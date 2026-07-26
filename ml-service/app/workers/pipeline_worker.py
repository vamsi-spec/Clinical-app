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
        #STEP 1: ASR TRANSCRIPTION 
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

        publish_progress(visit_id,"EXTRACTING_ENTITIES","EXtracting medical entities...",45)
        #STEP 2: NER + SENTENCE SEGMENTATION + SPEAKER SEPARATION
        ner_response = extract_clinical_entities(
            transcript=transcription.full_text,
            segments=transcription.segments,
            nlp_bc5=model_state.get("nlp_bc5")
            nlp_sci=model_state.get("nlp_sci")
            specialty=specialty
        )

        ner_response.visit_id = visit_id

        #STEP 3 SOAP + CDS + Inconsistency
        publish_progress(visit_id,"GENERATING_SOAP","Generating clinical note...",55)

        speaker_transcript = build_speaker_transcript(transcription.segments)

        llm_result = run_llm_pipeline(
            transcript=transcription.full_text,
            speaker_formatted_transcript=speaker_transcript,
            ner_response=ner_response,
            patient_context=patient_context,
            specialty=specialty,
            run_inconsistency_check=True,
        )

        publish_progress(visit_id, "CHECKING_INCONSISTENCIES", "Checking for safety issues...", 70)

        #STEP 4 Explainabilty mapping 
        publish_progress(visit_id,"MAPPING_EXPLAINABILITY","Linking note to audio",78)

        explainable_note = build_explainable_soap(
            soap_note=llm_result["soap"],
            segments=transcription.segments,
            embedder=model_state.get("embedder"),
        )

        #step 5: Billing suggestion
        publish_progress(visit_id, "CHECKING_BILLING", "Suggesting billing codes...", 87)

        billing_result = suggest_billing_codes(soap_assessment=llm_result["soap"].get("assessment",""),
        diagnosis_entities=ner_response.diagnoses,
        visit_duration_minutes=int((transcription.duration or 0) / 60) or 15,
        )

        #Step6: Drug interaction check:
        publish_progress(visit_id,"CHECKING_DRUGS","Checking drug interactions...",93)

        medications_texts = [m.text for m in ner_response.medications if not m.negated]

        drug_result = check_drug_interactions_sync(medication_texts, visit_id=visit_id)
        
        #Firing a dedicated urgent alert if anything critical found 
        if drug_result["metadata"].get("has_high") or drug_result["metadata"].get("has_critical"):
            publish_critical_drug_interaction(visit_id, drug_result["interactions"])

        elapsed = round(time.time() - start_time, 2)


        full_result = {
            "transcription": {
                "full_text": transcription.full_text,
                "segments": [s.model_dump() for s in transcription.segments],
                "detected_language": transcription.detected_language,
                "duration": transcription.duration,
                "speaker_count": transcription.speaker_count,
            },
            "ner": {
                "medications": [m.model_dump() for m in ner_response.medications],
                "symptoms":    [s.model_dump() for s in ner_response.symptoms],
                "diagnoses":   [d.model_dump() for d in ner_response.diagnoses],
            },
            "soap": llm_result["soap"],
            "cds": llm_result["cds"],
            "inconsistencies": llm_result["inconsistencies"],
            "explainable_note": explainable_note,
            "billing": billing_result,
            "drug_interactions": drug_result,
            "generation_metadata": {
                **llm_result["generation_metadata"],
                "total_pipeline_duration_seconds": elapsed,
            },
        }


        publish_pipeline_completed(visit_id,full_result)

        publish_progress(visit_id,"COMPLETED","Clinical note ready.",100)
        logger.info(f"[worker] Pipeline complete for visit {visit_id}: {elapsed}s")

    except Exception as e:
        logger.error(f"[worker] Pipeline FAILED for visit {visit_id}: {e}", exc_info=True)
        publish_pipeline_failed(
            visit_id=visit_id,
            error=str(e),
            failed_step="unknown",  
        )

    finally:
        if local_audio_path:
            cleanup_local_audio(local_audio_path)


