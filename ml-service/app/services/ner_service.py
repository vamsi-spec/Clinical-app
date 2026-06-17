import logging 
import re
from typing import Optional

from app.models.schemas import NEREntity,NEResponse,EnrichedSegment,SpeakerRole
from app.config import settings
from functools import lru_cache

logger = logging.getLogger(__name__)



#model loaders
#called once at start from main.py

def load_ner_models() -> tuple:
    nlp_bc5 = None
    nlp_sci = None

    try:
        import spacy
        import scispacy

        logger.info("Loading en_ner_bc5dr_md...")
        nlp_bc5 = spacy.load("en_ner_bc5cdr_md")
        logger.info("en_ner_bc5cdr_md loaded")
    except Exception as e:
        logger.error(f"Failed to load en_ner_bc5dr_md: {e}")
    
    try:
        import scispacy
        
        
        logger.info("Loading en_core_sci_md...")
        nlp_sci = spacy.load("en_core_sci_md")
        logger.info("en_core_sci_md loaded")

    except Exception as e:
        logger.error(f"Failed to load en_core_sci_md: {e}")

    return nlp_bc5, nlp_sci

def add_negation_detector(nlp_pipeline):
    try:
        from negspacy.termsets import termset
        from negspacy.negation import Negex

        ts = termset("en_clinical")
        nlp_pipeline.add_pipe("negex",config={"neg_termset":ts.get_patterns()},last = True)

        logger.info(f"Negation detector added to {nlp_pipeline.meta['name']}")
        return nlp_pipeline

    except Exception as e:
        logger.warning(f"Could not add negation detector: {e} — "
        "negated entities will not be filtered")
        return nlp_pipeline


def build_confidence_map(segments: list[EnrichedSegment],transcript: str) -> dict[tuple,float]:
    """
    Build map from (start,end) -> confidence score using transcript overlap
    we run NER on the full transcript string,entities come back with character positions.We need to know which transcript segment that character position came from, so we can weight the entity by that segment's confidence.
    """

    confidence_map = {}
    char_offset = 0

    for seg in segments:
        seg_text = seg.text
        seg.start = char_offset
        seg_end = char_offset + len(seg_text)
        confidence_map[(seg.start,seg_end)] = seg.confidence
        char_offset = seg_end + 1

    return confidence_map

def get_entity_confidence(entity_start:int, entity_end:int, confidence_map:dict) -> float:
    for (seg_start, seg_end), confidence in confidence_map.items():
        if seg_start <= entity_start <= seg_end:
            return confidence
    return 1.0
        
# TEXT PREPROCESSING
# NER works better on clean, normalized text
def processing_for_ner(transcript: str) -> str:
    text = re.sub(r'^(DOCTOR|PATIENT|FAMILY|UNKNOWN):\s*', '', transcript, flags=re.MULTILINE)

    text = re.sub(r'\s+',' ',text).strip()

    expansions = {
        r'\bBP\b': 'blood pressure',
        r'\bHR\b': 'heart rate',
        r'\bRR\b': 'respiratory rate',
        r'\bSOB\b': 'shortness of breath',
        r'\bCP\b': 'chest pain',
        r'\bN/V\b': 'nausea vomiting',
        r'\bDOE\b': 'dyspnea on exertion',
        r'\bh/o\b': 'history of',
        r'\bc/o\b': 'complains of',
        r'\bk/c/o\b': 'known case of',
        r'\bDM\b': 'diabetes mellitus',
        r'\bHTN\b': 'hypertension',
        r'\bCAD\b': 'coronary artery disease',
        r'\bCKD\b': 'chronic kidney disease',
    }

    for pattern, expansion in expansions.items():
        text = re.sub(pattern, expansion, text, flags=re.IGNORECASE)

    return text



def deduplicate_entities(entities: list[NEREntity]) -> list[NEREntity]:
    seen_texts = {}
    for entity in entities:
        normalized = entity.text.lower().strip()
        if normalized not in seen_texts:
            seen_texts[normalized] = entity
        else:
            if entity.confidence > seen_texts[normalized].confidence:
                seen_texts[normalized] = entity
    
    return list(seen_texts.values())



#UML semantic type mappings


SYMPTOM_SEMANTIC_TYPES = {
    "T184", 
    "T033",  
    "T034",  
}

