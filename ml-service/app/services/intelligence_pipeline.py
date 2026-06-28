import logging 
import time
from typing import Optional


from app.models.schemas import EnrichedSegment,NERResponse,SpeakerRole
from app.services.ner_service import (
    extract_clinical_entities,
    build_speaker_transcript,
    get_ner_stats,
)
from app.services.llm_service import run_llm_pipeline
from app.services.explainability_service import (
    build_explainable_soap,
    generate_audit_hash,
    get_explainability_stats,
)

logger = logging.getLogger(__name__)


# Intelligence pipeline 
# 1. NER extraction (SciSpacy + hybrid classifier)
# 2. LLM Pass 1 (SOAP + CDS)
# 3. LLM Pass 2 (inconsistency check)
# 4. Explainability mapping (sentence → timestamp)

def run_intelligence_pipeline(transcript: str,segments: list[EnrichedSegment],patient_context: Optional[dict],specialty: str,visit_id: str,model_state: dict,run_inconsistency_check: bool = True) -> dict:
    """
    1. Build speaker-formatted transcript from segments
    2. NER extraction with confidence weighting
    3. LLM Pass 1: SOAP + CDS (specialty-aware, chain-of-thought)
    4. LLM Pass 2: Inconsistency + safety check
    5. Explainability: map every SOAP sentence to source timestamp
    6. Assemble final result
    """

    pipeline_start = time.time()
    steps_completed = []
    warnings = []

    result = {
        "ner": {"medications": [], "symptoms": [], "diagnoses": [], "stats": {}},
        "soap": {},
        "cds": {"differentials": [], "red_flags": [], "missed_followups": []},
        "inconsistencies": {},
        "explainable_note": {},
        "generation_metadata": {},
        "pipeline_steps_completed": [],
        "warnings": [],
        "total_duration_seconds": 0,
    }


    #STEP 1: Build speaker-formatted transcript 
    logger.info(f"Intelligence pipeline starting: visit_id={visit_id}, specialty={specialty}")

    speaker_transcript = build_speaker_trancript(segments) if segments else transcript
    if not speaker_transcript:
        speaker_transcript = transcript
        warnings.append("segments missing — using raw transcript")
        logger.warning("segments missing — using raw transcript")

    # STEP 2: NER extraction (SciSpacy + hybrid classifier)
    logger.info("STEP 1: NER extraction")
    nlp_bc5 = model_state.get("nlp_bc5")
    nlp_sci = model_state.get("nlp_sci")
    embedder = model_state.get("embedder")

    ner_response = None
    try:
        if nlp_bc5 or nlp_sci:
            ner_response = extract_clinical_entities(
                transcript=transcript,
                segments=segments,
                nlp_bc5=nlp_bc5,
                nlp_sci=nlp_sci,
                specialty=specialty,
            )

            ner_response.visit_id = visit_id
            ner_stats = get_ner_stats(ner_response)

            result["ner"] = {
                "medications": ner_response.medications,
                "symptoms": ner_response.symptoms,
                "diagnoses": ner_response.diagnoses,
                "stats": ner_stats,
            }

            steps_completed.append("ner_extraction")
            logger.info(f"NER extraction: {ner_stats['total_entities']} entities")
        else:
            warnings.append("NER models unavailable")
            logger.warning("NER models unavailable — skipping NER")

    except Exception as e:
        warnings.append(f"NER extraction failed: {str(e)}")
        logger.error(f"NER extraction failed: {e}", exc_info=True)


    #STEP 2: Build LLM prompts (base SOAP +cds + list_of_diagnoses)
    logger.info("Step 2: LLM SOAP + CDS + inconsistency detection")

    try:
        llm_result = run_llm_pipeline(
            transcript=transcript,
            speaker_formatted_transcript=speaker_transcript,
            ner_response=ner_response,
            patient_context=patient_context,
            specialty=specialty,
            run_inconsistency_check=run_inconsistency_check,
        )
        result["soap"] = llm_result.get("soap",{})
        result["cds"] = llm_result.get("cds",{})
        result["inconsistencies"] = llm_result.get("inconsistencies",{})
        result["generation_metadata"] = llm_result.get("generation_metadata",{})

        llm_passes = llm_result.get("generation_metadata", {}).get("passes_completed", [])
        steps_completed.extend(llm_passes)

        llm_warnings = llm_result.get("generation_metadata", {}).get("warnings", [])
        warnings.extend(llm_warnings)

        logger.info(f"LLM complete: passes={llm_passes}")

    except Exception as e:
        logger.error(f"LLM pipeline failed: {e}")
        warnings.append(f"SOAP generation failed: {str(e)}")
        result["soap"] = {
            "subjective": "[Generation failed]",
            "objective":  "[Generation failed]",
            "assessment": "[Generation failed]",
            "plan":       "[Generation failed]",
        }

    logger.info("Step 3: Building explainable SOAP note")
    try:
        if result["soap"] and segments:
            explainable = build_explainable_soap(
                soap_note = result["soap"],
                segments = segmentsm
                embedder = embedder
            )
            result["explainable_note"] = explainable
            exp_stats = get_explainability_stats(explainable)
            steps_completed.append("explainability_mapping")

            logger.info(
                f"Explainability complete: "
                f"{exp_stats.get('coverage_percent', 0)}% coverage, "
                f"{exp_stats.get('high_conf_percent', 0)}% high confidence"
            )

            if exp_stats.get("coverage_percent", 0) < 50:
                warnings.append(
                    f"Low explainability coverage ({exp_stats.get('coverage_percent', 0)}%) — "
                    "transcript may be too short or too different from SOAP content"
                )
        else:
            warnings.append(
                "Explainability mapping skipped — "
                "no segments or SOAP note unavailable"
            )
    except Exception as e:
        logger.error(f"Explainability mapping failed: {e}")
        warnings.append(f"Explainability mapping failed: {str(e)}")
        result["explainable_note"] = {}

    #final step
    total_elapsed = round(time.time() - pipeline_start, 2)
    result["pipeline_steps_completed"] = steps_completed
    result["warnings"]                 = warnings
    result["total_duration_seconds"]   = total_elapsed

    # Count total safety issues for logging
    total_safety_issues = sum(
        len(v) for v in result["inconsistencies"].values()
        if isinstance(v, list)
    )

    logger.info(
        f"Intelligence pipeline complete: {total_elapsed}s, "
        f"steps={steps_completed}, "
        f"red_flags={len(result['cds'].get('red_flags', []))}, "
        f"safety_issues={total_safety_issues}, "
        f"warnings={len(warnings)}"
    )

    return result





        

    


