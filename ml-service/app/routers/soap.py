import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from app.models.schemas import NERResponse, EnrichedSegment
from app.services.llm_service import run_llm_pipeline
from app.services.ner_service import build_speaker_transcript
from app.config import settings


router = APIRouter()
logger = logging.getLogger(__name__)


#Request schemas
#Pydantic models for incoming requests


class PatientContextSchema(BaseModel):
    age: Optional[int] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    chronic_conditions: list[str] = []
    current_medications: list[str] = []
    allergies: list[str] = []
    last_visit_summary: Optional[str] = None
    longitudinal_trends: list[dict] = []

class SOAPGenerationRequest(BaseModel):
    visit_id: str = Field(..., description="PostgreSQL Visit ID")
    transcript: str = Field(...,description="Plain text transcript")
    segments: list[dict] = Field(default=[],description="Enriched segments from pahse 4 transcription")
    specialty: str = Field(default="general",description="Doctors specialt for prompt selection")
    patient_context: Optional[PatientContextSchema] = Field(default=None,description="Existing patient clinical profile from PostgreSQL")
    ner_results: Optional[dict] = Field(default=None,description="NER results from ner_service — optional, improves output")
    run_inconsistency_check: bool = Field(default=True,description="set false to skip safety check pass")


class SOAPGenerationResponse(BaseModel):
    visit_id: str
    soap: dict
    cds: dict
    inconsistencies: dict
    generation_metadata: dict

def get_model_state():
    from app.main import model_state
    return model_state

# POST /soap/generate
# Main SOAP generation endpoint
# Called by Node backend after transcription

@router.post("/generate",response_model=SOAPGenerationRespons,summary="Generate SOAP note with CDS reasoning",description="""
    Receives an enriched transcript and generates:
    - Structured SOAP note (specialty-aware, chain-of-thought)
    - Clinical Decision Support block (differentials, red flags)
    - Inconsistency and safety check results
    - Metadata about the generation process
    """)

async def generate_soap(request: SOAPGenerationRequest,model_state: dict = Depends(get_model_state)):
    """
    SOAP generation endpoint
    call Ollama endpoint.
    Pass 1 - SOAP + CDS generation with chain-of-thought
    Pass 2 - Inconsistency and safety check
    """

    logger.info(
        f"SOAP generation request: visit_id={request.visit_id}, "
        f"specialty={request.specialty}, "
        f"transcript_length={len(request.transcript)} chars"
    )

    if not request.transcript or len(request.transcript.strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="Transcript too short for SOAP generation. Minimum 20 characters."
        )

    # ── BUILD SPEAKER-FORMATTED TRANSCRIPT ────────────
    # Convert segments to "DOCTOR: ...\nPATIENT: ..." format
    # This is what the LLM uses for clinical reasoning

    speaker_transcript = ""

    if request.segments:
        try:
            from app.models.schemas import EnrichedSegment,SpeakerRole
            enriched_segs = []
            for seg_dict in request.segments:
                role_str = seg_dict.get("role","UNKNOWN")
                try:
                    role = SpeakerRole(role_str)
                except ValueError:
                    role = SpeakerRole.UNKNOWN

                enriched_segs.append(EnrichedSegment(
                    id=seg_dict.get("id",0),
                    start = seg_dict.get("start",0.0),
                    end = seg_dict.get("end",0.0),
                    text = seg_dict.get("text",""),
                    role = role,
                    confidence=seg_dict.get("confidence",1.0)
                    needs_review=seg_dict.get("needs_review",False),
                ))

            speaker_transcript = build_speaker_trancript(enriched_segs)

            except Exception as e:
                logger.warning(f"Could not build speaker transcript from segments: {e}" "Using plain transcript")

                speaker_transcript = request.transcript

        else:
            speaker_transcript = request.transcript

        ner_response = None
        if request.ner_results:
            try:
                from app.models.schemas import NEREntity

                def parse_entities(entity_list: list) -> list[NEREntity]:
                    result = []
                    for e in (entity_list or []):
                        if isinstance(e,dict):
                            result.append(NEREntity(
                                text=e.get("text",""),
                                label = e.get("label","UNNKNOWN"),
                                start = e.get("start",0),
                                end = e.get("end",0),
                                negated=e.get("negated",False)
                                confidence = e.get("confidence",1.0)
                            ))

                    return result
                
                ner_response = NEResponse(visit_id=request.visit_id,visit_id=request.visit_id,
                medications=parse_entities(
                    request.ner_results.get("medications", [])
                ),
                symptoms=parse_entities(
                    request.ner_results.get("symptoms", [])
                ),
                diagnoses=parse_entities(
                    request.ner_results.get("diagnoses", [])
                ),)

            except Exception as e:
            logger.warning(f"Could not parse NER results: {e}")

        patient_context_dict = None
        if request.patient_context:
            patient_context_dict = request.patient_context.model_dump()

        import asyncio
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                None,lambda: run_llm_pipeline(
                    transcript=request.transcript,
                    speaker_formatted_transcript=speaker_transcript,
                    ner_response=ner_response,
                    patient_context=patient_context_dict,
                    specialty=request.specialty,
                    run_inconsistency_check=request.run_inconsistency_check,
                )
            )
        except Exception as e:
        logger.error(
            f"LLM pipeline error for visit {request.visit_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"SOAP generation failed: {str(e)}"
        )

    return SOAPGenerationResponse(
        visit_id=request.visit_id,
        soap=result["soap"],
        cds=result["cds"],
        inconsistencies=result["inconsistencies"],
        generation_metadata=result["generation_metadata"],
    )

# GET /soap/health
# Check LLM availability
        
@router.get("/health")
async def soap_health():
    """
    Check if Ollama is reachable and model is loaded.
    """
    try:
        import ollama
        client = ollama.Client(host=settings.ollama_base_url)

        # List available models
        models_response = client.list()
        available_models = [m["name"] for m in models_response.get("models", [])]
        target_model = settings.ollama_model
        model_available = any(
            target_model in m for m in available_models
        )

        return JSONResponse(
            status_code=200 if model_available else 503,
            content={
                "status": "ready" if model_available else "model_not_loaded",
                "ollama_url": settings.ollama_base_url,
                "target_model": target_model,
                "model_available": model_available,
                "available_models": available_models,
                "note": (
                    "Run: docker-compose exec ollama ollama pull llama3.1:8b"
                    if not model_available else "Ready for SOAP generation"
                ),
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "ollama_unreachable",
                "error": str(e),
                "note": "Ensure Ollama container is running: docker-compose up ollama",
            }
        )

class HashRequest(BaseModel):
    visit_id: str
    soap_note: dict
    finalized_at: str


@router.post("/hash")
async def generate_hash(request: HashRequest):
    """
    Generate SHA-256 audit hash for a finalized SOAP note.
    Called by Node backend when doctor clicks 'Approve and Sign'.
    Hash is stored in SOAPNote.auditHash in PostgreSQL.
    """
    from app.services.llm_service import generate_audit_hash

    if not request.soap_note:
        raise HTTPException(
            status_code=400,
            detail="Cannot hash empty SOAP note"
        )

    audit_hash = generate_audit_hash(
        soap_note=request.soap_note,
        visit_id=request.visit_id,
        finalized_at=request.finalized_at,
    )

    return {
        "visit_id": request.visit_id,
        "audit_hash": audit_hash,
        "algorithm": "SHA-256",
        "finalized_at": request.finalized_at,
    }
            


