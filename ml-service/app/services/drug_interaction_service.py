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


# KNOWN HIGH-RISK PAIRS — LOCAL FALLBACK
# When RxNav is unavailable (offline clinic,
# network issues), check against a curated list
# of the most dangerous drug combinations
# This is NOT comprehensive — it is a safety net
# for the most common life-threatening interactions

KNOWN_CRITICAL_PAIRS: list[dict] = [
    {
        "drugs": {"maoi", "ssri", "sertraline", "fluoxetine",
                  "paroxetine", "citalopram", "escitalopram",
                  "phenelzine", "tranylcypromine", "selegiline"},
        "match_any_pair": True,
        "severity": Severity.CRITICAL,
        "description": (
            "MAOIs combined with SSRIs risk severe serotonin syndrome — "
            "potentially fatal. Absolute contraindication."
        ),
    },
    {
        "drugs": {"warfarin", "aspirin", "ibuprofen", "naproxen",
                  "diclofenac", "nsaid"},
        "match_any_pair": True,
        "severity": Severity.HIGH,
        "description": (
            "Warfarin combined with NSAIDs significantly increases "
            "bleeding risk. Monitor INR closely or avoid combination."
        ),
    },
    {
        "drugs": {"metformin", "contrast", "iodinated contrast",
                  "iv contrast"},
        "match_any_pair": True,
        "severity": Severity.HIGH,
        "description": (
            "Metformin with iodinated contrast media risks lactic acidosis. "
            "Hold metformin 48 hours before and after contrast administration."
        ),
    },
    {
        "drugs": {"atorvastatin", "simvastatin", "lovastatin",
                  "gemfibrozil", "fenofibrate"},
        "match_any_pair": True,
        "severity": Severity.HIGH,
        "description": (
            "Statin combined with fibrate increases risk of myopathy and "
            "rhabdomyolysis. Use lowest statin dose or avoid combination."
        ),
    },
    {
        "drugs": {"ace inhibitor", "lisinopril", "enalapril", "ramipril",
                  "potassium", "spironolactone", "eplerenone"},
        "match_any_pair": True,
        "severity": Severity.HIGH,
        "description": (
            "ACE inhibitor combined with potassium-sparing diuretic "
            "or potassium supplement risks severe hyperkalemia."
        ),
    },
]


def check_known_pairs_fallback(
    drug_names: list[str],
) -> list[DrugInteractionResult]:
    """
    Check medications against curated high-risk pairs.

    Used when RxNav is unavailable. Not comprehensive —
    only covers the most dangerous common combinations.

    Args:
        drug_names: List of normalized drug names

    Returns:
        List of interactions found in curated pairs
    """
    drug_names_lower = {name.lower() for name in drug_names}
    interactions = []

    for pair_config in KNOWN_CRITICAL_PAIRS:
        known_drugs = pair_config["drugs"]
+        matching = drug_names_lower & known_drugs

        if len(matching) >= 2:
            matching_list = sorted(matching)
            interactions.append(DrugInteractionResult(
                drug1=matching_list[0],
                drug2=matching_list[1],
                severity=pair_config["severity"],
                description=pair_config["description"],
                source="local_fallback",
            ))

    return interactions




            
# MAIN DRUG INTERACTION FUNCTION
# Full async pipeline:
# 1. Normalize drug names
# 2. Look up RxNorm CUI for each drug (parallel)
# 3. Send all CUIs to RxNav interaction API
# 4. Parse and map severity
# 5. Deduplicate results
# 6. Fall back to known pairs if RxNav fails

