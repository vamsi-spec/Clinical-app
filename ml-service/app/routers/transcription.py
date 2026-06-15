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
router = APIRouter

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

    #Stream file to dist - dont load entire file to memory
    #critical for large size

    total_bytes = 0
    try:
        async with aiofiles.open(temp_path,"wb") as f:
            while chunk := await file.read(1024 * 1024)
            total_bytes += len(chunk)
            if total_bytes > MAX_FILE_SIZE
            await f.close()
            os.unlink(temp_path)
            raise HTTPException(
                status_code=413,
                detail = f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB"
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




        
        

    
