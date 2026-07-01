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