DIAGNOSIS_SEMANTIC_TYPES = {
    "T047",  
    "T048",  
    "T191",  
    "T046",  
    "T020",  
    "T037",  
    "T019",  
    "T190",  
}

# Semantic types to completely ignore
# These are entities that are neither symptoms nor diagnoses
IGNORE_SEMANTIC_TYPES = {
    "T121",  
    "T116",  
    "T123",  
    "T109", 
    "T196", 
}


#SCIspacy's entitylinker connects extracted entities to UMLS concept IDs and return official sematic type

def load_entity_linker(nlp_pipeline):
    """
    Add UMLS EntityLinker to a SciSpacy pipeline.
    Called once at startup — linker loads a large
    UMLS index (~1GB) so must not be called per request.

    Args:
        nlp_pipeline: Loaded spaCy pipeline

    Returns:
        Pipeline with EntityLinker added, or original
        pipeline if linker fails to load
    """

    try:
        nlp_pipeline.add_pipe("scispacy_linker",config={
            "resolve_abbrevations": True,
            "linker_name": "umls",
            "threshold": 0.8,
            "k": 10,
            "filter_for_definitions": False
        },
        last=True)
        logger.info("UMLS entity linker added to pipeline")
        return nlp_pipeline
    except Exception as e:
        logger.error(f"Failed to load UMLS entity linker: {e}"
        "Fall back to embeddings")
        return nlp_pipeline

def classify_via_umls(entity_text: str,spacy_entity) -> Optional[str]:
    try:
        if not hasattr(spacy_entity._,'kb_ents'):
            return None
        
        kb_ents = spacy_entity._.kb_ents
        if not kb_ents:
            logger.debug(f"No UMLS entity found for '{entity_text}'")
            return None

        linker = None
        #checking metadata to get tui code
        if hasattr(spacy_entity.doc._,'linker'):
            linker = spacy_entity.doc._.linker
        
        best_cui,best_score = kb_ents[0]

        logger.debug(f"Entity '{entity_text}' -> CUI: {best_cui} (score: {best_score})")

        if linker and hasattr(linker,'kb'):
            entity_data = linker.kb.cui_to_entity.get(best_cui)
            if entity_data:
                semantic_types = set(entity_data.types)

                if semantic_types & IGNORE_SEMANTIC_TYPES:
                    logger.debug(
                        f"Ignoring '{entity_text}' — "
                        f"pharmacologic/chemical type: {semantic_types}"
                    )
                    return "IGNORE"

                # Check symptom types
                if semantic_types & SYMPTOM_SEMANTIC_TYPES:
                    logger.debug(
                        f"UMLS classifies '{entity_text}' as SYMPTOM "
                        f"(types: {semantic_types})"
                    )
                    return "SYMPTOM"

                # Check diagnosis types
                if semantic_types & DIAGNOSIS_SEMANTIC_TYPES:
                    logger.debug(
                        f"UMLS classifies '{entity_text}' as DIAGNOSIS "
                        f"(types: {semantic_types})"
                    )
                    return "DIAGNOSIS"

        logger.debug(
            f"UMLS linked '{entity_text}' (CUI={best_cui}) "
            "but semantic type not in classification maps"
        )
        return None

    except Exception as e:
        logger.warning(f"UMLS classification error for '{entity_text}': {e}")
        return None


#Layer 2 Sementic embedding

SYMPTOM_PROTOTYPES = [
    "The patient complains of pain",
    "The patient reports feeling",
    "The patient has been experiencing",
    "The patient describes discomfort",
    "The patient feels sick",
    "The patient noticed swelling",
    "The patient suffers from",
    "The patient presents with",
    "I have been having",
    "I feel",
    "I noticed",
    "I am experiencing",
    "My symptom is",
    "I complain of",
]

DIAGNOSIS_PROTOTYPES = [
    "The patient has been diagnosed with",
    "The patient is a known case of",
    "The patient has a history of",
    "The assessment shows",
    "The diagnosis is",
    "The patient has chronic",
    "The patient was found to have",
    "Impression:",
    "Assessment:",
    "The clinical picture is consistent with",
    "This is a case of",
    "The patient is suffering from the disease",
    "The medical condition is",
    "The patient carries a diagnosis of",
]

FAMILY_HISTORY_PROTOTYPES = [
    "My mother had",
    "My father had",
    "My family has a history of",
    "My brother was diagnosed with",
    "My sister has",
    "Family history of",
    "His mother had",
    "Her father had",
    "Parents had",
    "Siblings have",
    "Grandmother had",
    "Grandfather had",
]

