import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


from app.services.drug_interaction_service import (
    check_drug_interactions,
    check_drug_interactions_sync,
    normalize_drug_name,
)


logger = logging.getLogger(__name__)
router = APIRouter()


class DrugInteractionRequest(BaseModel):
    visit_id: str = Field(...,description="PostgreSQL Visit ID")
    medications: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Medication names extracted from NER (preferred) "
            "Dosage is stripped automatically — "
            "pass full NER text e.g. 'Metformin 500mg twice daily'"
        )
    )

class DrugInteractionResponseBody(BaseModel):
    visit_id: str
    interactions: list[dict] = []
    drugs_checked: list[str] = []
    drugs_not_found: list[str] = []
    source: str = ""
    metadata: dict = {}


# POST /drugs/check
# Main drug interaction endpoint
# Called by Node backend after NER completes
# Async — uses RxNav API over HTTP

@router.post("/check",response_model=DrugInteractionResponseBody,summary="check drug interactions via RxNav",
description="""
Checks all medication pairs for known interactions using the
    RxNav API from the US National Library of Medicine.

    Pipeline:
    1. Normalize drug names (strip dosage, salt forms, routes)
    2. Look up RxNorm CUI codes for each drug (in parallel)
    3. Send all CUIs to RxNav interaction API in one request
    4. Map severity to CRITICAL/HIGH/MEDIUM/LOW
    5. Deduplicate (A+B == B+A, keep highest severity)
    6. Always also checks local curated high-risk pairs as safety net

    Falls back to local known-pairs check if RxNav is unavailable.
    """)

async def check_interactions(request:DrugInteractionRequest):
    logger.info(f"Drug interaction request: visit_id={request.visit_id}, "
        f"medications={request.medications}")

    if len(request.medications) < 2:
        return DrugInteractionResponseBody(
            visit_id=request.visit_id,
            interactions=[],
            drugs_checked=[normalize_drug_name(m) for m in request.medications],
            drugs_not_found=[],
            source="skipped",
            metadata={
                "reason": "Only one medication provided — no interactions possible",
                "total_interactions": 0,
                "has_critical": False,
                "has_high": False,
            },
        )

    try:
        result = await check_drug_interactions(medication_names=request.medications,visit_id=request.visit_id)

    except Exception as e:
        logger.error(
            f"Drug interaction check failed for visit {request.visit_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Drug interaction check failed: {str(e)}"
        )

    critical_count = result["metadata"].get("severity_counts",{}).get("critical",0)
    high_count = result["metadata"].get("severity_counts",{}).get("high",0)

    if critical_count > 0:
        logger.warning(
            f"CRITICAL drug interactions for visit {request.visit_id}: "
            f"{critical_count} interactions found"
        )
    elif high_count > 0:
        logger.warning(
            f"HIGH drug interactions for visit {request.visit_id}: "
            f"{high_count} interactions found"
        )
    
    else:
        logger.info(f"Drug check complete: visit_id={request.visit_id}, "
        f"interactions={len(result['interactions'])}")
    
    return DrugInteractionResponseBody(
        visit_id=request.visit_id,
        interactions=result["interactions"],
        drugs_checked=result["drugs_checked"],
        drugs_not_found=result["drugs_not_found"],
        source=result["source"],
        metadata=result["metadata"],
    )


# POST /drugs/normalize
# Utility endpoint — shows how drug names
# will be normalized before RxNav lookup
# Useful for debugging and doctor UI preview

@router.post("/normalize",summary="Preview drug name normalization",description="Shows how medication names will be normalized before RxNav lookup")
async def normalize_drugs(medications: list[str]):
    """
    Example:
        Input:  ["Metformin 500mg twice daily", "atorvastatin calcium 40mg"]
        Output: ["Metformin", "atorvastatin"]
    """

    if not medications:
        raise HTTPException(status_code=400,detail="Provide at least one medication name")

    return {
        "normalizations": [
            {
                "original": med,
                "normalized": normalize_drug_name(med)
            }
            for med in medications
        ]
    }

# GET /drugs/health
# Checks RxNav API reachability

@router.get("/health")
async def drug_interaction_health():
    """
    Check RxNav API availability.
    Returns 200 if reachable, 503 if not.
    Service degrades gracefully to local fallback when RxNav is down.
    """

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://rxnav.nlm.nih.gov/REST/version.json",timeout=5.0,)
            resp.raise_for_status()
            data = resp.json()
            rxnav_version = data.get("version","unknown")

        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "rxnav": {
                    "reachable": True,
                    "version": rxnav_version,
                    "base_url": "https://rxnav.nlm.nih.gov/REST",
                    "note": "Free API from US National Library of Medicine — no key required",
                },
                "local_fallback": {
                    "available": True,
                    "pairs_covered": 5,
                    "note": "MAOI+SSRI, Warfarin+NSAID, Metformin+Contrast, Statin+Fibrate, ACE+K-sparing",
                },
            }
        )

        except Exception as e:
            logger.warning(f"RxNav health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "rxnav": {
                    "reachable": False,
                    "error": str(e),
                    "note": "RxNav unreachable — will use local fallback only",
                },
                "local_fallback": {
                    "available": True,
                    "note": "5 high-risk pairs checked locally without RxNav",
                },
            }
        )
    

