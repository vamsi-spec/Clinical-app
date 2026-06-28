import re
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

from app.models.schemas import EnrichedSegment, SpeakerRole

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Sentence Transformer Loader
# Loaded once at startup — never per request
# ──────────────────────────────────────────────────────────────

def load_sentence_embedder():
    """
    Load sentence transformer model for semantic similarity.
    Used to match SOAP sentences to source audio segments.
    """
    try:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading sentence transformer: all-MiniLM-L6-v2")
        embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Sentence transformer loaded")
        return embedder

    except Exception as e:
        logger.error(f"Failed to load Sentence Transformer: {e}")
        logger.warning(
            "Explainability service will use keyword matching only — "
            "less accurate timestamp mappings"
        )
        return None



# SECTION → SPEAKER PREFERENCE MAP
# Different SOAP sections come from different speakers.
# This is a strong prior for timestamp matching:
#   - Subjective = patient's words
#   - Objective  = doctor's observations
#   - Assessment = doctor's clinical reasoning
#   - Plan       = doctor's instructions
SECTION_SPEAKER_PREFERENCE = {
    "subjective": SpeakerRole.PATIENT,
    "objective":  SpeakerRole.DOCTOR,
    "assessment": SpeakerRole.DOCTOR,
    "plan":       SpeakerRole.DOCTOR,
}

CLINICAL_STOPWORDS = {
    "the", "a", "an", "is", "was", "has", "have", "had",
    "and", "or", "of", "in", "to", "for", "with", "on",
    "at", "by", "from", "as", "be", "been", "being",
    "that", "this", "these", "those", "it", "its",
    "are", "were", "will", "would", "could", "should",
    "patient", "doctor", "reports", "states", "notes",
    "complains", "denies", "history",
}


# ──────────────────────────────────────────────────────────────
# Scoring Configuration
# ──────────────────────────────────────────────────────────────

@dataclass
class ScoringConfig:
    """Configurable weights and thresholds for explainability matching."""

    semantic_weight: float = 0.55
    keyword_weight: float = 0.35
    speaker_weight: float = 0.10
    min_match_threshold: float = 0.25  # reject matches below this score

    def __post_init__(self):
        total = self.semantic_weight + self.keyword_weight + self.speaker_weight
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total:.3f}"
            )


# ──────────────────────────────────────────────────────────────
# Match Result
# ──────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    """Result of matching a SOAP sentence to a transcript segment."""

    soap_sentence: str
    matched_segment: Optional[EnrichedSegment] = None
    score: float = 0.0
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    speaker_bonus: float = 0.0
    is_confident: bool = False  # True if score >= threshold


# ──────────────────────────────────────────────────────────────
# Layer 1: Keyword Overlap Scoring
# ──────────────────────────────────────────────────────────────

def _tokenize(text: str) -> set:
    """Extract meaningful words, removing clinical stopwords."""
    words = set(re.findall(r'\b\w+\b', text.lower()))
    return words - CLINICAL_STOPWORDS


def keyword_overlap_score(soap_sentence: str, segment_text: str) -> float:
    """
    Calculate keyword overlap between SOAP sentence and segment.

    Uses recall-style metric: what fraction of the SOAP sentence's
    meaningful words appear in the segment?

    This works well for specific medical terms: "Metformin 500mg"
    appearing in both SOAP plan and transcript segment.

    Returns float 0.0 to 1.0
    """
    soap_words = _tokenize(soap_sentence)
    seg_words = _tokenize(segment_text)

    if not soap_words:
        return 0.0

    overlap = len(soap_words & seg_words)
    return overlap / len(soap_words)


# ──────────────────────────────────────────────────────────────
# Layer 2: Semantic Similarity Scoring
# ──────────────────────────────────────────────────────────────

def semantic_similarity_score(
    soap_embedding,
    segment_embedding,
) -> float:
    """
    Compute cosine similarity between pre-computed embeddings.

    Both embeddings should already be tensors from the sentence
    transformer. This avoids re-encoding on every call.

    Returns float 0.0 to 1.0
    """
    if soap_embedding is None or segment_embedding is None:
        return 0.0

    try:
        from sentence_transformers import util

        similarity = util.cos_sim(soap_embedding, segment_embedding).item()
        return max(0.0, float(similarity))

    except Exception as e:
        logger.warning(f"Semantic similarity failed: {e}")
        return 0.0


# ──────────────────────────────────────────────────────────────
# Combined Score
# ──────────────────────────────────────────────────────────────

def combined_match_score(
    keyword_score: float,
    semantic_score: float,
    speaker_match_bonus: float,
    config: Optional[ScoringConfig] = None,
) -> float:
    """Weighted combination of all scoring signals."""
    if config is None:
        config = ScoringConfig()

    return (
        config.semantic_weight * semantic_score +
        config.keyword_weight * keyword_score +
        config.speaker_weight * speaker_match_bonus
    )


