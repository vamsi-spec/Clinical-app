import json
import logging
import time
import os
import re
import hashlib

from pathlib import Path
from typing import Optional

import ollama

from app.models.schemas import (EnrichedSegment,NEResponse,NEREntity,SpeakerRole)
from app.config import settings

logger = logging.getLogger(__name__)


#Promopt Loader
#fall back to default if specialty not found

PROMPT_DIR = Path(__file__).parent.parent/"prompts"

SPECIALTY_PROMPT_MAP = {
    "cardiology":        "soap_cardiology.txt",
    "cardiac":           "soap_cardiology.txt",
    "cardiothoracic":    "soap_cardiology.txt",
    "psychiatry":        "soap_psychiatry.txt",
    "psychology":        "soap_psychiatry.txt",
    "mental health":     "soap_psychiatry.txt",
    "general medicine":  "soap_general.txt",
    "general":           "soap_general.txt",
    "internal medicine": "soap_general.txt",
    "family medicine":   "soap_general.txt",
}


def load_prompt(specialty: str) -> str:
    specialty_lower = specialty.lower().strip()

    prompt_file = None
    for key, filename in SPECIALTY_PROMPT_MAP.items():
        if key in specialty_lower or specialty_lower in key:
            prompt_file = filename
            break

    if not prompt_file:
        prompt_file = "soap_default.txt"
        logger.info(f"No specialty specific prompt found for {specialty}, using default.")

    else:
        logger.info(f"Loading specialty specific prompt: {prompt_file}")


    prompt_path = PROMPT_DIR / prompt_file

    try:
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {prompt_path}")
        return ("You are a clinical documentation AI.Generate a SOAP note from the transcript. Return valid JSON only with soap and cds keys."
        )

#Patient Context Builder
# Injects existing patient clinical profile into the LLM prompt before SOAP generation

def build_patient_context_block(patient_context: Optional[dict],) -> str:
    if not patient_context:
        return ""

    lines = ["PATIENT CLINICAL HISTORY:(from existing medical record)"]

    age = patient_context.get("age")
    gender = patient_context.get("gender")
    if age or gender:
        demo = []
        if age:
            demo.append(f"Age: {age}")
        if gender:
            demo.append(gender)
        lines.append(f"  Demographics: {', '.join(demo)}")

    conditions = patient_context.get("chronic_conditions",[])

    if conditions:
        lines.append(f"Known chronic conditions: {', '.join(conditions)}")

    medications = patient_context.get("current_medications",[])

    if medications:
        lines.append(f"Current Medications on record: {', '.join(medications)}")

    allergies = patient_context.get("allergies",[])
    if allergies:
        lines.append(f"Known allergies: {', '.join(allergies)}")

    

    blood_type = patient_context.get("blood_type")
    if blood_type:
        lines.append(f"Blood type: {blood_type}")

    last_visit = patient_context.get(last_visit_summary)
    if last_visit:
        lines.append(f"Last visit summary: {last_visit}")

    longitudinal = patient_context.get("longitudinal_trends",[])
    if longitudinal:
        lines.append("Recent trends(from visit history)")
        for trend in longitudinal[:5]:
            lines.append(f"    - {trend.get('metric')}:{trend.get('direction', 'stable')} (latest: {trend.get('latest_value')} {trend.get('unit', '')})"
            )

    return "\n".join(lines)



