import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from app.services.billing_service import (
    suggest_billing_codes,
    get_billing_stats,
    fuzzy_match_icd10,
    get_icd10_db_size,
)
from app.models.schemas import NEREntity

logger = logging.getLogger(__name__)
router = APIRouter()


class NEREntitySchema(BaseModel):
    text: str
    label: str
    start: int = 0
    end: int = 0
    negated: bool = False
    confidence: float = 1.0

class BillingRequest(BaseModel):
    visit_id: str = Field(..., description="PostgreSQL Visit ID")
    soap_assessment: str = Field(
        default="",
        description="Assessment section from SOAP note — used for LLM fallback coding"
    )
    diagnosis_entities: list[NEREntitySchema] = Field(
        default=[],
        description="Diagnosis entities from NER service — primary source for ICD-10 matching"
    )
    visit_duration_minutes: int = Field(
        default=20,
        ge=1,
        le=480,
        description="Visit duration for CPT E&M code selection"
    )


class BillingResponseBody(BaseModel):
    visit_id: str
    icd10_codes: list[dict] = []
    cpt_code: dict = {}
    coding_gaps: list[dict] = []
    metadata: dict = {}
    stats: dict = {}


#Model state dependency

def get_model_state():
    from app.main import model_state
    return model_state


@router.post("/suggest",reponse_model = BillingResponseBody,summary="Suggest ICD-10 and CPT billing codes",description="""
Suggests billing codes from SOAP assessment and NER diagnosis entities.

    Three-layer approach:
    1. Fuzzy matching against local ICD-10 database (~70,000 codes, offline)
    2. LLM fallback for complex/ambiguous cases not matched by fuzzy
    3. All LLM suggestions validated against local database (no hallucinated codes)

    Also suggests CPT E&M code based on visit duration and problem count,
    and detects coding gaps — diagnoses with no matching ICD-10 code.
""")

async def suggest_billing(request: BillingRequest,):
    logger.info(f"Billing request: visit_id={request.visit_id}, f"diagnoses={len(request.diagnosis_entities)}, f"duration={request.visit_duration_minutes}min")

    if not request.diagnosis_entities and not request.soap_assessment:
        raise HTTPException(status_code=400,detail="No diagnosis entities or SOAP assessment provided")

    diagnosis_entities = []
    for e in request.diagnosis_entities:
        diagnosis_entities.append(
            NEREntity(
                text=e.text,
                label=e.label,
                start=e.start,
                end=e.end,
                negated=e.negated,
                confidence=e.confidence,
            )
        )

    import asyncio
    loop = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(
            None,
            lambda:suggest_billing_codes(
                soap_assessment=request.soap_assessment,
                diagnosis_entities=diagnosis_entities,
                visit_duration_minutes=request.visit_duration_minutes,
            )
        )
    except Exception as e:
        logger.error(f"Billing suggest error: {e}")
        raise HTTPException(status_code=500,detail=f"Billing suggest failed: {str(e)}")

        raise HTTPException(
            status_code=500,
            detail=f"Billing suggestion failed: {str(e)}"
        )

    stats = get_billing_stats(result)

    logger.info(
        f"Billing complete: visit_id={request.visit_id}, "
        f"codes={len(result['icd10_codes'])}, "
        f"gaps={len(result['coding_gaps'])}, "
        f"cpt={result['cpt_code'].get('code')}"
    )

    return BillingResponseBody(
        visit_id=request.visit_id,
        icd10_codes=result["icd10_codes"],
        cpt_code=result["cpt_code"],
        coding_gaps=result["coding_gaps"],
        metadata=result["metadata"],
        stats=stats,
    )
    

# GET /billing/search
# Direct ICD-10 code search
# Used by doctor UI for manual code lookup
# Bypasses NER — searches directly by text

@router.get("/search",summary="Search ICD-10 codes by description")

async def search_icd10(query: str,threshold: int = 60,limit: int = 5):
    if not query or len(query.strip()) < 2:
        raise HTTPException(status_code=400,detail="Query must be at least 2 characters")

    limit = min(limit,10)

    import asyncio
    loop = asyncio.get_event_loop()

    matches = await loop.run_in_executor(
        None,
        lambda: fuzzy_match_icd10(query.strip(),threshold=threshold,limit = limit)
    )

    return {
        "query": query,
        "threshold": threshold,
        "results": [m.model_dump() for m in matches],
        "count": len(matches)
    }


# GET /billing/health
# Reports billing service status

@router.get("/health")
async def billing_health():
    db_size = get_icd10_db_size()
    return JSONResponse(
        status_code=200 if db_size > 0 else 503,
        content={
            "status": "ready" if db_size > 0 else "degraded",
            "icd10_database": {
                "loaded": db_size > 0,
                "code_count": db_size,
                "note": (
                    "Production: download full CMS ICD-10 dataset (~70,000 codes). "
                    "Current: seed data only."
                    if db_size < 1000
                    else "Full ICD-10 database loaded."
                )
            },
            "cpt_codes": {
                "loaded": True,
                "codes": ["99212", "99213", "99214", "99215"],
                "note": "Simplified E&M model — not full CMS MDM scoring",
            },
        }
    )


    
