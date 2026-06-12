import torch
import logging
import os
from pathlib import Path
from typing import Optional


from app.models.schemas import DiarizationSegment,SpeakerRole
from app.config import settings



logger = logging.getLogger(__name__)


#Requires pyannote a hugging face token to automatically accepted
#Model download from HF_HOME
#https://huggingface.co/pyannote/speaker-diarization-3.1

def load_diarization_pipeline():
    """
    Load the pre-trained speaker diarization pipeline with model caching
    Returns None if loading fails rather than crashing pipeline
        pyannote.audio.Pipeline: Initialized diarization pipeline
    """

    try:
        from pyannote.audio import Pipeline

        token = settings.huggingface_token
        if not token or token == "your_huggingface_token_here":
            logger.warning("Hugging Face token missing no diarization")
            return None

        logger.info("Loading PyAnnote speaker diarization pipeline...")

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=token
        )

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        pipeline.to(device)

        logger.info(f"Diarization pipeline loaded successfully on {device}")

        return pipeline
    except ImportError:
        logger.warning("Pyannote not installed."
        "Run: pip install pyannote.audio")
        return None

    except Exception as e:
        logger.error(f"Failed to load diarization pipeline: {e}")
        logger.warning(
            "Continuing without diarization — "
            "speaker labels will not be available"
        )
        return None


def diarize_audio(audio_path: str,diarization_pipeline,num_speakers: Optional[int] = None,min_speakers: int = 1,max_speakers: int = 4) -> list[DiarizationSegment]:
    if diarization_pipeline is None:
        logger.warning("Diarization pipeline not loaded - returning empty segments")
        return []

    logger.info(f"Starting diarization: {audio_path}")

    try:
        diarize_kwargs = {}
        if num_speakers is not None:
            diarize_kwargs["num_speakers"] = num_speakers
            logger.info(f"Diarizing with fixed speaker count: {num_speakers}")
        else:
            diarize_kwargs["min_speakers"] = min_speakers
            diarize_kwargs["max_speakers"] = max_speakers
            logger.info(f"Diarizing with speaker range: {min_speakers}-{max_speakers}")

        diarization_result = diarization_pipeline(
            audio_path,
            **diarize_kwargs
        )

        segments = []
        for turn, _, speaker in diarization_result.itertracks(
            yield_label=True
        )
            if (turn.end - turn.start) < 0.3:
                continue

            segments.append(DiarizationSegment(
                speaker=speaker,
                start=round(turn.start, 3),
                end=round(turn.end, 3)
            ))

        segments.sort(key=lambda x: x.start)
        
        unique_speakers = set(s.speaker for s in segments)

        logger.info(f"Diarization complete. Speakers: {list(unique_speakers)}")

        return segments

    except Exception as e:
        logger.error(f"Diarization failed for {audio_path}: {e}")
        logger.warning("Returning empty segments")
        return []


