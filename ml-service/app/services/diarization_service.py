import torch
import logging
import os
import re
import json
from pathlib import Path
from typing import Optional, List, Dict


from app.models.schemas import DiarizationSegment,SpeakerRole
from app.config import settings



logger = logging.getLogger(__name__)


#Requires pyannote a hugging face token to automatically accepted
#Model download from HF_HOME
#https://huggingface.co/pyannote/speaker-diarization-3.1

def load_diarization_pipeline():
    """
    Load the pre-trained speaker diarization pipeline with model caching
    Returns None if loading fails rather than crashing pipeline
        pyannote.audio.Pipeline: Initialized diarization pipeline
    """

    try:
        from pyannote.audio import Pipeline

        token = settings.huggingface_token
        if not token or token == "your_huggingface_token_here":
            logger.warning("Hugging Face token missing no diarization")
            return None

        logger.info("Loading PyAnnote speaker diarization pipeline...")

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=token
        )

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        pipeline.to(device)

        logger.info(f"Diarization pipeline loaded successfully on {device}")

        return pipeline
    except ImportError:
        logger.warning("Pyannote not installed."
        "Run: pip install pyannote.audio")
        return None

    except Exception as e:
        logger.error(f"Failed to load diarization pipeline: {e}")
        logger.warning(
            "Continuing without diarization — "
            "speaker labels will not be available"
        )
        return None


def diarize_audio(audio_path: str,diarization_pipeline,num_speakers: Optional[int] = None,min_speakers: int = 1,max_speakers: int = 4) -> list[DiarizationSegment]:
    if diarization_pipeline is None:
        logger.warning("Diarization pipeline not loaded - returning empty segments")
        return []

    logger.info(f"Starting diarization: {audio_path}")

    try:
        diarize_kwargs = {}
        if num_speakers is not None:
            diarize_kwargs["num_speakers"] = num_speakers
            logger.info(f"Diarizing with fixed speaker count: {num_speakers}")
        else:
            diarize_kwargs["min_speakers"] = min_speakers
            diarize_kwargs["max_speakers"] = max_speakers
            logger.info(f"Diarizing with speaker range: {min_speakers}-{max_speakers}")

        diarization_result = diarization_pipeline(
            audio_path,
            **diarize_kwargs
        )

        segments = []
        for turn, _, speaker in diarization_result.itertracks(
            yield_label=True
        ):
            if (turn.end - turn.start) < 0.3:
                continue

            segments.append(DiarizationSegment(
                speaker=speaker,
                start=round(turn.start, 3),
                end=round(turn.end, 3)
            ))

        segments.sort(key=lambda x: x.start)
        
        unique_speakers = set(s.speaker for s in segments)

        logger.info(f"Diarization complete. Speakers: {list(unique_speakers)}")

        return segments

    except Exception as e:
        logger.error(f"Diarization failed for {audio_path}: {e}")
        logger.warning("Returning empty segments")
        return []


def align_whisper_with_diarization(
    whisper_segments: list, 
    diarization_segments: list[DiarizationSegment]
) -> list:
    """
    Aligns Whisper segments with Pyannote speaker turns using maximum time overlap.
    Mutates/updates the Whisper segments by setting their 'speaker' attribute.
    """
    if not whisper_segments:
        return []
    for w_seg in whisper_segments:
        best_speaker = "UNKNOWN"
        max_overlap = 0.0
        
        # Calculate overlap duration with each diarization turn
        for d_seg in diarization_segments:
            overlap_start = max(w_seg.start, d_seg.start)
            overlap_end = min(w_seg.end, d_seg.end)
            overlap = max(0.0, overlap_end - overlap_start)
            
            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = d_seg.speaker
                
        # Set speaker attribute on segment (or dictionary)
        if isinstance(w_seg, dict):
            w_seg["speaker"] = best_speaker
        else:
            setattr(w_seg, "speaker", best_speaker)
            
    return whisper_segments


