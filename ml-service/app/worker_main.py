import logging
import sys


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("ml-worker")

def main():
    from app.model_loader import build_empty_model_state, load_all_models_sync
    from app.kafka.consumer import run_consumer_loop
    from app.kafka.config import flush_producer

    logger.info("Clinical Note Intelligence — ML Pipeline Worker Starting")

    model_state = build_empty_model_state()

    try:
        load_all_models_sync(model_state)
    except RuntimeError as e:
        logger.error(
            f"FATAL: {e} — worker cannot process audio without Whisper. Exiting."
        )
        sys.exit(1)

    logger.info("WORKER MODEL LOAD COMPLETE")
    logger.info(f"  Whisper:    {'whisper' if model_state['whisper'] else 'not loaded'}")
    logger.info(f"  PyAnnote:   {'diarization' if model_state['diarization'] else 'not loaded'}")
    logger.info(f"  Wav2Vec2:   {'wav2vec2_processor' if model_state['wav2vec2_processor'] else 'not loaded'}")
    logger.info(f"  NER bc5cdr: {'nlp_bc5' if model_state['nlp_bc5'] else 'not loaded'}")
    logger.info(f"  NER sci_md: {'nlp_sci' if model_state['nlp_sci'] else 'not loaded'}")
    logger.info(f"  Embedder:   {'embedder' if model_state['embedder'] else 'not loaded'}")

    try:
       run_consumer_loop(model_state)
    finally:
        flush_producer()
        
         





if __name__ == "__main__":
    main()