def assign_speaker_roles(diarization_segments: list[DiarizationSegment],whisper_segments: list = None) -> dict[str,SpeakerRole]:
    """
    Map Pyannote speaker ids to clinical roles

    Assign clinical roles using multiple rules and heuristics
    combining several weak signals into one strong decision
    """

    if not diarization_segments:
        return {}
    speakers = list(set(s.speaker for s in diarization_segments))

    if len(speakers) == 1:
        role_map = {speakers[0]: SpeakerRole.DOCTOR}
        logger.warning("Single speaker detected - assigned as doctor")
        return role_map

    scores = {speaker: 0.0 for speaker in speakers}

    #factor 1 who speaks first - mostly doctor
    first_segment = min(diarization_segments, key=lambda s: s.start)
    scores[first_segment.speaker] += 3.0
    logger.debug(f"First speaker: {first_segment.speaker} (+3.0)")


    #factor 2 - Doctors may asks many short questions - so more turns
    #patients may have long monologues (narrating)
    turn_counts = {spk: 0 for spk in speakers}
    for seg in diarization_segments:
        turn_counts[seg.speaker] += 1

    max_turns_speaker = max(turn_counts,key=turn_counts.get)
    scores[max_turns_speaker] += 2.0
    logger.debug(f"Max turns speaker: {max_turns_speaker} ({turn_counts[max_turns_speaker]} turns)")
    

    #factor 3 - Average turn duration (we give less weight - because patient can narrate long stories)
    #low duration might be doctor
    speaker_durations = {spk: [] for spk in speakers}
    for seg in diarization_segments:
        speaker_durations[seg.speaker].append(seg.end - seg.start)
    
    avg_durations = {
        speaker: sum(durations) / len(durations)
        for speaker,durations in speaker_durations.items()
        if durations
    }

    min_avg_speaker = min(avg_durations,key = avg_durations.get)
    scores[min_avg_speaker] += 1.5
    logger.debug(f"Avg turn durations: {avg_durations} "
        f"→ {min_avg_speaker} +1.5 (shorter avg = doctor)")

    
    #factor-4: short turn ratio (weight: 2.0)

    short_turn_threshold = 3.0
    short_turn_counts = {spk: 0 for spk in speakers}

    for seg in diarization_segments:
        if(seg.end - seg.start) < short_turn_threshold:
            short_turn_counts[seg.speaker] += 1

    max_short_turn_spk = max(short_turn_counts,key=short_turn_counts.get)

    if short_turn_counts[max_short_turn_spk] > 0:
        scores[max_turns_speaker] += 2.0
        logger.debug(f"Short turn counts: {short_turn_counts} "
            f"→ {max_short_turns_speaker} +2.0")

    #Factor-5 Medical terminology

    if whisper_segments:
        try:
            terminology_scores = _score_medical_terminology(whisper_segments,speakers)
            for speaker,term_score in terminology_scores.items():
                scores[speaker] += term_score * 2.5
                logger.debug(f"Terminology score: {speaker} +{term_score * 2.5:.2f}")
        except Exception as e:
            logger.warning(f"Terminology scoring failed: {e}")
    logger.info(f"Final scores: {scores}")

    sorted_by_score = sorted(scores.items(),key=lambda x: x[1],reverse=True)

    role_map = {}

    if len(sorted_by_score) >= 2:
        role_map[sorted_by_score[0][0]] = SpeakerRole.DOCTOR
        role_map[sorted_by_score[1][0]] = SpeakerRole.PATIENT

        for speaker_id,_ in sorted_by_score[2:]:
            role_map[speaker_id] = SpeakerRole.FAMILY
    elif len(sorted_by_score) == 1:
        role_map[sorted_by_score[0][0]] = SpeakerRole.DOCTOR

    logger.info(
        f"Role assignment result: "
        f"{[f'{s}={r.value}' for s, r in role_map.items()]}"
    )

    return role_map

def _score_medical_terminology(whisper_segments: list,speakers: list[str]) -> dict[str,float]:
    """
    Speaker with more medical terms = more likely doctor.
    just using simple regex matching for common medical terms for now.
    """

    CLINICAL_TERMS = {
        # Examination terms
        "auscultation", "palpation", "percussion", "bilateral",
        "systolic", "diastolic", "tachycardia", "bradycardia",
        "hypertension", "hypotension", "febrile", "afebrile",

        # Prescription language
        "prescribe", "prescribed", "milligram", "dosage", "twice daily",
        "once daily", "orally", "intravenous", "subcutaneous",
        "contraindicated", "titrate", "titration",

        # Diagnostic terms
        "differential", "diagnosis", "prognosis", "etiology",
        "pathology", "acute", "chronic", "idiopathic",
        "comorbidity", "complication",

        # Lab terms
        "hemoglobin", "creatinine", "bilirubin", "glucose",
        "hba1c", "ecg", "ultrasound", "mri", "ct scan",

        # Instruction terms — doctors give instructions
        "follow up", "follow-up", "refer", "referral",
        "admission", "discharge", "monitor", "review",

        # Drug names — partial match handles generics
        "metformin", "atorvastatin", "amlodipine", "losartan",
        "lisinopril", "metoprolol", "aspirin", "warfarin",
        "insulin", "amoxicillin", "azithromycin",
    }

    speaker_term_counts = {speaker: 0 for speaker in speakers}
    speaker_word_counts = {speaker: 0 for speaker in speakers}

    for seg in whisper_segments:
        speaker = getattr(seg,"speaker",None)
        if not speaker or speaker not in speakers:
            continue
        
        text = seg.text.lower()
        words = text.split()
        speaker_word_counts[speaker] += len(words)

        for term in CLINICAL_TERMS:
            if term in text:
                speaker_term_counts[speaker] += 1

    densities = {}
    for speaker in speakers:
        word_count = speaker_word_counts.get(speaker,0)
        term_count = speaker_term_counts.get(speaker,0)

        if word_count > 0:
            densities[speaker] = (term_count/word_count) * 100
        else:
            densities[speaker] = 0.0

    max_density = max(densities.values()) if densities else 1.0

    if max_density == 0:
        return {speaker: 0.0 for speaker in speakers}

    return {
        speaker: density / max_density
        for speaker, density in densities.items()
    }
    
    
    

    
    