NEGATION_PROTOTYPES = [
    "The patient denies",
    "No history of",
    "The patient does not have",
    "Ruled out",
    "There is no evidence of",
    "We need to rule out",
    "To exclude",
    "The patient never had",
    "No signs of",
    "Negative for",
]


@lru_cache(maxsize=1)
def get_prototype_embeddings(embedder_model_name: str="all-MiniLM-L6-v2"):
    try:
        from sentence_transformers import SentenceTransformer
        import torch

        embedder = SentenceTransformer(embedder_model_name)
        logger.info(f"Loaded embedder {embedder_model_name}")
        
        symptom_embs = embedder.encode(SYMPTOM_PROTOTYPES,convert_to_tensor=True)

        diagnosis_embs = embedder.encode(DIAGNOSIS_PROTOTYPES,convert_to_tensor=True)

        family_embs = embedder.encode(FAMILY_HISTORY_PROTOTYPES,convert_to_tensor=True)

        negation_embs = embedder.encode(NEGATION_PROTOTYPES,convert_to_tensor=True)

        logger.info(" Prototype embeddings computed and cached")

        return {
            "embedder": embedder,
            "symptom": symptom_embs,
            "diagnosis": diagnosis_embs,
            "family_history": family_embs,
            "negation": negation_embs,
        }

    except Exception as e:
        logger.warning(f"Failed to compute prototype embeddings: {e}")
        return None


def extract_entity_context(entity_text: str,full_transcript: str,entity_start: int,context_window: int=100) -> str:
    """
    Extract the sentence context around an entity.

    Instead of classifying just "diabetes" we classify
    "My mother had diabetes when she was young" —
    the full context tells us this is family history.
    """

    start = max(0, entity_start - context_window)
    end = min(len(full_transcript), entity_start + len(entity_text) + context_window)
    context = full_transcript[start:end]
    

    last_period_before = context.rfind('.', 0, context_window)
    first_period_after = context.find('.', context_window + len(entity_text))

    if last_period_before != -1:
        context = context[last_period_before + 1:]

    if first_period_after != -1:
        context = context[:first_period_after + 1]

    return context.strip()


def classify_via_embeddings(entity_text: str,sentence_context:str,embedder_cache:Optional[dict] = None) -> Optional[str]:
    if embedder_cache is None:
        embedder_cache = get_prototype_embeddings()
    
    if embedder_cache is None:
        return None
    
    try:
        from sentence_transformers import util
        import torch

        embedder = embedder_cache["embedder"]

        context_embedding = embedder.encode(sentence_context,convert_to_tensor=True)

        scores = {}
        for category, prototype_embs in embedder_cache.items():
            if category == "embedder":
                continue
                
            similarities = util.cos_sim(context_embedding,prototype_embs)[0]

            scores[category] = float(similarities.max())

        logger.debug(f"Embedding scores for '{entity_text}': {scores}")

        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]

        MIN_CONFIDENCE = 0.45

        if best_score < MIN_CONFIDENCE:
            logger.debug(f"Embedding confidence too low for '{entity_text}': " f"{best_score:.3f} — falling through to Layer 3")
            return None

        # Check if family history or negation score is high
        # These are special cases that override symptom/diagnosis
        family_score = scores.get("family_history", 0)
        negation_score = scores.get("negation", 0)

        if family_score > 0.6 and family_score > scores.get("symptom", 0):
            logger.info(f"'{entity_text}' classified as FAMILY_HISTORY (score: {family_score:.3f})")
            return "FAMILY_HISTORY"

        if negation_score > 0.6 and negation_score > scores.get("symptom", 0):
            logger.info(
                f"'{entity_text}' classified as NEGATED_CONTEXT "
                f"(score: {negation_score:.3f})"
            )
            return "NEGATED_CONTEXT"

        category_to_label = {
            "symptom": "SYMPTOM",
            "diagnosis": "DIAGNOSIS"
        }

        label = category_to_label.get(best_category)

        if label:
            logger.info(
                f"Embedding classifies '{entity_text}' as {label} "
                f"(score: {best_score:.3f})"
            )
            return label

        return None

    except Exception as e:
        logger.warning(f"Embedding classification error for '{entity_text}': {e}")
        return None



#Layer 3 LLM FEW-SHOT CLASSIFIER 


