import asyncio
import logging
import time
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from app.models.schemas import (
    TranscriptionResponse,
    EnrichedSegment,
    SpeakerRole,
    PipelineStatus,
)

from app.services.whisper_service import transcribe_audio

from app.services.confidence_service import (
    filter_noise_segments,
    score_all_segments,
    get_confidence_stats,
)

from app.services.diarization_service import (
    diarize_audio,
    assign_speaker_roles,
    assign_speakers_to_segments,
    get_diarization_stats,
)
from app.services.correction_service import (
    correct_low_confidence_segments,
    get_correction_stats,
)

logger = logging.getLogger(__name__)



def default_status_callback(status: str,message: str,progress: int):
    logger.info(f"[{status}] {message} ({progress}%)")


def run_whisper_and_diarization_parallel(audio_path: str,model_state: dict,num_speakers: Optional[int] = None) -> tuple:
    whisper_result = None
    diarization_segments = []
    whisper_error = None
    diarization_error = None

    def run_whisper():
        try:
            return transcribe_audio(audio_path,model_state["whisper"])
        except Exception as e:
            logger.error(f"Whisper failed in paralle runner:{e}")
            return e
    
    def run_diarization():
        try:
            if model_state.get("diarization") is None:
                logger.warning("Diarization model not loaded - skipping")
                return []
            return diarize_audio(audio_path,model_state["diarization"],num_speakers=num_speakers)
        except Exception as e:
            logger.error(f"Diarization failed in paralle runner:{e}")
            return e
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        whisper_future = executor.submit(run_whisper)
        diarization_future = executor.submit(run_diarization)

        whisper_output = whisper_future.result()
        diarization_output = diarization_future()

    if isinstance(whisper_output,Exception):
        whisper_error = str(whisper_output)
        whisper_result = None
    else:
        whisper_result = whisper_output
    
    if isinstance(diarization_output, Exception):
        diarization_error = str(diarization_output)
        diarization_segments = []
    else:
        diarization_segments = diarization_output

    if whisper_error:
        logger.error(f"Whisper error: {whisper_error}")

    if diarization_error:
        logger.warning(
            f"Diarization error: {diarization_error} — "
            "continuing without speaker labels"
        )

    return whisper_result, diarization_segments


def convert_to_enriched_segments(scored_segments: list,) -> list[EnrichedSegment]:
    enriched = []
    for seg in scored_segments:
        if isinstance(seg,dict):
            get = lambda key,default=None: seg.get(key,default)
        else:
            get = lambda key,default=None: getattr(seg,key,default)

        role = get("role",SpeakerRole.UNKNOWN)
        if isinstance(role,str):
            try:
                role = SpeakerRole(role)
            except ValueError:
                role = SpeakerRole.UNKNOWN
        
        enriched.append(EnrichedSegment(
            id=get("id",len(enriched)),
            start=get("start",0.0),
            end=get("end",0.0),
            text=get("text",""),
            speaker=get("speaker", "UNKNOWN"),
            role=role,
            confidence=get("confidence", 1.0),
            needs_review=get("needs_review", False),
            corrected=get("corrected", False),
            original_text=get("original_text", None),
            words=get("words", []),
        ))
        return enriched