def get_role_assignment_from_llm(
    speakers: list[str], 
    dialogue_transcript: str
) -> Optional[dict[str, SpeakerRole]]:
    """
    Calls Ollama to classify speaker IDs using Llama 3.1 context understanding.
    Returns a mapping of speaker ID to SpeakerRole, or None if Ollama fails.
    """
    try:
        import ollama
        
        # Format the URL if it's set in base settings
        # The ollama client takes host='http://ollama:11434'
        host = settings.ollama_base_url
        client = ollama.Client(host=host)
        
        prompt = f"""
You are a medical transcription assistant. Your job is to assign clinical roles to the speaker IDs in the conversation transcript below.

Available roles:
- "DOCTOR": The clinician conducting the interview, asking diagnostic questions, prescribing meds, directing the encounter.
- "PATIENT": The individual presenting symptoms, answering medical history, narrating concerns.
- "FAMILY": Caregiver, parent, or spouse accompanying the patient, giving additional details.

List of Speaker IDs to classify: {speakers}

Transcript:
\"\"\"
{dialogue_transcript}
\"\"\"

Analyze the transcript. Return ONLY a valid JSON object matching each Speaker ID to their assigned role. 
Format:
{{
  "SPEAKER_00": "DOCTOR",
  "SPEAKER_01": "PATIENT"
}}

Do not write code blocks, markdown wrapper, headers, introduction, or explanations. Just return the raw JSON.
"""

        logger.info(f"Sending prompt to Ollama model {settings.ollama_model} at {host}")
        
        response = client.generate(
            model=settings.ollama_model,
            prompt=prompt,
            options={
                "temperature": 0.0
            },
            format="json"
        )
        
        raw_response = response.get("response", "").strip()
        logger.debug(f"Ollama raw response: {raw_response}")
        
        parsed_roles = json.loads(raw_response)
        
        # Convert string values to SpeakerRole enums
        role_map = {}
        for spk, role_str in parsed_roles.items():
            if spk in speakers:
                try:
                    role_map[spk] = SpeakerRole(role_str.upper())
                except ValueError:
                    role_map[spk] = SpeakerRole.UNKNOWN
        return role_map
            
    except Exception as e:
        logger.warning(f"Failed to query Ollama for speaker roles: {e}")
        return None


def _score_medical_terminology(
    whisper_segments: list, 
    speakers: list[str],
    smoothing_factor: int = 15
) -> dict[str, float]:
    """
    Computes medical terminology density per speaker using regex boundary matching
    and smoothing to prevent short utterances from inflating scores.
    """
    CLINICAL_TERMS = {
        # Examination terms
        "auscultation", "palpation", "percussion", "bilateral",
        "systolic", "diastolic", "tachycardia", "bradycardia",
        "hypertension", "hypotension", "febrile", "afebrile",

        # Prescription language
        "prescribe", "prescribed", "milligram", "dosage", "twice daily",
        "once daily", "orally", "intravenous", "subcutaneous",
        "contraindicated", "titrate", "titration",

        # Diagnostic terms
        "differential", "diagnosis", "prognosis", "etiology",
        "pathology", "acute", "chronic", "idiopathic",
        "comorbidity", "complication",

        # Lab terms
        "hemoglobin", "creatinine", "bilirubin", "glucose",
        "hba1c", "ecg", "ultrasound", "mri", "ct scan",

        # Instruction terms — doctors give instructions
        "follow up", "follow-up", "refer", "referral",
        "admission", "discharge", "monitor", "review",

        # Drug names — partial match handles generics
        "metformin", "atorvastatin", "amlodipine", "losartan",
        "lisinopril", "metoprolol", "aspirin", "warfarin",
        "insulin", "amoxicillin", "azithromycin",
    }

    pattern = re.compile(
        r'\b(' + '|'.join(map(re.escape, CLINICAL_TERMS)) + r')\b', 
        re.IGNORECASE
    )

    speaker_term_counts = {speaker: 0 for speaker in speakers}
    speaker_word_counts = {speaker: 0 for speaker in speakers}

    for seg in whisper_segments:
        speaker = getattr(seg, "speaker", None)
        if not speaker and isinstance(seg, dict):
            speaker = seg.get("speaker")
            
        if not speaker or speaker not in speakers:
            continue
        
        text = getattr(seg, "text", "")
        if not text and isinstance(seg, dict):
            text = seg.get("text", "")
            
        text_lower = text.lower()
        words = text_lower.split()
        speaker_word_counts[speaker] += len(words)

        matches = pattern.findall(text_lower)
        speaker_term_counts[speaker] += len(matches)

    densities = {}
    for speaker in speakers:
        word_count = speaker_word_counts.get(speaker, 0)
        term_count = speaker_term_counts.get(speaker, 0)
        densities[speaker] = term_count / (word_count + smoothing_factor)

    max_density = max(densities.values()) if densities else 0.0

    if max_density == 0:
        return {speaker: 0.0 for speaker in speakers}

    return {
        speaker: density / max_density
        for speaker, density in densities.items()
    }


