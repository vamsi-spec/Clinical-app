from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
import logging 
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ml-service")


model_state = {
    "whisper": None,
    "diarization": None,
    "wav2vec2_processor": None,
    "wav2vec2_model": None,
    "nlp_sci": None,
    "embedder": None,
    "models_loaded":False,
    "loading_errors": [],
}


def _load_whisper():
    try:
        from app.services.whisper_service import load_whisper_model
        model = load_whisper_model()
        model_state["whisper"] = model
        logger.info("Whisper loaded successfully")
    except Exception as e:
        error = f"Whisper load failed: {str(e)}"
        logger.error(f"Failed to load Whisper: {e}")
        model_state["loading_errors"].append(error)
        raise RuntimeError(error)

def _load_diarization():
    try:
        from app.services.diarization_service import load_diarization_pipeline
        pipeline = load_diarization_pipeline()
        model_state["diarization"] = pipeline
        if pipeline:
            logger.info("Pyannote diarization model loaded successfully")
        else:
            logger.warning("PyAnnote not loaded — check HUGGINGFACE_TOKEN in .env")
    except Exception as e:
        error = f"Diarization load failed: {str(e)}"
        logger.warning(error)
        model_state["loading_errors"].append(error)
        #continue without diarization

def _load_wav2vec2():
    try:
        from app.services.correction_service import load_wav2vec2_model
        processor,model = load_wav2vec2_model()
        model_state["wav2vec2_processor"] = processor
        model_state["wav2vec2_model"] = model
        if processor and model:
            logger.info("✅ Wav2Vec2 loaded")
        else:
            logger.warning("⚠️  Wav2Vec2 not loaded")
    except Exception as e:
        error = f"Wav2Vec2 load failed: {e}"
        logger.warning(error)
        model_state["loading_errors"].append(error)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ML Service starting up...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Whisper model size: {settings.whisper_model_size}")
    logger.info(f"Ollama model: {settings.ollama_model}")
    


    logger.info("ML service ready")

    yield

    logger.info("ML Service shutting down...")


app = FastAPI(
    title="Clinical Note Intelligence - ML Service",
    description="Handles transcription,NER SOAP generation billing codes ,and drug interaction detection",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
        "models_loaded": model_state['models_loaded'],
        "models": {
            "whisper": model_state["whisper"] is not None,
            "diarization": model_state["diarization"] is not None,
            "ner": model_state["nlp_sci"] is not None,
            "embedder": model_state["embedder"] is not None,
        },
        "config": {
            "whisper_model": settings.whisper_model_size,
            "ollama_model": settings.ollama_model,
            "confidence_threshold": settings.confidence_threshold,
        },
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "error": str(exc) if settings.environment == "development" else None,
        },
    )