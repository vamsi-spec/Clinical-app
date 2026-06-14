import torch
import logging
import math 
from pathlib import Path
from typing import Optional

from app.models.schemas import ScoredSegment
from app.config import settings

logger = logging.getLogger(__name__)

def load_wav2vec2_model():
    try:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        model_name = "facebook/wav2vec2-base-960h"
        logger.info(f"Loading Wav2vec2 model:" {model_name})

        processor = Wav2Vec2Processor.from_pretrained(model_name)
        model = Wav2Vec2ForCTC.from_pretrained(model_name)

        #set to inference mode
        #mandatory - without this Pytorch runs in training mode
        model.eval()

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)

        logger.info(f"Wav2vec2 model loaded")
        return processor,model
    except ImportError:
        logger.error("Transforments not installed")
        return None,None

    except Exception as e:
        logger.error(f"Failed to load Wav2Vec2: {e}")
        logger.warning("Continuing without Wav2Vec2 correction" "low confidence segments will not be corrected")
        return None, None


def load_audio_slice(audio_path: str,start: float,end: float,target_sr: int = 16000) -> Optional[any]:
    try:
        import librosa

        duration = end - start
        if duration < settings.min_segment_duration:
            logger.debug(f"Segment too short for correction " f"({duration:.2f}s < {settings.min_segment_duration}s)")
            return None

        audio, _ = librosa.load(audio_path,sr=target_sr,offset=start,duration=duration,mono=True)

        return audio

    except Exception as e:
        logger.error(f"Failed to load audio slice: {e}" f"start: {start}, end: {end}")
        return None


def correct_segment_audio(audio_array,wav2vec2_processor,wav2vec2_model) -> Optional[str]:
    try:
        device = next(wav2vec2_model.parameters()).device
        inputs = wav2vec2_processor(audio_array,sampling_rate=16000,return_tensors="pt",padding=True)

        input_values = inputs.input_values.to(device)

        with torch.no_grad():
            output = wav2vec2_model(input_values).logits

        predicted_ids = torch.argmax(logits,dim=-1)
        transcription = wav2vec2_processor.decode(predicted_ids[0])

        return transcription.lower().strip()
    except Exception as e:
        logger.error(f"Wav2vec2 inference failed: {e}")
        return None
        

def should_accept_correction(original: str,corrected: str,length_ratio_threshold: float = 3.0) -> bool:
    if not corrected or len(corrected.strip()) == 0:
        return False
    
    if not any(c.isalpha() for c in corrected):
        return False
    
    orig_len = len(original.split())
    corr_len = len(corrected.split())

    if orig_len > 0 and corr_len > 0:
        ratio = max(orig_len,corr_len) / min(orig_len,corr_len)
        if ratio > length_ratio_threshold:
            logger.debug(
                f"Correction rejected — length ratio too large: "
                f"{ratio:.1f} (original: '{original}', "
                f"corrected: '{corrected}')"
            )
            return False

        

    return True


def correct_low_confidence_segments(audio_path: str,scored_segments: list[ScoredSegment],wav2vec2_processor,wav2vec2_model) -> list[ScoredSegment]:
    if wav2vec2_processor is None or wav2vec2_model is None:
        logger.warning(
            "Wav2Vec2 not available — skipping correction. "
            "Low confidence segments will be flagged but not corrected."
        )
        return scored_segments

    flagged = [s for s in scored_segments if s.needs_review]

    if not flagged:
        logger.info("No segments flagged for correction")
        return scored_segments
    
    logger.info(f"Correcting {len(flagged)} low-confidence segments")

    corrected_cnt = 0
    rejected_cnt = 0
    failed_cnt = 0

    for segment in scored_segments:
        if not segment.needs_review:
            segment.corrected = False
            continue
            
        audio_slice = load_audio_slice(audio_path,segment.start,segment.end)
        if audio_slice is None:
            segment.corrected = False
            failed_cnt += 1
            continue

        corrected_text = correct_segment_audio(
            audio_slice,
            wav2vec2_processor,
            wav2vec2_model,
        )

        if corrected_text is None:
            segment.corrected = False
            failed_cnt += 1
            continue

        if should_accept_correction(segment.text,corrected_text):
            segment.original_text = segment.text
            segment.text = corrected_text
            segment.corrected = True
            corrected_count += 1
            logger.debug(
                f"Correction accepted at {segment.start:.1f}s: "
                f"'{segment.original_text}' → '{corrected_text}'"
            )
        else:
            segment.corrected = False
            rejected_cnt += 1

            logger.debug(
                f"Correction rejected at {segment.start:.1f}s: "
                f"kept original '{segment.text}'"
            )
    logger.info(
        f"Correction complete: "
        f"{corrected_cnt} corrected, "
        f"{rejected_cnt} rejected (original kept), "
        f"{failed_cnt} failed"
    )

    return scored_segments

def get_correction_stats(segments: list[ScoredSegment]) -> dict:
    
    total = len(segments)
    flagged = sum(1 for s in segments if s.needs_review)
    corrected = sum(1 for s in segments if s.corrected)

    return {
        "total_segments": total,
        "flagged_for_review": flagged,
        "corrected": corrected,
        "correction_rate": round(
            corrected / flagged * 100 if flagged > 0 else 0, 1
        ),
    }
            
        