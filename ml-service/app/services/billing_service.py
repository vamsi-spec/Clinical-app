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
    
    
    
    
    

