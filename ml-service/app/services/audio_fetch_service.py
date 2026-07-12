import os
import uuid
import logging
import httpx

logger = logging.getLogger(__name__)

TEMP_DIR = "temp"
DOWNLOAD_TIMEOUT = 60.0


async def download_audio_from_url(audio_url: str,visit_id: str) -> str:
    """
    download audio from a cloudinary streaming url to a local temp file,so the existing pipeline functions work unmodified

    """

    os.makedirs(TEMP_DIR,exist_ok=True)

    ext = os.path.splitext(audio_url.split("?")[0])[1] or ".webm"
    local_path = os.path.join(TEMP_DIR,f"worker-{visit_id}-{uuid.uuid4().hex[:8]}{ext}")

    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            async with client.stream("GET", audio_url) as response:
                response.raise_for_status()
                with open(local_path,"wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=1024*1024):
                        f.write(chunk)

        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        logger.info(f"Downloaded audio for visit {visit_id}: {size_mb}MB {local_path}")


        return local_path

    except Exception as e:
        logger.error(f"Failed to download audio for visit {visit_id}: {e}")
        if os.path.exists(local_path):
            os.unlink(local_path)
        raise RuntimeError(f"Audio download failed: {e}")


def cleanup_local_audio(local_path: str):
    try:
        if local_path and os.path.exists(local_path):
            os.unlink(local_path)
            logger.debug(f"Cleaned up worker temp file: {local_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up {local_path}: {e}")