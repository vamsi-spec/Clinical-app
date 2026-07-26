import json
import logging
import signal
import sys

from app.kafka.config import create_consumer, parse_envelope, Topics, ConsumerGroups
from app.workers.pipeline_worker import process_visit_audio


logger = logging.getLogger(__name__)

_shutdown_requested = False

def _handle_shutdown_signal(signum, frame):
    global _shutdown_requested
    logger.info(f"Received signal {signum} — shutting down consumer loop gracefully...")
    _shutdown_requested = True


def run_consumer_loop(model_state: dict):
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)


    consumer = create_consumer(
        group_id=ConsumerGroups.ML_PIPELINE_WORKER,
        topics=[Topics.VISIT_AUDIO_UPLOADED],
    )

    logger.info("ML pipeline worker listening for visit.audio.uploaded...")

    try:
        while not _shutdown_requested:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                logger.error(f"Kafka consumer error: {msg.error()}")
                continue

            try:
                envelope = parse_envelope(msg.value())
                payload = envelope.get("payload",{})
                visit_id = payload.get("visitId","unknown")

                logger.info(f"Received visit.audio.uploaded: visit_id={visit_id}, "
                    f"eventId={envelope.get('eventId')}")

                process_visit_audio(payload, model_state)

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

            finally:
                consumer.commit(msg)
        
    finally:
        logger.info("Closing Kafka consumer...")
        consumer.close()
        logger.info("ML pipeline worker stopped.")
