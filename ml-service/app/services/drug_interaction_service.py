import logging
import time
import re
from typing import Optional
from urllib.parse import quote

import httpx

from app.models.schemas import DrugInteractionResult, Severity

logger = logging.getLogger(__name__)


# RXNAV BASE URLS
# Free API from US National Library of Medicine
# No API key required — open access
# Rate limit: ~20 requests/second (generous)

RXNAV_BASE        = "https://rxnav.nlm.nih.gov/REST"
RXNORM_LOOKUP_URL = f"{RXNAV_BASE}/rxcui.json"
RXNORM_APPROX_URL = f"{RXNAV_BASE}/approximateTerm.json"
INTERACTION_URL   = f"{RXNAV_BASE}/interaction/list.json"


# HTTP timeout for RxNav calls
# RxNav is generally fast (<500ms) but network conditions in a clinic may vary
RXNAV_TIMEOUT = 10.0

SEVERITY_MAP: dict[str, Severity] = {
    "contraindicated":          Severity.CRITICAL,
    "contraindicated drug combination": Severity.CRITICAL,
    "do not use":               Severity.CRITICAL,
    "serious":                  Severity.HIGH,
    "major":                    Severity.HIGH,
    "severe":                   Severity.HIGH,
    "significant":              Severity.HIGH,
    "moderate":                 Severity.MEDIUM,
    "use caution":              Severity.MEDIUM,
    "monitor":                  Severity.MEDIUM,
    "minor":                    Severity.LOW,
    "minimal":                  Severity.LOW,
    "low":                      Severity.LOW,
    "n/a":                      Severity.LOW,
    "":                         Severity.LOW,
}


def map_rxnav_severity(severity_string: str) -> Severity:
    """
    Convert RxNav severity string to internal Severity enum.

    RxNav severity strings are inconsistent across data sources —
    some say "Major", some say "major", some say "Serious".
    Case-insensitive lookup with LOW as safe default.
    """

    if not severity_string:
        return Severity.LOW

    normalized = severity_string.lower().strip()

    if normalized in SEVERITY_MAP:
        return SEVERITY_MAP[normalized]

    for key, severity in SEVERITY_MAP.items():
        if key and key in normalized:
            return severity

    logger.debug(
        f"Unknown RxNav severity string: '{severity_string}' — defaulting to LOW"
    )
    return Severity.LOW

# DRUG NAME NORMALIZER
# Cleans drug names before sending to RxNav
# RxNav lookup is sensitive to formatting:
# "Metformin 500mg" → "Metformin" (strip dosage)
# "ASPIRIN" → "Aspirin" (normalize case)
# "metformin hcl" → "metformin" (strip salt form)

 DOSAGE_PATTERN = re.compile(
    r'\s+\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?|iu|mmol|mEq|%|tab|cap|'
    r'tablet|capsule|patch|cream|gel|solution|injection|spray|drop)s?\b.*$',
    re.IGNORECASE
)

SALT_FORMS = re.compile(
    r'\s+(?:hcl|hydrochloride|sodium|potassium|calcium|maleate|'
    r'fumarate|succinate|tartrate|mesylate|besylate|sulfate|'
    r'phosphate|acetate|citrate)\b.*$',
    re.IGNORECASE
)

ROUTE_PATTERN = re.compile(
    r'\s+(?:oral|iv|topical|sublingual|inhaled|subcutaneous|'
    r'intramuscular|transdermal|ophthalmic|otic|rectal|nasal)\b.*$',
    re.IGNORECASE
)


def normalize_drug_name(drug_text: str) -> str:
    """
    Strip dosage, salt forms, and routes from medication names.

    RxNav lookup works best with generic drug name only.
    Examples:
        "Metformin 500mg twice daily" → "Metformin"
        "atorvastatin calcium 40mg" → "atorvastatin"
        "Lisinopril-HCTZ 10/12.5mg" → "Lisinopril"
        "aspirin 75mg oral" → "aspirin"
    """

    name = drug_text.strip()

    name  = DOSAGE_PATTERN.sub('',name)
    name = SALT_FORMS.sub('',name)
    name = ROUTE_PATTERN.sub('',name)

    name = name.strip(' .,;:-/')

    return name

#STEP 1 RXNORM CUI lookup
#converting the drug name to RxNorm Concept unique ID

# Two strategies:
# A) Exact lookup: GET /rxcui.json?name=Metformin
# B) Approximate: GET /approximateTerm.json?term=Metformin
# A first, B as fallback for misspellings or brand names

async def get_rxcui(drug_name: str,client:httpx.AsyncClient) -> Optional[str]:
    try:
        resp = await client.get(RXNORM_LOOKUP_URL,params={"name":drug_name,"allsrc":"0"},timeout=RXNAV_TIMEOUT)

        resp.raise_for_status()
        data = resp.json()

        # RxNav returns {"idGroup": {"rxnormId": ["860975"]}}
        rxnorm_ids = (data.get("idGroup",{}).get("rxnormId",[]))

        if rxnorm_ids:
            logger.debug(f"Exact CUI lookup: '{drug_name}' → {rxnorm_ids[0]}")
            return rxnorm_ids[0]

    except Exception as e:
        logger.debug(f"Exact CUI lookup failed for '{drug_name}': {e}")

    # Try approximate match for misspellings / brand names
    # Handles brand names: "Glucophage" → finds Metformin CUI
    # Handles partial names: "metfor" → finds Metformin
    try:
        resp = await client.get(RXNORM_APPROX_URL,
        params={
            "term": drug_name,
            "maxEntries": 1,
            "option": "1",
        },timeout=RXNAV_TIMEOUT)

        resp.raise_for_status()
        data = resp.json()

        candidates = (
            data.get("approximateGroup",{}).get("candidate",[])
        )

        if candidates:
            rxcui = candidates[0].get("rxcui")
            if rxcui:
                logger.debug(f"Approximate CUI for '{drug_name}': {rxcui}")
                return rxcui
        
    except Exception as e:
        logger.error(f"Approximate CUI lookup failed for '{drug_name}': {e}")
    
    logger.info(f"No RxNorm CUI found for drug: '{drug_name}'")
    return None


        