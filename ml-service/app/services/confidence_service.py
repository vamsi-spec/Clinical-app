import math
import logging


from app.models.schemas import (
    RawWhisperSegment,
    ScoredSegment,
    WordTimestamp,
    WhisperRawResult
)

from app.config import settings


logger = logging.getLogger(__name__)


def logprob_to_confidence(avg_logprob: float) -> float:
    """ making the values log prob to (0-1 range) """

    try:
        confidence = math.exp(avg_logprob)
        return max(0.0,min(1.0,confidence))

    except (ValueError,OverflowError):
        return 0.0


#Score the segments for each list segments in a transcript

def score_segment(segment: RawWhisperSegment,threshold: Optional[float]=None) -> ScoredSegment:
    
    review_threshold = threshold or settings.confidence_threshold
    #if threshold less than mentioned we have to review it

    confidence = logprob_to_confidence(segment.avg_logprob)

    needs_review = (
        confidence < review_threshold or segment.no_speech_prob > 0.4
    )

    scored_words = []
    for word in segment.words:
        #word confidence is already 0 to 1 from whisper
        scored_words.append(WordTimestamp(
            word=word.word
            start=word.start
            end=word.end
            confidence=round(word.confidence,3)
        ))

    return ScoredSegment(
        id=segment.id,
        start=segment.start,
        end=segment.end,
        text=segment.text,
        avg_logprob=segment.avg_logprob,
        no_speech_prob=segment.no_speech_prob,
        confidence=round(confidence,3),
        needs_review=needs_review,
        words=scored_words,
    )


    
