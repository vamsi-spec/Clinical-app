import logging
from app.kafka.config import publish_event,Topics

logger = logging.getLogger(__name__)

def publish_progress(visit_id: str,status: str,message: str,progress: int):
    """
    publish a pipeline progress update.
    Consumed by Node's progress relay and forwarded to the doctor's UI via SocketId.

    Args:
        visit_id: PostgreSQL Visit ID — used as partition key
        status: PipelineStatus enum value as string
        message: Human-readable message for the UI
        progress: 0-100 percentage
    """

    publish_event(
        topic=Topics.VISIT_PIPELINE_PROGRESS,
        key=visit_id,
        payload={
            "visitId": visit_id,
            "status": status,
            "message": message,
            "progress": progress
        }
    )


def publish_transcription_done(visit_id: str,transcription_result: dict):
    """
    Published as transcription completes before intelligence pipeline starts
    """

    publish_event(
        topics=Topics.VISIT_TRANSCRIPTION_DONE,
        key=visit_id,
        payload={
            "visit_id": visit_id,
            "transcription": transcription_result,
        }
    )

def publish_pipeline_completed(visit_id: str,full_result: dict):
    """
    Published when the ENTIRE pipeline succeeds —
    transcription + NER + SOAP + CDS + billing + drugs.
    """
    publish_event(
        topic=Topics.VISIT_PIPELINE_COMPLETED,
        key=visit_id,
        payload={
            "visitId": visit_id,
            "result": full_result,
        },
    )

def publish_pipeline_failed(visit_id: str,error: str,failed_step: str):
    publish_event(
        topic=Topics.VISIT_PIPELINE_FAILED,
        key=visit_id,
        payload={
            "visitId": visit_id,
            "error": error,
            "failedStep": failed_step,
        }
    )

def publish_critical_drug_interaction(visit_id: str,interactions: list[dict]):
    """
    Published separately from the main completion event
    specifically for CRITICAL/HIGH severity drug interactions.

    Why a separate topic instead of waiting for pipeline
    completion: a critical interaction is time-sensitive —
    the doctor should see the warning as soon as it's found,
    not wait for SOAP generation and billing to also finish.
    A dedicated consumer group can push this as an
    urgent Socket.IO alert ahead of the full result.
    """

    publish_event(
        topic=Topics.DRUG_INTERACTION_DETECTED,
        key=visit_id,
        payload={
            "visitId": visit_id,
            "interactions": interactions,
        },
    )


    