def _analyze_conversational_cues(
    whisper_segments: list, 
    speakers: list[str]
) -> dict[str, dict[str, float]]:
    """
    Analyzes pronouns and questions to help identify roles.
    """
    cues = {
        spk: {"questions": 0.0, "pronouns_patient": 0.0, "pronouns_doctor": 0.0, "word_count": 0}
        for spk in speakers
    }
    
    patient_pronouns = re.compile(r'\b(i|my|me|myself|mine)\b', re.IGNORECASE)
    doctor_pronouns = re.compile(r'\b(you|your|yours|we|our|us)\b', re.IGNORECASE)
    
    for seg in whisper_segments:
        speaker = getattr(seg, "speaker", None)
        if not speaker and isinstance(seg, dict):
            speaker = seg.get("speaker")
            
        if not speaker or speaker not in speakers:
            continue
            
        text = getattr(seg, "text", "")
        if not text and isinstance(seg, dict):
            text = seg.get("text", "")
            
        text = text.strip()
        words = text.split()
        cues[speaker]["word_count"] += len(words)
        
        if text.endswith('?') or any(text.lower().startswith(q) for q in ["how", "what", "where", "why", "when", "does", "do", "have", "is", "are"]):
            cues[speaker]["questions"] += 1
            
        cues[speaker]["pronouns_patient"] += len(patient_pronouns.findall(text))
        cues[speaker]["pronouns_doctor"] += len(doctor_pronouns.findall(text))

    scores = {spk: {"questions_score": 0.0, "pronoun_score": 0.0} for spk in speakers}
    for spk in speakers:
        total_words = cues[spk]["word_count"]
        if total_words > 0:
            scores[spk]["questions_score"] = (cues[spk]["questions"] / total_words) * 100
            scores[spk]["pronoun_score"] = (cues[spk]["pronouns_doctor"] - cues[spk]["pronouns_patient"]) / total_words
            
    return scores


def run_heuristic_role_assignment(
    diarization_segments: list[DiarizationSegment], 
    whisper_segments: list = None
) -> dict[str, SpeakerRole]:
    """
    Heuristics fallback score-based role mapping with corrected Factor 4 and improved features.

    NOTE: whisper_segments should already have 'speaker' attributes
    set by align_whisper_with_diarization() before calling this function.
    If not aligned, terminology scoring will be skipped automatically.
    """
    speakers = list(set(s.speaker for s in diarization_segments))
    scores = {speaker: 0.0 for speaker in speakers}

    # Factor 1: Who speaks first (Moderate weight: +1.5)
    first_segment = min(diarization_segments, key=lambda s: s.start)
    scores[first_segment.speaker] += 1.5
    logger.debug(f"First speaker: {first_segment.speaker} (+1.5)")

    # Factor 2: Turn count
    turn_counts = {spk: 0 for spk in speakers}
    for seg in diarization_segments:
        turn_counts[seg.speaker] += 1

    max_turns_speaker = max(turn_counts, key=turn_counts.get)
    scores[max_turns_speaker] += 2.0
    logger.debug(f"Max turns speaker: {max_turns_speaker} ({turn_counts[max_turns_speaker]} turns)")

    # Factor 3: Avg turn duration
    speaker_durations = {spk: [] for spk in speakers}
    for seg in diarization_segments:
        speaker_durations[seg.speaker].append(seg.end - seg.start)
    
    avg_durations = {
        speaker: sum(durations) / len(durations)
        for speaker, durations in speaker_durations.items()
        if durations
    }

    min_avg_speaker = min(avg_durations, key=avg_durations.get)
    scores[min_avg_speaker] += 1.5
    logger.debug(f"Avg turn durations: {avg_durations} → {min_avg_speaker} +1.5 (shorter avg = doctor)")

    # Factor 4: Short turn ratio (Corrected Factor 4 Score Target and NameError)
    short_turn_threshold = 3.0
    short_turn_counts = {spk: 0 for spk in speakers}

    for seg in diarization_segments:
        if (seg.end - seg.start) < short_turn_threshold:
            short_turn_counts[seg.speaker] += 1

    max_short_turn_spk = max(short_turn_counts, key=short_turn_counts.get)

    if short_turn_counts[max_short_turn_spk] > 0:
        scores[max_short_turn_spk] += 2.0
        logger.debug(f"Short turn counts: {short_turn_counts} → {max_short_turn_spk} +2.0")

    # Factor 5: Medical terminology
    if whisper_segments:
        try:
            terminology_scores = _score_medical_terminology(whisper_segments, speakers)
            for speaker, term_score in terminology_scores.items():
                scores[speaker] += term_score * 3.5
                logger.debug(f"Terminology score: {speaker} +{term_score * 3.5:.2f}")
                
            # Factor 6: Conversational cues
            cue_scores = _analyze_conversational_cues(whisper_segments, speakers)
            for speaker, cue_data in cue_scores.items():
                q_score = min(2.0, cue_data["questions_score"] * 0.2)
                scores[speaker] += q_score
                
                
                pronoun_bonus = max(0.0, cue_data["pronoun_score"] * 2.5)
                scores[speaker] += pronoun_bonus
                logger.debug(f"Cues for {speaker} -> Questions: +{q_score:.2f}, Pronouns: {pronoun_bonus:+.2f}")
        except Exception as e:
            logger.warning(f"Terminology or cue scoring failed: {e}")

    logger.info(f"Final heuristic scores: {scores}")

    sorted_by_score = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    role_map = {}
    if len(sorted_by_score) >= 2:
        role_map[sorted_by_score[0][0]] = SpeakerRole.DOCTOR
        role_map[sorted_by_score[1][0]] = SpeakerRole.PATIENT

        for speaker_id, _ in sorted_by_score[2:]:
            role_map[speaker_id] = SpeakerRole.FAMILY
    elif len(sorted_by_score) == 1:
        role_map[sorted_by_score[0][0]] = SpeakerRole.DOCTOR

    return role_map


