import whisper
import torch
import logging
import os
from pathlib import Path

from app.config import settings
from app.models.schemas import (RawWhisperSegment,WordTimestamp,WhisperRawResult)

logger = logging.getLogger(__name__)


def load_whisper_model() -> whisper.Whisper:
    """

    load whisper model based on model size and into memory || called once at fastapi startup
    """

    model_size = settings.whisper_model_size
    logger.info(f"Loading whisper model:{model_size}")

    device = "cuda" if torch.cuda.is_available() else "cpu"

    if device == "cpu":
        logger.warning("Whisper running on cpu - transcription will be slow.")
    model = whisper.load_model(model_size,device=device)
    logger.info(f"Successfully loaded whisper model {model_size} on {device}")
    return model


def validate_audio_file(audio_path: str) -> None:
    path = Path(audio_path)

    if not path.exists():
        raise ValueError(f"Audio file not found:{audio_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file:{audio_path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Empty audio file is not allowed:{audio_path}")
        
    max_size = 100 * 1024 * 1024
    if file_size > max_size:
        raise ValueError(f"File size {file_size / (1024*1024):.1f}Mb exceeds the maximum limit of 100Mb")

    allowed_extensions = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".mp4"}
    if path.suffix.lower() not in allowed_extensions:
        raise ValueError(
            f"Unsupported audio format: {path.suffix}. "
            f"Allowed: {', '.join(allowed_extensions)}"
        )

def transcribe_audio(audio_path: str,whisper_model:whisper.Whisper) -> WhisperRawResult:
    logger.info(f"Starting transcription for {audio_path}")
    
    validate_audio_file(audio_path)
    

    use_fp16 = torch.cuda.is_available()

    try:
        result = whisper_model.transcribe(
            audio_path,
            language=None,
            word_timestamps=True,
            verbose=False,
            fp16 = use_fp16,
            condition_on_previous_text=True,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            logprob_threshold=-1.0,
            no_speech_threshold=0.6,
        )

        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            raise RuntimeError(f"Failed to transcribe audio: {str(e)}")

        
        segments = []
        for seg in result.get("segments",[]):
            no_speech_prob = seg.get("no_speech_prob",0.0)
            if no_speech_prob > 0.90:
                logger.debug("Skipping likely non-speech segment at" f"{seg['start']:.1f}s(no_speech_prob:{no_speech_prob:.2f})")
                continue

            segment_duration = seg["end"] - seg["start"]
            if(segment_duration < 0.3):
                continue


            words = []
            for word_data in seg.get("words",[]):
                words.append(WordTimestamp(
                    word=word_data.get("word","").strip(),
                    start=round(word_data.get("start",0.0),3),
                    end=round(word_data.get("end",0.0),3),
                    confidence=round(float(word_data.get("probability",1.0)),3)
                ))
            segments.append(RawWhisperSegment(
                id=seg.get("id",len(segments)),
                start=round(seg["start"],3),
                end=round(seg["end"],3),
                text=seg["text"].strip(),
                avg_logprob=round(seg.get("avg_logprob",-0.5),4),
                no_speech_prob=round(no_speech_prob,4)
                words=words
            ))

        duration = 0.0
        if segments:
            duration=segments[-1].end
        elif result.get("segments"):
            duration = result["segments"][-1].get("end",0.0)

        full_text = " ".join(seg.text for seg in segments).strip()

        detected_language = result.get("language","en")

        logger.info(f"Transcription completed in{duration:.}s,{len(segments)} segments",f"Language: {detected_language}")

        if not segments:
            logger.warning("No valid segments extracted from whisper output.")

        return WhisperRawResult(
            segments=segments,
            full_text=full_text,
            detected_language=detected_language,
            duration=round(duration,2),
        )


LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
}


def get_language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code.upper())
        
            
            

        

    

    

    

    