import logging
import time
from typing import Optional

from app.services.audio_fetch_service import download_audio_from_url, cleanup_local_audio
from app.services.pipeline_service import run_transcription_pipeline
from app.services.ner_service import extract_clinical_entities, build_speaker_transcript
from app.services.llm_service import run_llm_pipeline
from app.services.explainability_service import build_explainable_soap
from app.services.billing_service import suggest_billing_codes
from app.services.drug_interaction_service import check_drug_interactions_sync
from app.kafka.producer import (
    publish_progress,
    publish_transcription_done,
    publish_pipeline_completed,
    publish_pipeline_failed,
    publish_critical_drug_interaction,
)

logger = logging.getLogger(__name__)


#Main Pipeline Entry Point
#Called by the kafka consumer loop for every visit.audio.uploaded message received

# This function owns the ENTIRE lifecycle of processing one visit — download, transcribe, extract, generate, bill, check drugs, publish result, clean up. 
# If anything raises partway through, the except block ensures a visit.pipeline.failed event still fires so the Visit doesn't sit stuck in Node's database forever showing "processing."

def process_visit_audio(payload: dict,model_state: dict):
    visit_id = payload["visitId"]
    audio_url  = payload["audioUrl"]
    specialty = payload.get("specialty","general")
    patient_context = payload.get("patientContext")
    num_speaker = payload.get("numSpeakers")

    local_audio_path = None
    start_time = time.time()

    logger.info(f"[worker] Starting pipeline for visit {visit_id}")

    try:
        publish_progress(visit_id,"TRANSCRIBING","Downloading audio...",5)

        import asyncio
        local_audio_path = asyncio.run(download_audio_from_url(audio_url,visit_id))

        def status_cb(status,message,progress):
            scaled = 5 + int(progress * 0.35)
            publish_progress(visit_id,status,message,scaled)

        transcription = run_transcription_pipeline(
            audio_path=local_audio_path,
            model_state=model_state,
            num_speakers=num_speakers,
            specialty=specialty,
            status_callback=status_cb,
        )

        publish_transcription_done(visit_id,transcription.model_dump())
        logger.info(
            f"[worker] Transcription done for {visit_id}: "
            f"{len(transcription.segments)} segments"
        )