FEW_SHOT_EXAMPLES = [
    {
        "sentence": "The patient complains of chest pain for three days.",
        "entity": "chest pain",
        "classification": "CURRENT_SYMPTOM",
        "reasoning": "Patient is currently experiencing this — present tense complaint"
    },
    {
        "sentence": "My mother had diabetes when she was young.",
        "entity": "diabetes",
        "classification": "FAMILY_HISTORY",
        "reasoning": "Refers to a family member, not the patient"
    },
    {
        "sentence": "We need to rule out cancer based on these findings.",
        "entity": "cancer",
        "classification": "DIFFERENTIAL",
        "reasoning": "Being considered but not confirmed — rule out language"
    },
    {
        "sentence": "The patient is a known case of hypertension since 2018.",
        "entity": "hypertension",
        "classification": "ESTABLISHED_DIAGNOSIS",
        "reasoning": "Long-standing confirmed diagnosis"
    },
    {
        "sentence": "The patient's rash has completely cleared up after medication.",
        "entity": "rash",
        "classification": "RESOLVED_SYMPTOM",
        "reasoning": "Past symptom that is no longer active"
    },
    {
        "sentence": "The patient denies any history of seizures.",
        "entity": "seizures",
        "classification": "NEGATED",
        "reasoning": "Explicitly denied by patient"
    },
    {
        "sentence": "Patient was diagnosed with Type 2 Diabetes last year.",
        "entity": "Type 2 Diabetes",
        "classification": "ESTABLISHED_DIAGNOSIS",
        "reasoning": "Formal diagnosis in the patient's history"
    },
    {
        "sentence": "She reports feeling nauseated every morning.",
        "entity": "nausea",
        "classification": "CURRENT_SYMPTOM",
        "reasoning": "Active ongoing symptom reported by patient"
    },
]

LLM_TO_INTERNAL_LABEL = {
    "CURRENT_SYMPTOM": "SYMPTOM",
    "ESTABLISHED_DIAGNOSIS": "DIAGNOSIS",
    "DIFFERENTIAL": "DIAGNOSIS",       
    "RESOLVED_SYMPTOM": "IGNORE",      
    "FAMILY_HISTORY": "FAMILY_HISTORY",
    "NEGATED": "NEGATED",
}


def classify_via_llm(entity_text: str,sentence_context: str,speaker_role: Optional[str] = None) -> Optional[str]:
    try:
        import ollama

        examples_str = "\n".join([
            f'Sentence: "{ex["sentence"]}"\n'
            f'Entity: "{ex["entity"]}"\n'
            f'Classification: {ex["classification"]}\n'
            f'Reasoning: {ex["reasoning"]}\n'
            for ex in FEW_SHOT_EXAMPLES
        ])

        speaker_context = ""
        if speaker_role:
            speaker_context = f"\nThe sentence was spoken by: {speaker_role}"
        
        prompt = f"""You are a clinical NLP classifier for a hospital system.

Classify how a medical entity is used in its sentence context.

Classifications:
- CURRENT_SYMPTOM: Patient is currently experiencing this
- ESTABLISHED_DIAGNOSIS: Confirmed medical diagnosis for this patient
- DIFFERENTIAL: Being considered but not yet confirmed (rule out language)
- RESOLVED_SYMPTOM: Was a symptom but is now resolved/improved
- FAMILY_HISTORY: Refers to a family member, not the patient
- NEGATED: Explicitly denied or absent

Examples:
{examples_str}

Now classify this:
Sentence: "{sentence_context}"
Entity: "{entity_text}"{speaker_context}

Return ONLY valid JSON. No markdown. No explanation outside JSON.
Format:
{{"classification": "CURRENT_SYMPTOM", "confidence": 0.95, "reasoning": "one sentence"}}"""

        from app.config import settings

        client = ollama.Client(host=settings.ollama_base_url)
        response = client.generate(model=settings.ollama_model,prompt=prompt,options={"temperature": 0.0},format="json")

        raw = response.get("response","").strip()
        parsed = json.loads(raw)

        classification = parsed.get("classification"," ").upper()
        confidence = float(parsed.get("confidence",0.0))
        reasoning = parsed.get("reasoning","")

        logger.info(
            f"LLM classifies '{entity_text}': "
            f"{classification} (confidence: {confidence:.2f}) — {reasoning}"
        )

        # Reject if LLM is not confident
        if confidence < 0.7:
            logger.debug(
                f"LLM confidence too low ({confidence:.2f}) "
                f"for '{entity_text}' — falling through to Layer 4"
            )
            return None

        return LLM_TO_INTERNAL_LABEL.get(classification)

    except json.JSONDecodeError as e:
        logger.warning(f"LLM returned invalid JSON for '{entity_text}': {e}")
        return None
    except Exception as e:
        logger.warning(f"LLM classification failed for '{entity_text}': {e}")
        return None


