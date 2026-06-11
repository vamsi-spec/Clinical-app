from pydantic import BaseModel, Field, validator
from typing import Optional
from enum import Enum

class PipelineStatus(str, Enum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    CONFIDENCE_SCORING = "confidence_scoring"
    CORRECTING = "correcting"
    DIARIZING = "diarizing"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


class SpeakerRole(str, Enum):
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"
    FAMILY = "FAMILY"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"



#WordTimestamp
#used for each word -> start , end time for next transcaribing audio
#when we touch that word , we directly go to that audio clip

class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    confidence: float = Field(
        ge = 0.0,
        le = 1.0,
        default = 1.0
    )

#Rawwhisper output 
#nothing is processed just whisper output
class RawWhisperSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    words: list[WordTimestamp] = []

#confidence scoring segment
#it gives  rawwhisper + confidence output for that

class ScoredSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    confidence: float = Field(ge=0.0,le=1.0)
    needs_review: bool
    words: list[WordTimestamp] = []

    @validator("confidence")
    def round_confidence(cls,v):
        return round(v,3)


#Diarization segment
#it says speaker time line -> spearker1(0 to 5sec) speaker2(6 to 10 sec)

class DiarizationSegment(BaseModel):
    speaker: str
    start: float
    end: float

#Enriched Segment
#this is final output after the all pipeline steps

class EnrichedSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    speaker: str = "UNKNOWN"
    role: SpeakerRole = SpeakerRole.UNKNOWN
    confidence: float = Field(ge=0.0,le=1.0)
    needs_review: bool = False
    corrected: bool = False
    original_text: Optional[str] = None
    words: list[WordTimestamp] = []


class WhisperRawResult(BaseModel):
    segments: list[RawWhisperSegment]
    full_text: str
    detected_language: str
    duration: float


#Transcription response 
#final Response by ml-service 

class TranscriptionResponse(BaseModel):
    full_text: str
    segments: list[EnrichedSegment]
    detected_language: str
    duration: float
    speaker_count: int
    low_confidence_count: int
    corrected_count: int
    pipeline_steps_completed: list[str]
    warnings: list[str]


#pipeline error

class PipelineError(BaseModel):
    step: str
    message: str
    recoverable: bool   #can continue without that step


#Soap generation request
#it is useful for building a prompt 

class SOAPGenerationRequest(BaseModel):
    visit_id: str
    transcript: str
    segments: list[EnrichedSegment]
    speciality: str = 'general'
    patient_context: Optional[dict] = None



#NER analyze
class NERRequest(BaseModel):
    visit_id: str
    transcript: str
    speciality: str = "general"


class NEREntity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    negated: bool = False
    confidence: float = 1.0

class NERResponse(BaseModel):
    visit_id: str
    medications: list[NEREntity] = []
    symptoms: list[NEREntity] = []
    diagnoses: list[NEREntity] = []


class DrugInteractionRequest(BaseModel):
    visit_id: str
    medications: list[str]    

class DrugInteractionResult(BaseModel):
    drug1: str
    drug2: str
    severity: Severity
    description: str
    source: str = "rxnav"

class BillingRequest(BaseModel):
    visit_id: str
    soap_assessment: str
    diagnoses: list[NEREntity]
    visit_duration_minutes: int


class ICD10Suggestion(BaseModel):
    code: str                       
    description: str                
    confidence: float = Field(ge=0.0, le=1.0)
    method: str                    
    reasoning: Optional[str] = None

class BillingResponse(BaseModel):
    visit_id: str
    icd10_codes: list[ICD10Suggestion] = []
    cpt_code: Optional[dict] = None
    coding_gaps: list[dict] = []


