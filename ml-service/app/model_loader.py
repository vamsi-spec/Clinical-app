import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_empty_model_state() -> dict:
    return {
        "whisper":            None,
        "diarization":        None,
        "wav2vec2_processor": None,
        "wav2vec2_model":     None,
        "nlp_bc5":            None,
        "nlp_sci":            None,
        "embedder":           None,
        "models_loaded":      False,
        "loading_errors":     [],
    }


def load_all_models_sync(model_state: dict) -> dict:
    from app.services.whisper_service import load_whisper_model
    from app.services.diarization_service import load_diarization_pipeline
    from app.services.correction_service import load_wav2vec2_model
    from app.services.ner_service import (
        load_ner_models, load_entity_linker,
    )
    from app.services.explainability_service import load_sentence_embedder

    try:
        model_state["whisper"] = load_whisper_model()
        logger.info("[worker]Whisper loaded successfully")
    except Exception as e:
        err = f"Whisper load failed: {e}"
        logger.error(f"[worker] FATAL: {err}")
        model_state["loading_errors"].append(err)
        raise RuntimeError(err)

    try:
        model_state["diarization"] = load_diarization_pipeline()
        logger.info("[worker] Pyannote loaded" if model_state["diarization"]
        else "⚠️  [worker] PyAnnote not loaded"
        )
    except Exception as e:
        logger.warning(f"⚠️  [worker] Diarization load failed: {e}")
        model_state["loading_errors"].append(f"Diarization: {e}")

    try:
        processor, model = load_wav2vec2_model()
        model_state["wav2vec2_processor"] = processor
        model_state["wav2vec2_model"] = model
        logger.info("[worker] wav2vec2 loaded" if processor else 
        "[worker] wav2vec2 not loaded")

    except Exception as e:
        logger.warning(f"⚠️  [worker] wav2vec2 load failed: {e}")
        model_state["loading_errors"].append(f"Wav2vec2: {e}")

    
    try:
        nlp_bc5, nlp_sci = load_ner_models()
        if nlp_bc5:
            nlp_bc5 = load_entity_linker(nlp_bc5)
            model_state["nlp_bc5"] = nlp_bc5
        model_state["nlp_sci"] = nlp_sci
        logger.info(
            f"✅ [worker] NER models loaded "
            f"(bc5={'yes' if nlp_bc5 else 'no'}, sci={'yes' if nlp_sci else 'no'})"
        )
    except Exception as e:
        logger.warning(f"⚠️  [worker] NER load failed: {e}")
        model_state["loading_errors"].append(f"NER: {e}")

    
    try:
        model_state["embedder"] = load_sentence_embedder()
        logger.info(
            "✅ [worker] Embedder loaded" if model_state["embedder"]
            else "⚠️  [worker] Embedder not loaded"
        )
    except Exception as e:
        logger.warning(f"⚠️  [worker] Embedder load failed: {e}")
        model_state["loading_errors"].append(f"Embedder: {e}")

    model_state["models_loaded"] = model_state["whisper"] is not None
    return model_state