# ──────────────────────────────────────────────────────────────
# Explainability Service (Class-Based)
# ──────────────────────────────────────────────────────────────

class ExplainabilityService:
    """
    Maps SOAP note sentences back to source transcript segments.

    Workflow:
        1. Pre-compute embeddings for all segments (once)
        2. For each SOAP sentence, encode it once
        3. Score against all segments using keyword + semantic + speaker
        4. Return the best match (or None if below threshold)
    """

    def __init__(self, embedder=None, config: Optional[ScoringConfig] = None):
        self.embedder = embedder
        self.config = config or ScoringConfig()

        # Cache for pre-computed segment embeddings
        self._segment_embeddings = None
        self._segments: list[EnrichedSegment] = []

    def precompute_segment_embeddings(self, segments: list[EnrichedSegment]):
        """
        Batch-encode all transcript segments upfront.
        Call this once before matching SOAP sentences.
        """
        self._segments = segments

        if self.embedder is None:
            logger.info("No embedder available — skipping segment pre-computation")
            self._segment_embeddings = None
            return

        texts = [seg.text for seg in segments]
        if not texts:
            self._segment_embeddings = None
            return

        logger.info(f"Pre-computing embeddings for {len(texts)} segments")
        self._segment_embeddings = self.embedder.encode(
            texts, convert_to_tensor=True, show_progress_bar=False
        )
        logger.info("Segment embeddings ready")

    def _encode_soap_sentence(self, sentence: str):
        """Encode a single SOAP sentence. Returns None if no embedder."""
        if self.embedder is None:
            return None
        try:
            return self.embedder.encode(sentence, convert_to_tensor=True)
        except Exception as e:
            logger.warning(f"Failed to encode SOAP sentence: {e}")
            return None

    def match_sentence(
        self,
        soap_sentence: str,
        section: str,
        segments: Optional[list[EnrichedSegment]] = None,
    ) -> MatchResult:
        """
        Find the best matching transcript segment for a SOAP sentence.

        Args:
            soap_sentence: A single sentence from the SOAP note
            section: Which SOAP section ("subjective", "objective", etc.)
            segments: Override segments (uses pre-computed if not provided)

        Returns:
            MatchResult with the best matching segment and scores
        """
        active_segments = segments or self._segments
        if not active_segments:
            return MatchResult(soap_sentence=soap_sentence)

        # Encode SOAP sentence once for all comparisons
        soap_emb = self._encode_soap_sentence(soap_sentence)

        # Determine preferred speaker for this section
        preferred_speaker = SECTION_SPEAKER_PREFERENCE.get(
            section.lower(), None
        )

        best_result = MatchResult(soap_sentence=soap_sentence)

        for idx, segment in enumerate(active_segments):
            # Layer 1: Keyword overlap
            kw_score = keyword_overlap_score(soap_sentence, segment.text)

            # Layer 2: Semantic similarity
            seg_emb = (
                self._segment_embeddings[idx]
                if self._segment_embeddings is not None
                else None
            )
            sem_score = semantic_similarity_score(soap_emb, seg_emb)

            # Layer 3: Speaker preference bonus
            speaker_bonus = 0.0
            if preferred_speaker and segment.role == preferred_speaker:
                speaker_bonus = 1.0

            # Combined score
            score = combined_match_score(
                keyword_score=kw_score,
                semantic_score=sem_score,
                speaker_match_bonus=speaker_bonus,
                config=self.config,
            )

            if score > best_result.score:
                best_result = MatchResult(
                    soap_sentence=soap_sentence,
                    matched_segment=segment,
                    score=score,
                    keyword_score=kw_score,
                    semantic_score=sem_score,
                    speaker_bonus=speaker_bonus,
                    is_confident=(score >= self.config.min_match_threshold),
                )

        # Reject low-confidence matches
        if best_result.score < self.config.min_match_threshold:
            logger.debug(
                f"No confident match for: '{soap_sentence[:50]}...' "
                f"(best score: {best_result.score:.3f})"
            )
            best_result.matched_segment = None
            best_result.is_confident = False

        return best_result

    def match_all_sentences(
        self,
        soap_sentences: list[str],
        section: str,
        segments: Optional[list[EnrichedSegment]] = None,
    ) -> list[MatchResult]:
        """
        Match multiple SOAP sentences to their source segments.

        Args:
            soap_sentences: List of sentences from a SOAP section
            section: Which SOAP section ("subjective", "objective", etc.)
            segments: Override segments (uses pre-computed if not provided)

        Returns:
            List of MatchResult, one per input sentence
        """
        return [
            self.match_sentence(sentence, section, segments)
            for sentence in soap_sentences
        ]



