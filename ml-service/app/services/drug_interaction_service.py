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

#STEP 2 RXNAV INTERACTION CHECK
# Send list of CUI codes to RxNav
# Returns all known interactions between them
# RxNav checks every pair internally —we don't need to enumerate pairs yourself


async def check_interactions_rxnav(rxcui_list: list[str], client: httpx.AsyncClient) -> list[dict]:
    if len(rxcui_list) < 2:
        return []

    try:
        rxcuis_param = "+".join(rxcui_list)
        resp = await client.get(INTERACTION_URL,params = {"rxcuis": rxcuis_param},timeout=RXNAV_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        #Parse Rxnav response structure
        interactions = []
        groups = data.get("fullInteractionTypeGroup",[]) or []

        for group in groups:
            interaction_types = group.get("fullInteractionType",[]) or []
            for itype in interaction_types:
                pairs = itype.get("interactionPair",[]) or []
                for pair in pairs:
                    concepts = pair.get("interactionConcept",[])
                    if len(concepts) < 2:
                        continue

                    drug1 = (
                        concepts[0]
                        .get("minConceptItem", {})
                        .get("name", "Unknown")
                    )
                    drug2 = (
                        concepts[1]
                        .get("minConceptItem", {})
                        .get("name", "Unknown")
                    )

                    severity_str = pair.get("severity", "")
                    description  = pair.get("description", "")

                    interactions.append({
                        "drug1":       drug1,
                        "drug2":       drug2,
                        "severity":    severity_str,
                        "description": description,
                    })

        logger.info(
            f"RxNav returned {len(interactions)} interactions "
            f"for {len(rxcui_list)} drugs"
        )
        return interactions

    except httpx.TimeoutException:
        logger.warning(
            f"RxNav interaction check timed out after {RXNAV_TIMEOUT}s. "
            "Network issue or RxNav service unavailable."
        )
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"RxNav HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.error(f"RxNav interaction check failed: {e}")
        return []


#STEP 3 Deduplication
# RxNav sometimes returns the same pair twice
# from different data sources (DrugBank, NDF-RT)
# We keep the highest severity occurrence
# and merge descriptions
# A↔B and B↔A are the same interaction

def deduplicate_interactions(interactions: list[DrugInteractionResult]) -> list[DrugInteractionResult]:
    seen: dict[tuple[str,str],DrugInteractionResult] = {}

    severity_rank = {
        Severity.CRITICAL: 4,
        Severity.HIGH:     3,
        Severity.MEDIUM:   2,
        Severity.LOW:      1,
    }

    for interaction in interactions:
        pair_key = tuple(sorted([interaction.drug1.lower(),interaction.drug2.lower()]))

        if pair_key not in seen:
            seen[pair_key] = interaction
        else:
            existing = seen[pair_key]

            if severity_rank.get(interaction.severity, 0) > \
               severity_rank.get(existing.severity, 0):
                seen[pair_key] = interaction

        result = list(seen.values())
        result.sort(
            key=lambda x: severity_rank.get(x.severity, 0),
            reverse=True)

        return result
    

            


        