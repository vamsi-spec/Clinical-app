import asyncio
import logging
import time
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

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