def split_into_sentences(text: str, min_length: int = 10) -> list[str]:
    """
    Split clinical text into sentences using pySBD.

    pySBD (Python Sentence Boundary Disambiguation) handles:
    - Medical abbreviations (b.i.d., p.r.n., Dr., etc.)
    - Decimal numbers (2.5mg, 130/85)
    - Ellipses, URLs, and other edge cases

    Falls back to basic regex splitting if pySBD is not installed.

    Args:
        text: Clinical text to split
        min_length: Minimum character length for a sentence (filters noise)

    Returns:
        List of sentences
    """
    if not text or not text.strip():
        return []

    try:
        import pysbd

        segmenter = pysbd.Segmenter(language="en", clean=False)
        sentences = [
            s.strip() for s in segmenter.segment(text)
            if len(s.strip()) > min_length
        ]
        return sentences if sentences else [text.strip()]

    except ImportError:
        logger.warning(
            "pySBD not installed — falling back to basic regex splitting. "
            "Install with: pip install pysbd"
        )
        # Fallback: simple split on sentence-ending punctuation + space + capital
        raw = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        sentences = [s.strip() for s in raw if len(s.strip()) > min_length]
        return sentences if sentences else [text.strip()]


# ──────────────────────────────────────────────────────────────
# Standalone Helpers (functional API)
# ──────────────────────────────────────────────────────────────

# Speaker preference weight for standalone function
SPEAKER_PREFERENCE_WEIGHT = 0.10


def _empty_source() -> dict:
    """Return an empty source dict when no segment match is found."""
    return {
        "source_start": None,
        "source_end": None,
        "source_text": None,
        "source_speaker": None,
        "source_role": None,
        "match_confidence": 0.0,
    }


# Batch segment embedder
# Pre-computes embeddings for all segments once, reuse them for every SOAP note.
# Without batching: O(n_sentences × n_segments) encodings
# With batching: O(n_segments) encodings + O(n_sentences) comparisons


def batch_encode_segments(segments: list[EnrichedSegment], embedder) -> Optional[any]:
    """Batch-encode all segment texts into embeddings. Call once per visit."""
    if embedder is None or not segments:
        return None
    try:
        texts = [seg.text for seg in segments]
        logger.info(f"Batch encoding {len(texts)} segments")
        start = time.time()
        embeddings = embedder.encode(texts, convert_to_tensor=True, batch_size=32)
        elapsed = round(time.time() - start, 2)
        logger.info(f"Batch encoding completed in {elapsed}s")
        return embeddings

    except Exception as e:
        logger.warning(f"Batch encoding failed: {e} — falling back to on-the-fly encoding")
        return None


def find_best_segment(
    soap_sentence: str,
    section: str,
    segments: list[EnrichedSegment],
    embedder,
    segment_embeddings,
) -> dict:
    """
    Find the best matching transcript segment for a SOAP sentence.

    Uses all 3 scoring layers: keyword overlap, semantic similarity,
    and speaker preference bonus.

    Args:
        soap_sentence: A single sentence from the SOAP note
        section: SOAP section name ("subjective", "objective", etc.)
        segments: List of enriched transcript segments
        embedder: Sentence transformer model (or None)
        segment_embeddings: Pre-computed embeddings from batch_encode_segments

    Returns:
        Dict with source_start, source_end, source_text, source_speaker,
        source_role, and match_confidence
    """
    if not segments:
        return _empty_source()

    preferred_role = SECTION_SPEAKER_PREFERENCE.get(section, SpeakerRole.UNKNOWN)

    # Encode SOAP sentence once for all comparisons
    soap_emb = None
    if embedder is not None:
        try:
            soap_emb = embedder.encode(soap_sentence, convert_to_tensor=True)
        except Exception as e:
            logger.warning(f"Failed to encode SOAP sentence: {e}")

    best_score = -1.0
    best_segment = None

    for idx, seg in enumerate(segments):
        # Layer 1: keyword overlap
        kw_score = keyword_overlap_score(soap_sentence, seg.text)

        # Layer 2: semantic similarity (using pre-computed embeddings)
        seg_emb = segment_embeddings[idx] if segment_embeddings is not None else None
        sem_score = semantic_similarity_score(soap_emb, seg_emb)

        # Layer 3: speaker preference bonus
        speaker_bonus = SPEAKER_PREFERENCE_WEIGHT if seg.role == preferred_role else 0.0

        score = combined_match_score(kw_score, sem_score, speaker_bonus)

        if score > best_score:
            best_score = score
            best_segment = seg

    if best_segment is None:
        return _empty_source()

    return {
        "source_start": best_segment.start,
        "source_end": best_segment.end,
        "source_text": best_segment.text,
        "source_speaker": best_segment.speaker,
        "source_role": best_segment.role.value,
        "match_confidence": round(best_score, 3),
    }
def _empty_source() -> dict:
    """Return empty source when no match found."""
    return {
        "source_start":    None,
        "source_end":      None,
        "source_text":     None,
        "source_speaker":  None,
        "source_role":     None,
        "match_confidence": 0.0,
    }