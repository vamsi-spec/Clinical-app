import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional

from app.models.schemas import NERResponse, EnrichedSegment, SpeakerRole
from app.services.ner_service import (
    extract_clinical_entities,
    build_speaker_transcript,
    get_ner_stats,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

class NERRequest(BaseModel):
    visit_id: str = Field(...,description="PostgreSQL Visit ID")
    transcript: str = Field(...,description="Plain text transcript")
    segments: list[dict] = Field(default=[],description="Enriched segments for confidence weighting")
    specialty: str = Field(default="general",description="Doctor's specialty for prompt selection")


class NERResponseBody(BaseModel):
    visit_id: str
    medications: list[dict] = []
    symptoms: list[dict] = []
    diagnoses: list[dict] = []
    stats: dict = {}

def get_model_state():
    from app.main import model_state
    return model_state


# POST /ner/extract
# Main NER endpoint

@router.post("/extract",response_model=NERResponseBody,summary="Extract clinical entities from transcript",description="""
Extracts medical entities from a clinical transcript using:
    - en_ner_bc5cdr_md for drugs (CHEMICAL) and diseases (DISEASE)
    - en_core_sci_md for broader biomedical entities
    - negspacy for negation detection
    - 4-layer hybrid classifier for symptom vs diagnosis disambiguation
    - Confidence weighting from Phase 4 transcript segments
""")


async def extract_entities(request: NERRequest,model_state: dict = Depends(get_model_state)):
    logger.info(
        f"NER request: visit_id={request.visit_id}, "
        f"transcript_length={len(request.transcript)} chars, "
        f"segments={len(request.segments)}"
    )

    if not request.transcript or len(request.transcript.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Transcript too short for NER. Minimum 10 characters required."
        )

    nlp_bc5 = model_state.get("nlp_bc5")
    nlp_sci = model_state.get("nlp_sci")
    embedder = model_state.get("embedder")

    if nlp_bc5 is None and nlp_sci is None:
        raise HTTPException(
            status_code=503,
            detail=("NER models not loaded. Please check service status."
            "Check GET/ner/health for model status")
        )

    enriched_segments = []
    if request.segments:
        for seg_dict in request.segments:
            try:
                role_str = seg_dict.get("role","UNKNOWN")
                try:
                    role = SpeakerRole(role_str)
                except ValueError:
                    role = SpeakerRole.UNKNOWN
                
                enriched_segments.append(EnrichedSegment(
                    id=seg_dict.get("id", 0),
                    start=seg_dict.get("start", 0.0),
                    end=seg_dict.get("end", 0.0),
                    text=seg_dict.get("text", ""),
                    speaker=seg_dict.get("speaker", "UNKNOWN"),
                    role=role,
                    confidence=seg_dict.get("confidence", 1.0),
                    needs_review=seg_dict.get("needs_review", False),
                ))

            except Exception as e:
                logger.warning(f"Skipping malformed segment: {e}")
                continue

    import asyncio
    loop = asyncio.get_event_loop()

    try:
        ner_result = await loop.run_in_executor(
            None,
            lambda: extract_clinical_entities(
                transcript=request.transcript,
                segments=enriched_segments,
                nlp_bc5=nlp_bc5,
                nlp_sci=nlp_sci,
                speciality=request.specialty,
                
            )
        )
    except Exception as e:
        logger.error(
            f"NER extraction error for visit {request.visit_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"NER extraction failed: {str(e)}"
        )

    ner_result.visit_id = request.visit_id
    stats = get_ner_stats(ner_result)

    logger.info(
        f"NER complete: visit_id={request.visit_id}, "
        f"medications={len(ner_result.medications)}, "
        f"symptoms={len(ner_result.symptoms)}, "
        f"diagnoses={len(ner_result.diagnoses)}"
    )

    return NERResponseBody(
        visit_id=request.visit_id,
        medications=[e.model_dump() for e in ner_result.medications],
        symptoms=[e.model_dump() for e in ner_result.symptoms],
        diagnoses=[e.model_dump() for e in ner_result.diagnoses],
        stats=stats,
    )
        
@router.get("/health")
async def ner_health(model_state: dict = Depends(get_model_state)):
    bc5_loaded  = model_state.get("nlp_bc5")  is not None
    sci_loaded  = model_state.get("nlp_sci")  is not None
    emb_loaded  = model_state.get("embedder") is not None

    return {
        "status": "ready" if (bc5_loaded or sci_loaded) else "unavailable",
        "models": {
            "en_ner_bc5cdr_md": {
                "loaded": bc5_loaded,
                "purpose": "Drugs (CHEMICAL) + Diseases (DISEASE) — primary NER model",
            },
            "en_core_sci_md": {
                "loaded": sci_loaded,
                "purpose": "Broad biomedical entities — catch-all secondary model",
            },
            "sentence_embedder": {
                "loaded": emb_loaded,
                "purpose": "4-layer classifier Layer 2 + explainability semantic matching",
            },
        },
    }

