import csv
import json 
import logging
import time
from pathlib import Path
from typing import Optional


from app.models.schemas import NEREntity,ICD10Suggestion,BillingResponse
from app.config import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
ICD10_CSV_PATH = DATA_DIR / "icd10_codes.csv"


#ICD-10 DATABASE LOADER
# Loaded once at module import — small enough
# (~70,000 rows, ~4MB) to keep entirely in memory


_icd10_db: dict[str,str] = {}
_icd10_descriptions: dict[str,str] = {}


def load_icd10_database() -> tuple[dict,dict]:
    """
    Return: (icd10_db, icd10_descriptions)
    """
    
    codes = {}
    descriptions = {}

    if not ICD10_CSV_PATH.exists():
        logger.error(f"ICD-10 CSV not found at {ICD10_CSV_PATH}""Billing will rely entirely on LLM suggestions with no validation. ""Download the full CMS ICD-10 dataset for production use.")
        return codes,descriptions


    try:
        with open(ICD10_CSV_PATH,newline='',encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('code','').strip()
                description = row.get('description','').strip()
                
                if code and description:
                    codes[code] = description
                    descriptions[description] = code
        
        logger.info(f"ICD-10 DB loaded: {len(codes)} codes")
    except Exception as e:
        logger.error(f"Failed to load ICD-10 CSV: {e}")
        
    return codes,descriptions

#load at import time
_icd10_db, _icd10_descriptions = load_icd10_database()

def get_icd10_db_size() -> int:
    """Return number of ICD-10 codes loaded"""
    return len(_icd10_db)

#Layer 1 Fuzzy Matchinig
def fuzzy_match_icd10(diagnosis_text: str,threshold: int = 70,limit: int = 3) -> list[ICD10Suggestion]:
    """
    Perform fast fuzzy matching against the entire ICD-10 index.
    Returns the top N best matches above the threshold.
    """
    if not _icd10_descriptions:
        return []

    try:
        from rapidfuzz import process,fuzz

        matches = process.extract(
            diagnosis_text.lower(),
            _icd10_descriptions.keys(),
            scorer=fuzz.partial_ratio,
            limit=limit
        ) 

        results = []
        for description, score, _ in matches:
            if score >= threshold:
                code = _icd10_descriptions[description]
                results.append(ICD10Suggestion(
                    code=code,
                    description=_icd10_db.get(code,description),
                    confidence=round(score/100,3),
                    method="fuzzy_match",
                ))

        return results

    except Exception as e:
        logger.error(f"Fuzzy matching failed: {e}")
        return []


# LAYER 2 — LLM CLASSIFICATION
# Fallback for complex or ambiguous diagnoses
# that fuzzy matching cannot confidently resolve

def llm_suggest_icd10(soap_assessment: str,existing_codes: set[str]) -> list[ICD10Suggestion]:
    try:
        import ollama

        prompt = f"""You are a medical billing coder. Given this clinical assessment,
suggest the most appropriate ICD-10-CM codes.

Assessment: {soap_assessment}

Return ONLY valid JSON, no markdown, no explanation:
{{
  "suggestions": [
    {{
      "code": "E11.9",
      "description": "Type 2 diabetes mellitus without complications",
      "reasoning": "Patient has documented T2DM",
      "confidence": "high"
    }}
  ]
}}

Suggest 1-4 codes maximum. Use real, valid ICD-10-CM codes only."""

        client = ollama.Client(host=settings.ollama_base_url)
        response = client.generate(model=settings.ollama_model,prompt=prompt,options={"temperatire":0.0},format="json")

        raw = response.get("response","").strip()

        raw = raw.replace("```json","").replace("```","").strip()

        parsed = json.loads(raw)
        suggestions_raw = parsed.get("suggestions",[])

        confidence_map = {"high": 0.85,"medium":0.65,"low": 0.45}

        validated = []
        for item in suggestions_raw:
            code = item.get("code","").strip().upper()
            #  CRITICAL: validate against local database 
            # LLMs hallucinate plausible but non-existent codes
            # e.g. "E11.72" looks real but doesn't exist
            if code not in _icd10_db:
                logger.warning(f"llm hallucinated invalid ICD-10 code: {code}")
                continue
            
            if code in existing_codes:
                continue

            confidence_str = item.get("confidence","medium").lower()
            confidence = confidence_map.get(confidence_str,0.5)

            validated.append(ICD10Suggestion(
                code=code,
                description=_icd10_db[code],  # use OUR description, not LLM's
                confidence=confidence,
                method="llm",
                reasoning=item.get("reasoning", ""),
            ))

            logger.info(
            f"LLM suggested {len(suggestions_raw)} codes, "
            f"{len(validated)} validated against local database"
        )
        return validated

    except json.JSONDecodeError as e:
        logger.warning(f"LLM ICD-10 response was not valid JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"LLM ICD-10 suggestion failed: {e}")
        return []

# CODING GAP DETECTION
# Identifies diagnoses mentioned in the visit
# (from NER) that have NO matching ICD-10 code
# even at a low confidence threshold

def detect_coding_gaps(diagnosis_entities: list[NEREntity],matched_codes: set[str],matched_diagnosis_texts: set[str]) -> list[dict]:
    gaps = []

    for entity in diagnosis_entities:
        if entity.negated or "FAMILY" in entity.label:
            continue

        text_lower = entity.text.lower()
        if text_lower in matched_diagnosis_texts:
            continue

        matches = fuzzy_match_icd10(entity.text,threshold=85,limit=1)

        if not matches:
            gaps.append({
                "diagnosis": entity.text,
                "warning": (
                    f"No confident ICD-10 code found for '{entity.text}'. "
                    "Manual coding review recommended."
                ),
            })
    return gaps


# CPT E&M CODE SELECTION
# Evaluation & Management codes based on visit
# complexity — this is a SIMPLIFIED model.
# Real 2021+ CMS guidelines use Medical Decision
# Making (MDM) complexity, not just duration/count.
# This is an MVP approximation — flag for refinement
# with full CMS E&M tables in production.


CPT_EM_CODES = {
    "99212": "Office/outpatient visit, established patient, straightforward",
    "99213": "Office/outpatient visit, established patient, low complexity",
    "99214": "Office/outpatient visit, established patient, moderate complexity",
    "99215": "Office/outpatient visit, established patient, high complexity",
}

def suggest_cpt_codes(visit_duration_minutes: int,problems_addressed: int) -> dict:
    if problems_addressed >= 3 or visit_duration_minutes >= 40:
        code = "99215"
        basis = "high complexity — 3+ problems or 40+ min visit"
    elif problems_addressed == 2 or visit_duration_minutes >= 25:
        code = "99214"
        basis = "moderate complexity — 2 problems or 25+ min visit"
    elif visit_duration_minutes >= 15:
        code = "99213"
        basis = "low complexity — single problem, 15+ min visit"
    else:
        code = "99212"
        basis = "straightforward — brief visit"

    return {
        "code": code,
        "description": CPT_EM_CODES[code],
        "basis": basis,
        "note": (
            "Simplified MVP model based on duration and problem count. "
            "Production use requires full CMS Medical Decision Making "
            "complexity scoring for billing compliance."
        ),
    }

def suggest_billing_codes(soap_assessment: str,diagnosis_entities: list[NEREntity],visit_duration_minutes: int) -> dict:
    """
    Full billing code suggestion pipeline.

    Steps:
    1. Fuzzy match each NER diagnosis entity against ICD-10 DB
    2. If fuzzy matching found < 2 confident codes, run LLM fallback
       on the full SOAP assessment for broader context
    3. Validate all LLM suggestions against local database
    4. Detect coding gaps — diagnoses with no matching code
    5. Suggest CPT E&M code based on visit complexity

    Args:
        soap_assessment: SOAP note Assessment section
        diagnosis_entities: Diagnosis entities from NER (Phase 5)
        visit_duration_minutes: Visit duration for CPT selection

    Returns:
        Dict with icd10_codes, cpt_code, coding_gaps
    """

    start_time = time.time()

    all_icd10: list[ICD10Suggestion] = []
    matched_codes: set[str] = set()
    matched_diagnosis_texts: set[str] = set()

    # STEP 1 - fuzzy matching
    logger.info(f"Starting ICD-10 fuzzy matching for {len(diagnosis_entities)} entities...")
    active_diagnoses = [
        e for e in active_diagnoses if not e.negated and "FAMILY" not in e.label
    ]

    for entity in active_diagnoses:
        matches = fuzzy_match_icd10(entity.text)
        for match in matches:
            if match.code not in matched_codes:
                all_icd10.append(match)
                matched_codes.add(match.code)
                matched_diagnosis_texts.add(entity.text.lower())
                
    logger.info(f"Fuzzy matching completed: {len(all_icd10)} codes found")

    #STEP 2: LLM fallback if coverage is thin

    needs_llm_fallback = (len(all_icd10) < max(1,len(active_diagnoses) // 2)) and soap_assessment and len(soap_assessment.strip()) > 20

    if needs_llm_fallback:
        logger.info("Coverage thin (<50% diagnoses matched), running LLM fallback")
        llm_suggestions = llm_suggest_icd10(soap_assessment,matched_codes)
        for suggestion in llm_suggestions:
            all_icd10.append(suggestion)
            matched_codes.add(suggestion.code)
    #STEP 3: Sort by confidence , highest
    all_icd10.sort(key=lambda s: s.confidence,reverse=True)

    all_icd10 = all_icd10[:8]

    #STEP 4: coding gap detection
    coding_gaps = detect_coding_gaps(active_diagnoses,matched_codes,matched_diagnosis_texts)

    #STEP 5: CPT
    cpt_code = suggest_cpt_code(
        visit_duration_minutes=visit_duration_minutes,
        problems_addressed=len(active_diagnoses),
    )

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        f"Billing suggestion complete: {elapsed}s, "
        f"{len(all_icd10)} ICD-10 codes, "
        f"{len(coding_gaps)} gaps, "
        f"CPT={cpt_code['code']}"
    )

    return {
        "icd10_codes": [s.model_dump() for s in all_icd10],
        "cpt_code": cpt_code,
        "coding_gaps": coding_gaps,
        "metadata": {
            "duration_seconds": elapsed,
            "fuzzy_match_count": sum(
                1 for s in all_icd10 if s.method == "fuzzy_match"
            ),
            "llm_suggested_count": sum(
                1 for s in all_icd10 if s.method == "llm"
            ),
            "icd10_database_size": len(_icd10_db),
        },
    }


def get_billing_stats(result: dict) -> dict:
    return {
        "total_codes_suggested": len(result.get("icd10_codes", [])),
        "coding_gaps_count": len(result.get("coding_gaps", [])),
        "cpt_code": result.get("cpt_code", {}).get("code"),
        "has_gaps": len(result.get("coding_gaps", [])) > 0,
    }


    
    

