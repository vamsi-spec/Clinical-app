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
    "nlp_bc5": None,
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


def _load_ner_models():
    try:
        from app.services.ner_service import load_ner_models,add_negation_detector,load_entity_linker
        nlp_bc5,nlp_sci = load_ner_models()

        if nlp_bc5:
            # Add UMLS entity linker (Layer 1 of hybrid classifier)
            nlp_bc5 = load_entity_linker(nlp_bc5)
            model_state["nlp_bc5"] = nlp_bc5
            logger.info("en_ner_bc5cdr_md loaded with UMLS linker")

        if nlp_sci:
            model_state["nlp_sci"] = nlp_sci
            logger.info("en_core_sci_md loaded")

        if not nlp_bc5 and not nlp_sci:
            logger.warning("No NER models loaded — entity extraction unavailable")

    except Exception as e:
        logger.warning(f"NER models load failed: {e}")
        model_state["loading_errors"].append(f"NER: {e}")

def _load_emedder():
    """
    Load sentence transformer for:
    1. Explainability service — semantic SOAP→audio matching
    2. NER classifier Layer 2 — context-aware symptom/diagnosis classification
    3. NER classifier speaker role Layer 2 — prototype matching
    """
    try:
        from app.services.explainability_service import load_sentence_embedder
        embedder = load_sentence_embedder()
        model_state["embedder"] =embedder
        if embedder:
            logger.info("Sentence transformer loaded")
        else:
            logger.warning("Sentence transformer not loaded")
    except Exception as e:
        logger.warning(f"Embedder load failed: {e}")
        model_state["loading_errors"].append(f"Embedder: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ML Service starting up...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Whisper model size: {settings.whisper_model_size}")
    logger.info(f"Ollama model: {settings.ollama_model}")

    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=4) as executor:
        # Step 1: Whisper (CRITICAL — must succeed)
        logger.info("Loading Whisper (critical model)...")
        try:
            await loop.run_in_executor(executor, _load_whisper)
        except RuntimeError as e:
            logger.error(
                f"FATAL: Whisper failed to load — {e}. "
                "Transcription requests will return 503."
            )

        # Step 2: Phase 4 non-critical models in parallel
        logger.info("Loading Phase 4 models in parallel (PyAnnote + Wav2Vec2)...")
        await asyncio.gather(
            loop.run_in_executor(executor, _load_diarization),
            loop.run_in_executor(executor, _load_wav2vec2),
            return_exceptions=True,
        )

        # Step 3: Phase 5 non-critical models in parallel
        logger.info("Loading Phase 5 models in parallel (NER models + Embedder)...")
        await asyncio.gather(
            loop.run_in_executor(executor, _load_ner_models),
            loop.run_in_executor(executor, _load_emedder),
            return_exceptions=True,
        )

    # Mark service ready
    if model_state["whisper"] is not None:
        model_state["models_loaded"] = True
    else:
        logger.error(
            "ML Service degraded — Whisper not loaded. "
            "Transcription requests will fail with 503."
        )

    

    

    logger.info("=" * 55)
    logger.info("ML SERVICE STARTUP COMPLETE")
    logger.info(f"  Whisper:       {'Ready' if model_state['whisper'] else 'Failed (critical)'}")
    logger.info(f"  PyAnnote:      {'Ready' if model_state['diarization'] else 'Not loaded (no speaker labels)'}")
    logger.info(f"  Wav2Vec2:      {'Ready' if model_state['wav2vec2_processor'] else 'Not loaded (no medical correction)'}")
    logger.info(f"  bc5cdr NER:    {'Ready' if model_state['nlp_bc5'] else 'Not loaded (no drug/disease NER)'}")
    logger.info(f"  sci_md NER:    {'Ready' if model_state['nlp_sci'] else 'Not loaded (no broad NER)'}")
    logger.info(f"  Embedder:      {'Ready' if model_state['embedder'] else 'Not loaded (keyword matching only)'}")
    logger.info(f"  Load errors:   {len(model_state['loading_errors'])}")

    if model_state["loading_errors"]:
        logger.info("  Errors:")
        for err in model_state["loading_errors"]:
            logger.warning(f"    • {err}")

    yield

    logger.info("ML service shutting down...")

    import glob
    temp_files = glob.glob("temp/audio-*")
    for f in temp_files:
        try:
            import os
            os.unlink(f)
        except Exception:
            pass
    if temp_files:
        logger.info(f"Cleaned {len(temp_files)} temp files on shutdown")


app = FastAPI(title="Clinical Note Intelligence — ML Service",
    description=(
        "Handles transcription, speaker diarization, NER, "
        "SOAP generation, billing codes, and drug interaction detection"
    ),
    version="1.0.0",
    lifespan=lifespan,)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5000",
        "http://backend:5000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.routers import transcription
from app.routers import soap
from app.routers import ner
app.include_router(transcription.router,prefix="/transcribe",tags=["Transcription"])

app.include_router(soap.router, prefix="/soap", tags=["SOAP Generation"])
app.include_router(ner.router,prefix="/ner",tags=[" Clinical NER"])




@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
        "models_loaded": model_state['models_loaded'],
        "models": {
            "whisper": model_state["whisper"] is not None,
            "diarization": model_state["diarization"] is not None,
            "wav2vec2": model_state["wav2vec2_processor"] is not None,
            "nlp_bc5cdr": model_state["nlp_bc5"] is not None,
            "nlp_sci_md": model_state["nlp_sci"] is not None,
            "embedder": model_state["embedder"] is not None,
        },
        "loading_errors": model_state["loading_errors"],
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