async def check_drug_interactions(medication_names: list[str],visit_id: str = "")-> dict:
    """
    Args:
        medication_names: List of medication name strings from NER
                         (may include dosage — normalized internally)
        visit_id: PostgreSQL Visit ID for logging
    """

    start_time = time.time()

    if not medication_names:
        return _empty_interaction_result("No medication provided")

    if len(medication_names) < 2:
        return _empty_interaction_result("Only one medication - no interaction possible")

    #STEP 1: Normalize drug names
    normalized_names = []

    name_map: dict[str,str] = {}

    for original in medication_names:
        normalized = normalize_drug_name(original)
        if normalized and normalized not in name_map:
            name_map[normalized] = original
            normalized_names.append(normalized)

    logger.info(
        f"Drug interaction check: visit_id={visit_id}, "
        f"{len(normalized_names)} drugs after normalization: "
        f"{normalized_names}"
    )

    # STEP 2: Look up RxNorm CUIs in parallel
    rxcui_map: dict[str,str] = {}
    not_found: list[str] = []

    try:
        async with httpx.AsyncClient() as client:
            import asyncio

            tasks = {
                drug: get_rxcui(drug,client)
                for drug in normalized_names
            }

            results = await asyncio.gather(
                *tasks.values(),return_exceptions=True
            )

            for drug,result in zip(tasks.keys(),results):
                if isinstance(result, Exception):
                    logger.warning(f"CUI lookup exception for '{drug}': {result}")
                    not_found.append(drug)
                elif result:
                    rxcui_map[drug] = result
                else:
                    not_found.append(drug)
                    logger.info(f"No CUI found for drug: '{drug}'")

            logger.info(
                f"CUI lookup: {len(rxcui_map)} found, "
                f"{len(not_found)} not found: {not_found}"
            )

            # STEP 3: RxNav interaction check
            raw_interactions = []
            rxnav_available = False

            if len(rxcui_map) >= 2:
                rxcui_list = list(rxcui_map.values())
                raw_interactions = await check_interactions_rxnav(rxcui_list,client)

                rxnav_available = True
            
        except Exception as e:
        logger.warning(
            f"RxNav unavailable: {e}. "
            "Falling back to local known-pairs check."
        )
        rxnav_available = False
        raw_interactions = []

    #STEP 4: Parse + map severity

    parsed_interactions: list[DrugInteractionResult] = []

    if rxnav_available and raw_interactions:
        for raw in raw_interactions:
            parsed_interactions.append(DrugInteractionResult(
                drug1=raw["drug1"],
                drug2=raw["drug2"],
                severity=map_rxnav_severity(raw["severity"]),
                description=raw["description"],
                source="rxnav",
            ))

        
    #   STEP 5: Local fallback
    # Always run local fallback — adds known critical pairs
    # that RxNav may have missed due to data source gaps
    local_interactions = check_known_pairs_fallback(normalized_names)

    # Merge local with RxNav — prefer RxNav for same pair
    local_pair_keys = {
        tuple(sorted([i.drug1.lower(), i.drug2.lower()]))
        for i in parsed_interactions
    }
    for local in local_interactions:
        pair_key = tuple(sorted([local.drug1.lower(), local.drug2.lower()]))
        if pair_key not in local_pair_keys:
            parsed_interactions.append(local)

    # STEP 6: Deduplicate + sort
    final_interactions = deduplicate_interactions(parsed_interactions)

    elapsed = round(time.time() - start_time, 3)

    # Build severity counts for metadata
    severity_counts = {
        "critical": sum(1 for i in final_interactions if i.severity == Severity.CRITICAL),
        "high":     sum(1 for i in final_interactions if i.severity == Severity.HIGH),
        "medium":   sum(1 for i in final_interactions if i.severity == Severity.MEDIUM),
        "low":      sum(1 for i in final_interactions if i.severity == Severity.LOW),
    }

    logger.info(
        f"Drug interaction check complete: {elapsed}s, "
        f"{len(final_interactions)} interactions found, "
        f"severity breakdown: {severity_counts}"
    )

    return {
        "interactions":    [i.model_dump() for i in final_interactions],
        "drugs_checked":   normalized_names,
        "drugs_not_found": not_found,
        "source":          "rxnav" if rxnav_available else "local_fallback",
        "metadata": {
            "duration_seconds":   elapsed,
            "rxnav_available":    rxnav_available,
            "total_interactions": len(final_interactions),
            "severity_counts":    severity_counts,
            "has_critical":       severity_counts["critical"] > 0,
            "has_high":           severity_counts["critical"] + severity_counts["high"] > 0,
        },
    }


def _empty_interaction_result(reason: str) -> dict:
    """Return empty result with reason."""
    return {
        "interactions":    [],
        "drugs_checked":   [],
        "drugs_not_found": [],
        "source":          "skipped",
        "metadata": {
            "duration_seconds":   0,
            "rxnav_available":    False,
            "total_interactions": 0,
            "severity_counts":    {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "has_critical":       False,
            "has_high":           False,
            "reason":             reason,
        },
    }

# SYNC WRAPPER
# intelligence_pipeline.py runs in a thread executor
# which cannot directly call async functions
# This wrapper allows sync callers to use the async interaction checker

def check_drug_interactions_sync(medication_names: list[str],visit_id
: str = " ") -> dict:
    """
    Synchronous wrapper for check_drug_interactions().

    Used by intelligence_pipeline.py which runs in a
    ThreadPoolExecutor and cannot await directly.
    Creates a new event loop for the async call.
    """

    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            check_drug_interactions(medication_names,visit_id)
        )

        return result
    finally:
        loop.close()




        