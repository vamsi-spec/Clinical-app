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


def load_prompt(speciality: str) -> str:
    specialty_lower = specialty.lower().strip()

    prompt_file = None
    for key, filename in SPECIALTY_PROMPT_MAP.items():
        if key in specialty_lower or specialty_lower in key:
            prompt_file = filename
            break

    if not prompt_file:
        prompt_file = "soap_default.txt"
        logger.info(f"No specialty specific prompt found for {speciality}, using default.")

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
    

    


    

