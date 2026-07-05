import os
import uuid
import logging
import aiofiles
from pathlib import Path
from fastapi import APIRouter,UploadFile,File,Form,HTTPException,Depends
from fastapi.responses import JSONResponse
from typing import Optional

from app.models.schemas import TranscriptionResponse
from app.services.pipeline_service import run_transcription_pipeline
from app.config import settings


logger = logging.getLogger(__name__)
router = APIRouter()

#must check what multer accepts on the node side

ALLOWED_MIME_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/webm",
    "video/webm",  
    "application/octet-stream",
}


ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".mp4"}


MAX_FILE_SIZE = 100 * 1024 * 1024

def get_model_state():
    from app.main import model_state
    return model_state



#Temp file manager
#saves upload audio to /temp 
#after use clean it up

async def save_temp_audio(file: UploadFile,temp_dir: str = "temp") -> str:
    Path(temp_dir).mkdir(parents=True,exist_ok=True)

    original_name = file.filename or "audio.webm"
    ext = Path(original_name).suffix.lower()

    if not ext:
        ext = ".webm"

    temp_filename = f"audio-{uuid.uuid4().hex}{ext}"
    temp_path = os.path.join(temp_dir,temp_filename)

    #Stream file to disk - dont load entire file to memory
    #critical for large size

    total_bytes = 0
    try:
        async with aiofiles.open(temp_path,"wb") as f:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE:
                    await f.close()
                    os.unlink(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB"
                    )
                await f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500,detail=f"Failed to save audio : {str(e)}")
    
    logger.info(
        f"Audio saved: {temp_path} "
        f"({total_bytes / (1024*1024):.1f}MB)"
    )
    return temp_path

#clean up after pipeline is success orr fail

def cleanup_temp_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.unlink(path)
            logger.info(f"Cleaned up temp file: {path}")
    except Exception as e:
        logger.warning(f"Failed to clean up {path}: {e}")


@router.post("/",response_model=TranscriptionResponse,summary="Transcribe audio and detect speakers",description="""
    Accepts an audio file and returns a fully enriched transcript with:
    - Speaker-labeled segments (DOCTOR/PATIENT/FAMILY)
    - Confidence scores per segment
    - Low-confidence flags for doctor review
    - Auto-corrected medical terminology
    - Word-level timestamps for explainable notes
    """,)
async def transcribe_audio_endpoint(audio: UploadFile = File(
    ...,
        description="Audio file to transcribe. Supported: mp3, wav, m4a, ogg, webm"
),visit_id: str = Form(...,
        description="Visit ID from PostgreSQL — used for logging and Socket.IO room"),
        num_speakers: Optional[int] = Form(
        default=None,
        description="Optional: exact number of speakers if known. Improves diarization accuracy."
    ),
    specialty: str = Form(
        default="general",
        description="Doctor's specialty — used for domain-aware processing"
    ),
    model_state: dict = Depends(get_model_state),
        ):
        """
        Full transcription pipeline endpoint.
        Flow:
        1.validate file type and size
        2.save to temp
        3.run ml pipeline
        4.clean up temp
        5.return transcription response
        """

        temp_path = None
        try:
            content_type = audio.content_type or ""
            file_ext = Path(audio.filename or "").suffix.lower()

            if(content_type not in ALLOWED_MIME_TYPES and file_ext not in ALLOWED_EXTENSIONS):
                raise HTTPException(status_code=400,
                detail=(
                    f"Unsupported file type: {content_type}. "
                    f"Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}"
                ))
            
            if num_speakers is not None and not (1 <= num_speakers <= 6):
                raise HTTPException(status_code=400,
                detail="num_speakers must be between 1 and 6")

            if model_state.get("whisper") is None:
                raise HTTPException(status_code=503,detail=( "Whisper model not loaded. "
                    "ML service may still be initializing. "
                    "Retry in 30 seconds."))
            
            logger.info(f"Transcription request: visit_id={visit_id}, file={audio.filename}, num_speakers={num_speakers}, specialty={specialty}")

            #save file
            temp_path = await save_temp_audio(audio)

            #Run pipeline 
            #pipeline is cpu/gpu bound so run in thread pool
            import asyncio
            loop = asyncio.get_event_loop()

            result = await loop.run_in_executor(
                None,
                lambda: run_transcription_pipeline(
                    audio_path=temp_path,
                    model_state=model_state,
                    num_speakers=num_speakers,
                    specialty=specialty
                )
            )

            logger.info(f"Transcription complete: visit_id={visit_id}, "
            f"segments={len(result.segments)}, "
            f"language={result.detected_language}, "
            f"warnings={result.warnings}")

            return result

        except HTTPException:
            raise

        except RuntimeError as e:
            logger.error(
            f"Pipeline runtime error: visit_id={visit_id}, error={e}"
            )
            raise HTTPException(
            status_code=422,
            detail=f"Transcription failed: {str(e)}"
            )


        except Exception as e:
            logger.error(
                f"Unexpected error: visit_id={visit_id}, error={e}",
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
            detail=f"Internal error during transcription: {str(e)}"
            )
        finally:
            if temp_path:
                cleanup_temp_file(temp_path)

@router.get("/health",summary="Check transcription service health")

async def transcription_health(model_state: dict = Depends(get_model_state)):
    whisper_loaded = model_state.get("whisper") is not None
    diarization_loaded = model_state.get("diarization") is not None
    wav2vec2_loaded = (model_state.get("wav2vec2_processor") is not None and model_state.get("wav2vec2_model") is not None)

    all_critical_loaded = whisper_loaded

    status_code = 200 if all_critical_loaded else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_critical_loaded else "initializing",
            "models": {
                "whisper": {
                    "loaded": whisper_loaded,
                    "size": settings.whisper_model_size,
                    "critical": True,
                },
                "diarization": {
                    "loaded": diarization_loaded,
                    "critical": False,
                    "note": "Degrades gracefully — no speaker labels if unavailable"
                },
                "wav2vec2": {
                    "loaded": wav2vec2_loaded,
                    "critical": False,
                    "note": "Degrades gracefully — low confidence segments flagged but not corrected"
                },
            },
            "config": {
                "whisper_model": settings.whisper_model_size,
                "confidence_threshold": settings.confidence_threshold,
                "min_segment_duration": settings.min_segment_duration,
            }
        }
    )
    
        

            



        
        

    
