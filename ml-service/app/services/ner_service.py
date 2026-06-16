import logging 
import re
from typing import Optional

from app.models.schemas import NEREntity,NEResponse,EnrichedSegment,SpeakerRole
from app.config import settings

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
        
    