def assign_speaker_roles(
    diarization_segments: list[DiarizationSegment], 
    whisper_segments: list = None
) -> dict[str, SpeakerRole]:
    """
    Map Pyannote speaker ids to clinical roles using a hybrid model:
    Ollama Llama 3.1:8b semantic role detection with a robust heuristic fallback.
    """
    if not diarization_segments:
        return {}
        
    speakers = list(set(s.speaker for s in diarization_segments))

    if len(speakers) == 1:
        role_map = {speakers[0]: SpeakerRole.DOCTOR}
        logger.warning("Single speaker detected - assigned as doctor")
        return role_map

    if whisper_segments:
        try:
            whisper_segments = align_whisper_with_diarization(whisper_segments, diarization_segments)
            dialogue_turns = []
            for seg in whisper_segments[:50]:
                speaker = getattr(seg, "speaker", None)
                if not speaker and isinstance(seg, dict):
                    speaker = seg.get("speaker")
                if not speaker:
                    speaker = "UNKNOWN"
                    
                text = getattr(seg, "text", "")
                if not text and isinstance(seg, dict):
                    text = seg.get("text", "")
                    
                dialogue_turns.append(f"{speaker}: {text}")
            
            dialogue_transcript = "\n".join(dialogue_turns)
            
            logger.info("Attempting speaker role assignment using Ollama...")
            llm_roles = get_role_assignment_from_llm(speakers, dialogue_transcript)
            
            if llm_roles:
                # Verify that a reasonable coverage of speakers was mapped by LLM (at least 50%)
                coverage = len(llm_roles) / len(speakers)
                if coverage < 0.5:
                    logger.warning(
                        f"LLM only mapped {len(llm_roles)}/{len(speakers)} speakers — "
                        "falling back to heuristics"
                    )
                else:
                    logger.info(f"Role assignment via Ollama successful: {llm_roles}")
                    return llm_roles
                
            logger.warning("Ollama role mapping failed or returned incomplete results. Falling back to heuristics...")
            
        except Exception as e:
            logger.warning(f"Error during LLM speaker role assignment: {e}. Falling back to heuristics...")

    logger.info("Running heuristic speaker role assignment...")
    role_map = run_heuristic_role_assignment(diarization_segments, whisper_segments)
    
    logger.info(
        f"Role assignment result: "
        f"{[f'{s}={r.value}' for s, r in role_map.items()]}"
    )

    return role_map
    
    
    

    
    