# LAYER 4 — RULE-BASED FALLBACK

SYMPTOM_INDICATORS = {
    "pain", "ache", "hurt", "sore", "swelling", "swollen",
    "nausea", "vomiting", "dizziness", "dizzy", "fatigue",
    "tired", "weakness", "weak", "shortness", "breathless",
    "cough", "fever", "chills", "sweating", "rash", "itching",
    "burning", "tingling", "numbness", "bleeding", "discharge",
    "palpitation", "headache", "blurred", "difficulty",
}

DIAGNOSIS_INDICATORS = {
    "disease", "disorder", "syndrome", "failure", "deficiency",
    "insufficiency", "stenosis", "hypertrophy", "carcinoma",
    "diabetes", "hypertension", "infarction", "thrombosis",
    "pneumonia", "infection", "malignancy", "benign",
    "chronic", "acute", "mellitus", "type 2", "type 1",
}


def classify_via_rules(
    entity_text: str,
    speaker_role: Optional[str] = None,
) -> str:
    """
    Rule-based fallback — last resort only.
    Returns "SYMPTOM" or "DIAGNOSIS" — never None.
    Always produces an answer even if it is a guess.
    """
    text_lower = entity_text.lower()

    for indicator in SYMPTOM_INDICATORS:
        if indicator in text_lower:
            return "SYMPTOM"

    for indicator in DIAGNOSIS_INDICATORS:
        if indicator in text_lower:
            return "DIAGNOSIS"

    # Speaker role tiebreaker
    if speaker_role == "PATIENT":
        return "SYMPTOM"
    elif speaker_role == "DOCTOR":
        return "DIAGNOSIS"

    # Absolute last resort
    return "DIAGNOSIS"


def classifty_disease_entity(entity_text: str,spacy_entity=None,sentence_context: str="",speaker_role: Optional[str] = None,full_transcript: str="",entity_start: int = 0,embedder_cache: Optional[dict] = None,use_llm: bool = True) -> str:
    """
    Hybrid 4-layer entity classification.
    Replaces the original keyword-based approach.

    Layer 1: UMLS entity linking (industry standard)
    Layer 2: Semantic embeddings (context-aware)
    Layer 3: LLM few-shot (full understanding)
    Layer 4: Rule-based (last resort fallback)
    """

    import time 
    start_time = time.time()

    if not sentence_context and full_transcript and entity_start:
        sentence_context = extract_entity_context(
            entity_text,
            full_transcript,
            entity_start,
        )

    logger.debug(
        f"\nClassifying: '{entity_text}'\n"
        f"Context: '{sentence_context[:100]}...'\n"
        f"Speaker: {speaker_role}"
    )

    if spacy_entity is not None:
        result = classify_via_umls(entity_text,spacy_entity)
        if result is not None:
            elapsed = round((time.time() - start_time) * 1000,1)
            logger.info(f"UMLS classification for '{entity_text}': {elapsed} ms")
            return result

    if sentence_context:
        result = classify_via_embeddings(entity_text,sentence_context,embedder_cache)
        if result is not None:
            elapsed = round((time.time() - start_time) * 1000,1)
            logger.info(f"Embedding classification for '{entity_text}': {elapsed} ms")
            return result

    if use_llm and sentence_context:
        result = classify_via_llm(
            entity_text,
            sentence_context,
            speaker_role,
        )
        if result is not None:
            elapsed = round((time.time() - start_time) * 1000, 1)
            logger.info(
                f"Layer 3 (LLM) classified '{entity_text}': "
                f"{result} in {elapsed}ms"
            )
            return result

    result = classify_via_rules(entity_text, speaker_role)
    elapsed = round((time.time() - start_time) * 1000, 1)
    logger.info(
        f"Layer 4 (Rules fallback) classified '{entity_text}': "
        f"{result} in {elapsed}ms"
    )
    return result
    

        
        