def run_transcription_pipeline(audio_path: str,model_state: dict,num_speakers: Optional[int] = None,specialty: str = "general",status_callback=None) -> TranscriptionResponse:
    callback = status_callback or default_status_callback
    pipeline_steps_completed = []
    warnings = []
    start_time = time.time()

    logger.info(f"Pipeline starting audio={audio_path}",f"specialty={specialty}")

    #Step - 1 parallel Whisper + Pyannote
    callback(PipelineStatus.TRANSCRIBING,"Transcribing audio and detecting speakers...",10)

    whisper_result,diarization_segments = run_whisper_and_diarization_parallel(
        audio_path,
        model_state,
        num_speakers=num_speakers
    )

    if whisper_result is None:
        raise RuntimeError("Whisper transcription failed - no output" "check audio file format and model loading")

    pipeline_steps_completed.append("transcription")
    logger.info(f"Step 1 complete: {len(whisper_result.segments)} raw segments, "
        f"language={whisper_result.detected_language}")

    if not diarization_segments:
        warnings.append(
            "Speaker diarization unavailable — "
            "transcript will not have speaker labels"
        )
    else:
        pipeline_steps_completed.append("diarization")
        logger.info(
            f"Diarization complete: {len(diarization_segments)} turns"
        )

    #Step 2 -> Noise Filtering and Punctuation

    callback(PipelineStatus.CONFIDENCE_SCORING,"Filtering noise and scoring confidence...")

    filtered_segments = filter_noise_segments(whisper_result.segments)

    if not filtered_segments:
        warnings.append("All segments were filtered as noise — audio may be silent")
        return TranscriptionResponse(
            full_text="",
            segments=[],
            detected_language=whisper_result.detected_language,
            duration=whisper_result.duration,
            speaker_count=0,
            low_confidence_count=0,
            corrected_count=0,
            pipeline_steps_completed=pipeline_steps_completed,
            warnings=warnings + ["No speech detected in audio"],
        )

    from app.models.schemas import WhisperRawResult
    filtered_whisper_result = WhisperRawResult(
        segments=filtered_segments,
        full_text=" ".join(s.text for s in filtered_segments),
        detected_language=whisper_result.detected_language,
        duration=whisper_result.duration,
    )

    #Step 3 -> Confidence scoring
    #convert log-probs to 0 - 1 confidence scoring

    scored_segments = score_all_segments(filtered_whisper_result)
    pipeline_steps_completed.append("confidence_scoring")

    low_confidence_count = sum(1 for s in scored_segments if s.needs_review)
    logger.info(
        f"Step 3 complete: {len(scored_segments)} scored segments, "
        f"{low_confidence_count} segments need review"
    )

    #step4 -> wav2vec2 correction
    callback(PipelineStatus.CORRECTING,"Applying medical vocabulary correction...",50)

    wav2vec2_processor = model_state.get("wav2vec2_processor")
    wav2vec2_model = model_state.get("wav2vec2_model")

    if wav2vec2_processor and wav2vec2_model and low_confidence_count > 0:
        try:
            scored_segments = correct_low_confidence_segments(
                audio_path,scored_segments,wav2vec2_processor,wav2vec2_model
            )
            pipeline_steps_completed.append("wav2vec2_correction")
        except Exception as e:
            logger.warning(f"Wav2Vec2 correction failed: {e} — continuing")
            warnings.append(f"Medical correction unavailable: {str(e)}")

    else:
        if not wav2vec2_processor:
            warnings.append("Wav2Vec2 not loaded — low confidence segments flagged but not corrected")

    corrected_count = sum(1 for s in scored_segments if getattr(s,"corrected",False))

    #Step 5 -> speaker role assignment
    callback(PipelineStatus.DIARIZING,"Assigining speaker roles...",65)

    role_map = {}
    if diarization_segments:
        try:
            role_map = assign_speaker_roles(
                diarization_segments,whisper_segments=scored_segments
            )

            pipeline_steps_completed.append("speaker_role_assignment")
            logger.info(f"Role map: {role_map}")

        except Exception as e:
            logger.warning(f"Role assignment failed: {e}")
            warnings.append("Speaker role assignment failed - using UNKNOWN")

    
    #step 6 -> Assign speaker to segments

    callback(PipelineStatus.MERGING,"Mergin transcript with speaker labels...",80)

    try:
        scored_segments = assign_speakers_to_segments(scored_segments,diarization_segments,role_map)
        pipeline_steps_completed.append("speaker_assignment")
    
    except Exception as e:
        logger.warning("speaker_assignment failed {e}")
        warnings.append("speaker_assignment failed - segments have no speaker labels")

    #step 7 convert to final schema
    #Transform to enriched segment

    enriched_segments = convert_to_enriched_segments(scored_segments)


    #step 8 - Build response
    callback(PipelineStatus.COMPLETED,"Transcription pipeline completed.",100)

    full_text = " ".join(seg.text for seg in enriched_segments).strip()

    unique_speakers = set(seg.speaker for seg in enriched_segments if seg.speaker != "UNKNOWN")

    elapsed = round(time.time() - start_time, 2)
    logger.info(
        f"Pipeline complete in {elapsed}s: "
        f"{len(enriched_segments)} segments, "
        f"{len(unique_speakers)} speakers, "
        f"{corrected_count} corrections"
    )

    return TranscriptionResponse(
        full_text=full_text,
        segments=enriched_segments,
        detected_language=whisper_result.detected_language,
        duration=whisper_result.duration,
        speaker_count=len(unique_speakers),
        low_confidence_count=low_confidence_count,
        corrected_count=corrected_count,
        pipeline_steps_completed=pipeline_steps_completed,
        warnings=warnings,
    )



    

    
    