#NER Context builder
def build_ner_context_block(ner_response: Optional[NEResponse]) -> str:
    if not ner_response:
        return ""

    lines = ["EXTRACTED MEDICAL ENTITIES(from NER pipiline)"]

    active_meds = [e for e in ner_response.medications if not e.negated and "UNCERTAIN" not in e.label]

    active_symptoms = [e for e in ner_response.symptoms if not e.negated and "UNCERTAIN" not in e.label and "FAMILY" not in e.label]

    active_diagnoses = [
        e for e in ner_response.diagnoses
        if not e.negated
        and "FAMILY" not in e.label
    ]
    uncertain = [
        e for e in (
            ner_response.medications +
            ner_response.symptoms +
            ner_response.diagnoses
        )
        if "UNCERTAIN" in e.label
    ]
    family_history = [
        e for e in (ner_response.symptoms + ner_response.diagnoses)
        if "FAMILY" in e.label
    ]

    if active_meds:
        med_texts = list(dict.fromkeys(e.text for e in active_meds))
        lines.append(f"  Medications mentioned: {', '.join(med_texts)}")

    if active_symptoms:
        sym_texts = list(dict.fromkeys(e.text for e in active_symptoms))
        lines.append(f"  Symptoms reported: {', '.join(sym_texts)}")

    if active_diagnoses:
        diag_texts = list(dict.fromkeys(e.text for e in active_diagnoses))
        lines.append(f"  Diagnoses mentioned: {', '.join(diag_texts)}")

    if family_history:
        fh_texts = list(dict.fromkeys(e.text for e in family_history))
        lines.append(
            f"  Family history (NOT patient's conditions): {', '.join(fh_texts)}"
        )

    if uncertain:
        unc_texts = list(dict.fromkeys(e.text for e in uncertain))
        lines.append(
            f"  Low-confidence entities (verify carefully): {', '.join(unc_texts)}"
        )

    return "\n".join(lines)


def get_ollama_client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_base_url)


