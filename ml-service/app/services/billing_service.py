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

