import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Callable

from confluent_kafka import Producer, Consumer, KafkaError, KafkaException

logger = logging.getLogger(__name__)

class Topics:
    VISIT_AUDIO_UPLOADED      = "visit.audio.uploaded"
    VISIT_TRANSCRIPTION_DONE  = "visit.transcription.done"
    VISIT_PIPELINE_PROGRESS   = "visit.pipeline.progress"
    VISIT_PIPELINE_COMPLETED  = "visit.pipeline.completed"
    VISIT_PIPELINE_FAILED     = "visit.pipeline.failed"
    DRUG_INTERACTION_DETECTED = "drug.interaction.detected"

    PATIENT_VITALS_RECORDED = "patient.vitals.recorded"
    AUDIT_EVENTS             = "audit.events"


class ConsumerGroups:
    ML_PIPELINE_WORKER = "ml-service-pipeline-worker"

def get_kafka_brokers() -> str:
    return os.getenv("KAFKA_BROKERS","localhost:9092")

#Producer Singleton pattern

_producer: Optional[Producer] = None

def get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer is None:
        _producer = Producer({
            "bootstrap.servers": get_kafka_brokers(),
            "client.id": "clinical-note-ml-service",
            "acks": "all",
            "retries": 5,
            "retry.backoff.ms": 300
        })
        logger.info("Kafka producer initialized")
    return _producer


def _delivery_callback(err,msg):
    """
    called asynchronously by librdkafka after each publish attempt.
    Required for confluent kafka's async produce() - without this callback registered, delivered failures are silently swallowed.
    """

    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.debug(
            f"Message delivered to {msg.topic()} "
            f"[partition {msg.partition()}] at offset {msg.offset()}"
        )

def publish_event(topic: str,key: str,payload: dict) -> str:
    """
    Publish an event to Kafka with the same envelope
    structure used on the Node side, so consumers on
    either language can parse messages identically.

    Args:
        topic: One of the Topics.* constants
        key: Partition key — typically visit_id, ensures
             all events for one visit are ordered
        payload: The event-specific data dict

    Returns:
        event_id (UUID string) for logging/tracing
    """

    producer = get_producer()

    event_id = str(uuid.uuid4())

    envelope = {
        "eventId": event_id,
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "source": "ml-service",
        "payload": payload
    }

    try:
        producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(envelope).encode("utf-8"),
            callback=_delivery_callback
        )

        # poll(0) triggers any pending delivery callbacks
        # without blocking — must be called periodically
        # or the internal librdkafka queue fills up
        producer.poll(0)

        logger.info(f"Published event to {topic}: key={key}, eventId={event_id}")
        return event_id

    except KafkaException as e:
        logger.error(f"Failed to publish to {topic}: {e}")
        raise

def flush_producer(timeout: float = 10.0):
    """
    Block until all pending messages are delivered.
    Call this before process shutdown to avoid losing
    buffered messages that haven't been sent yet.
    """

    if _producer is not None:
        remaining  = _producer.flush(timeout)
        if remaining > 0:
            logger.warning(f"{remaining} messages still in queue flush timeout")


def create_consumer(group_id: str,topics: list[str]) -> Consumer:
    consumer = Consumer({
        "bootstrap.servers": get_kafka_brokers(),
        "group.id": group_id,
        "client.id": "clinical-note-ml-service",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "session.timeout.ms": 30000,
        "heartbeat.interval.ms": 3000,
    })

    consumer.subscribe(topics)

    logger.info(f"Consumer created for group {group_id} for topics {topics}")

    return consumer

def parse_envelope(raw_message_value: bytes) -> dict:
    """
    Parse the standard event envelope from a raw Kafka message.
    Shared parsing logic used by every consumer in this service.
    """

    try:
        return json.loads(raw_message_value.decode("utf-8"))

    except (json.JSONDecodeError,UnicodeDecodeError) as e:
        logger.error(f"Failed to parse Kafka message envelope: {e}")
        raise

    