def parse_llm_json(raw_response: str, context: str = "") -> Optional[dict]:
    """
    parse JSON from LLM response.

    Handles common LLM output issues:
    - Markdown code fences
    - Leading/trailing text
    - Trailing commas
    - BOM characters

    """
    if not raw_response:
        logger.warning(f"Empty LLM response for: {context}")
        return None

    text = raw_response.strip().lstrip('\ufeff')

    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
    text = text.strip()

    
    json_start = text.find('{')
    json_end = text.rfind('}')

    if json_start == -1 or json_end == -1:
        logger.warning(f"No JSON object found in LLM response for: {context}")
        logger.debug(f"Raw response: {raw_response[:200]}")
        return None

    text = text[json_start:json_end + 1]

    text = re.sub(r',\s*([\]}])', r'\1', text)

    text = re.sub(r'//[^\n]*', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(
            f"JSON parse failed for {context}: {e}. "
            f"Text preview: {text[:300]}"
        )
        return None

def call_ollama(prompt: str,system_prompt: str = "",max_retries: int = 3,context: str = "")-> str:
    #call ollama with retry logic

    client = get_ollama_client()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content" : system_prompt})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(1,max_retries + 1):
        try:
            logger.info(f"Calling Ollama (attempt {attempt}/{max_retries}) for: {context[:50]}...")
            start = time.time()

            response = client.chat(model=settings.ollama_model,messages=messages,options={"temperature":0.0,"num_predict":4096,"top_p":1.0},format="json")

            elapsed = round(time.time() - start,2)

            content = response["message"]["content"]
            logger.info(f"Ollama response received in {elapsed}s, tokens: {len(content)} chars")

            return content

        except Exception as e:
            logger.warning(f"Ollama attempt {attempt} failed for {context}: {e}")

            if attempt < max_retries:
                wait = 2 ** attempt
                logger.info(f"Waiting {wait}s before retry...")
                time.sleep(wait)

    logger.error(f"All Ollama attempts failed for context: {context[:50]}...")
    return None            



#Pass 1 - SOAP + CDS Generation
# Main chain-of-thought reasoning pass
# Uses specialty-specific prompt
# Injects patient context + NER entities
# Returns SOAP note + CDS block


def generate_soap_and_cds(transcript: str,speaker_formatted_transcript: str,ner_response: Optional[NEResponse],patient_context: Optional[dict],specialty: str = "general") -> Optional[dict]:
    """
    Generate SOAP note and CDS block using chain-of-thought prompting.

    This is the primary LLM call.
    It produces:
    - soap.subjective, soap.objective, soap.assessment, soap.plan
    - cds.differentials (list with diagnosis, likelihood, reasoning)
    - cds.red_flags (list of urgent findings)
    - cds.missed_followups (symptoms not addressed in plan)
    """

    system_prompt = load_prompt(specialty)
    patient_block = build_patient_context_block(patient_context)
    ner_block = build_ner_context_block(ner_response)

    user_prompt = f"""
    STRUCTURED TRANSCRIPT (with speaker labels):
    {speaker_formatted_transcript}
    {patient_block}
    {ner_block}

    REQUIRED OUTPUT FORMAT - return ONLY this JSON structure:
    {{
  "soap": {{
    "subjective": "Complete subjective section...",
    "objective": "Complete objective section...",
    "assessment": "Complete assessment with primary diagnosis and reasoning...",
    "plan": "Complete plan with medications, investigations, referrals, follow-up..."
  }},
  "cds": {{
    "differentials": [
      {{
        "diagnosis": "Primary diagnosis name",
        "likelihood": "high",
        "reasoning": "Evidence supporting this diagnosis from the transcript",
        "against": "What makes this less certain"
      }},
      {{
        "diagnosis": "Alternative diagnosis",
        "likelihood": "medium",
        "reasoning": "Why this is possible",
        "against": "What argues against it"
      }}
    ],
    "red_flags": [
      "Specific urgent finding that needs immediate attention"
    ],
    "missed_followups": [
      "Patient mentioned X but it was not addressed in the plan"
    ]
  }}
}}
"""

    raw = call_ollama(prompt=user_prompt,system_prompt=system_prompt,context="SOAP + CDS generation for speciality "+ specialty)

    if not raw:
        return None

    parsed = parse_llm_json(raw,context = "SOAP + CDS")

    if not parsed:
        return None

    if "soap" not in parsed:
        logger.warning("LLM response missing 'soap' key")
        return None

    soap = parsed.get("soap",{})
    required_soap_keys = ["subjective","objective","assessment","plan"]
    missing = [k for k in required_soap_keys if k not in soap]
    if missing:
        logger.warning(f"Missing SOAP keys: {missing} from speciality {specialty}")
        for k in missing:
            soap[k] = ""

    if "cds" not in parsed:
        logger.warning("LLM response missing 'cds' key - using empty CDS")
        parsed["cds"] = {
            "differentials": [],
            "red_flags": [],
            "missed_followups": []
        }
    return parsed

#PASS 2 - Inconsistency detection
#Now llm fully focus on inconsistencies betwwen transcript + SOAP + CDS

#why seperate from pass 1 
# When SOAP generation and inconsistency checking are in the same prompt, the LLM spends most of its attention on generating the note and superficially checks inconsistencies.

def detect_inconsistencies(soap_note: dict,speaker_formatted_transcript: str,ner_response: Optional[NEResponse],patient_context: Optional[dict]) -> dict:
    """
    Dedicated inconsistency and safety check pass.

    Receives the already-generated SOAP note and
    cross-references it against:
    - Original transcript
    - Patient's known allergies
    - Current medications
    - NER extracted entities
    - What was mentioned vs what was documented
    """
    try:
        inconsistency_prompt_path = PROMPT_DIR/"cds_inconsistency.txt"
        system_prompt = inconsistency_prompt_path.read_text(encoding="utf-8")

    except FileNotFoundError:
        logger.warning("cds_inconsistency.txt not found")
        return {}
        
    patient_block = ""
    if patient_context:
        allergies = patient_context.get("allergies", [])
        medications = patient_context.get("current_medications",[])
        conditions = patient_context.get("chronic_conditions",[])

        if allergies or medications or conditions:
            patient_block = f"""
PATIENT SAFETY PROFILE:
  Known allergies: {', '.join(allergies) if allergies else 'None documented'}
  Current medications on record: {', '.join(medications) if medications else 'None documented'}
  Known conditions: {', '.join(conditions) if conditions else 'None documented'}
"""

    ner_block = build_ner_context_block(ner_response)

    soap_text = json.dumps(soap_note, indent=2)

    user_prompt = f"""
GENERATED SOAP NOTE TO CHECK:
{soap_text}

ORIGINAL TRANSCRIPT:
{speaker_formatted_transcript}

{patient_block}

{ner_block}

CHECK FOR SAFETY ISSUES AND RETURN ONLY THIS JSON:
{{
  "allergy_violations": [
    {{
      "prescribed": "medication name",
      "allergy": "documented allergy",
      "severity": "critical",
      "explanation": "why this is dangerous"
    }}
  ],
  "drug_interactions": [
    {{
      "drug1": "first drug",
      "drug2": "second drug",
      "severity": "high",
      "explanation": "interaction mechanism"
    }}
  ],
  "diagnosis_symptom_mismatch": [
    {{
      "symptom": "mentioned symptom",
      "diagnosis": "stated diagnosis",
      "issue": "why this doesn't match"
    }}
  ],
  "transcript_discrepancies": [
    {{
      "transcript_quote": "what patient said",
      "soap_states": "what soap says",
      "issue": "the contradiction"
    }}
  ],
  "unaddressed_concerns": [
    {{
      "concern": "what patient mentioned",
      "quote": "exact patient words",
      "missing_from": "subjective / assessment / plan"
    }}
  ],
  "dosage_concerns": [
    {{
      "medication": "drug name",
      "prescribed_dose": "what was prescribed",
      "concern": "why this is flagged"
    }}
  ]
}}

Return empty arrays for any category where no issues are found.
"""

    raw = call_ollama(
        prompt=user_prompt,
        system_prompt=system_prompt,
        context="Inconsistency detection"
    )
    if not raw:
        logger.warning("No response from inconsistency check")
        return {}

    parsed = parse_llm_json(raw,context="inconsistency check")
    if not parsed:
        logger.warning("failed to parse . returning empty")
        return {}

    total_issues = sum(len(v) for v in parsed.values() if isinstance(v,list))

    if total_issues > 0:
        logger.warning(
            f"Pass 2 found {total_issues} safety issues: "
            f"{[k for k, v in parsed.items() if isinstance(v, list) and v]}"
        )
    else:
        logger.info("Pass 2 complete — no safety issues found")

    return parsed

# SOAP Note POST-PROCESSING
# Cleans and validates the LLM-generated text
# Removes artifacts, ensures minimum content

def postprocess_soap(soap: dict) -> dict:
    """
    Clean up SOAP note after LLM generation.

    - Remove artifacts like "I cannot ...", "As an AI ..."
    - Strip markdown code blocks
    - Ensure minimum content in each section
    - Return valid JSON
    """
    artifacts = [
        r'^Based on the (?:transcript|conversation|above)[,.]?\s*',
        r'^As an AI(?:\s+language\s+model)?,?\s*',
        r'^From the transcript[,.]?\s*',
        r'^Looking at the (?:transcript|conversation)[,.]?\s*',
        r'^According to the transcript[,.]?\s*',
        r'^The transcript (?:shows|indicates|reveals)[,.]?\s*',
    ]

    cleaned = {}
    for section, content in soap.items():
        if not isinstance(content,str):
            cleaned[section] = ""
            continue

        text = content.strip()

        for pattern in artifacts:
            text = re.sub(pattern,"",text,flags=re.IGNORECASE).strip()

        if len(text) < 10:
            text = f"[{section.capitalize()} section — insufficient information in transcript]"

        cleaned[section] = text

    return cleaned


#Audit HASD Generator
# SHA-256 hash of the finalized SOAP note
# Stored in PostgreSQL alongside the note
# If the note is tampered with later, the hash
# won't match — provides legal immutability
# Called AFTER doctor approves and edits the note
# NOT on the raw LLM output 


def generate_audit_hash(soap_note: dict,visit_id: str,finalized_at: str) -> str:
    canonical = json.dumps(soap_note,sort_keys=True,ensure_ascii=False)
    content = f"{canonical} | {visit_id} | {finalized_at}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def build_note_version(soap_note: dict,edited_by: str,edited_at: str,edit_reason: str=""):
    return {
        "soap": soap_note,
        "edited_by": edited_by,
        "edited_at": edited_at,
        "edit_reason": edit_reason,
        "hash": hashlib.sha256(
            json.dumps(soap_note, sort_keys=True).encode()
        ).hexdigest()[:16],  # short hash for display
    }

# MAIN LLM PIPELINE FUNCTION
# Orchestrates both LLM passes
# Returns complete LLM result for storage

def run_llm_pipeline(transcript: str,speaker_formatted_transcript: str,ner_response: Optional[NEResponse],patient_context:Optional[dict],specialty:str="general",run_inconsistency_check: bool = True) -> dict:
    start_time = time.time()
    results = {
        "soap": {},
        "cds": {
            "differentials": [],
            "red_flags": [],
            "missed_followups": [],
        },
        "inconsistencies": {},
        "generation_metadata": {
            "specialty": specialty,
            "model": settings.ollama_model,
            "passes_completed": [],
            "duration_seconds": 0,
            "warnings": [],
        },
    }

    #PASS 1 SOAP+CDS
    logger.info(f"Starting Pass 1: SOAP + CDS for speciality: {specialty}")
    
    soap_cds_result = generate_soap_and_cds(
        transcript=transcript,
        speaker_formatted_transcript=speaker_formatted_transcript,
        ner_response=ner_response,
        patient_context=patient_context,
        specialty=specialty
    )
    
    if soap_cds_result:
        raw_soap = soap_cds_result.get("soap", {})
        results["soap"] = postprocess_soap(raw_soap)
        results["cds"] = soap_cds_result.get("cds", results["cds"])
        results["generation_metadata"]["passes_completed"].append("soap_cds")
        logger.info("Pass 1 complete — SOAP and CDS generated")
    else:
        logger.error("Pass 1 failed — SOAP note could not be generated")
        results["generation_metadata"]["warnings"].append(
            "SOAP generation failed — LLM unavailable or returned invalid response"
        )
        # Provide empty SOAP rather than crashing
        results["soap"] = {
            "subjective": "[Generation failed — please write manually]",
            "objective": "[Generation failed — please write manually]",
            "assessment": "[Generation failed — please write manually]",
            "plan": "[Generation failed — please write manually]",
        }

    #PASS 2 INCONSISTENCY CHECK
    if run_inconsistency_check and results["soap"].get("assessment"):
        logger.info("Starting Pass 2: Inconsistency Check")
        inconsistencies = detect_inconsistencies(
            soap_note=results["soap"],
            speaker_formatted_transcript=speaker_formatted_transcript,
            ner_response=ner_response,
            patient_context=patient_context
        )

        if inconsistencies:
            results["inconsistencies"] = inconsistencies
            results["generation_metadata"]["passes_completed"].append("inconsistency_check")

            # Merge critical allergy violations into CDS red flags
            # so they appear in the most visible location
            allergy_violations = inconsistencies.get("allergy_violations", [])
            if allergy_violations:
                for violation in allergy_violations:
                    red_flag = (
                        f"ALLERGY VIOLATION: {violation.get('prescribed')} "
                        f"prescribed but patient is allergic to "
                        f"{violation.get('allergy')} — "
                        f"{violation.get('explanation', '')}"
                    )
                    results["cds"]["red_flags"].insert(0, red_flag)
                    logger.warning(f"Allergy violation detected: {red_flag}")
        
            else:
            logger.warning(
                "Pass 2 returned no results — "
                "inconsistency check may have failed"
            )
            results["generation_metadata"]["warnings"].append(
                "Inconsistency check could not complete — "
                "manual safety review recommended"
            )
    else:
        if not run_inconsistency_check:
            logger.info("Pass 2 skipped (run_inconsistency_check=False)")
        else:
            logger.info("Pass 2 skipped — no SOAP assessment to check against")

    elapsed = round(time.time() - start_time, 2)
    results["generation_metadata"]["duration_seconds"] = elapsed

    logger.info(
        f"LLM pipeline complete: {elapsed}s, "
        f"passes={results['generation_metadata']['passes_completed']}, "
        f"red_flags={len(results['cds'].get('red_flags', []))}, "
        f"inconsistencies={sum(len(v) for v in results['inconsistencies'].values() if isinstance(v, list))}"
    )

    return results
        

        
