import torch
import logging
import os
import re
import json
import copy
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
    Aligns Whisper transcript segments with Pyannote speaker turns at the word level.
    Groups consecutive words belonging to the same speaker into clean text turns.
    If a segment has no word-level timestamps, falls back to segment-level overlap.
    """
    if not whisper_segments:
        return []
    if not diarization_segments:
        # No diarization available, assign speaker="UNKNOWN" to all segments
        for seg in whisper_segments:
            if isinstance(seg, dict):
                seg["speaker"] = "UNKNOWN"
            else:
                setattr(seg, "speaker", "UNKNOWN")
        return whisper_segments

    aligned_turns = []
    current_speaker = None
    current_words = []
    
    seg_id = 0

    for seg in whisper_segments:
        # Extract word timestamps if available
        words = getattr(seg, "words", None)
        if words is None and isinstance(seg, dict):
            words = seg.get("words")
            
        # Fallback to segment-level alignment if no word timestamps are found
        if not words:
            best_speaker = "UNKNOWN"
            max_overlap = 0.0
            
            s_start = seg.get("start", 0.0) if isinstance(seg, dict) else getattr(seg, "start", 0.0)
            s_end = seg.get("end", 0.0) if isinstance(seg, dict) else getattr(seg, "end", 0.0)
            s_text = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")
            
            for d_seg in diarization_segments:
                overlap_start = max(s_start, d_seg.start)
                overlap_end = min(s_end, d_seg.end)
                overlap = max(0.0, overlap_end - overlap_start)
                
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = d_seg.speaker
            
            # Flush accumulated words if speaker changes
            if current_words:
                aligned_turns.append({
                    "id": seg_id,
                    "speaker": current_speaker,
                    "start": current_words[0]["start"],
                    "end": current_words[-1]["end"],
                    "text": " ".join([w["word"] for w in current_words]),
                    "words": [w["raw_obj"] for w in current_words]
                })
                seg_id += 1
                current_words = []
                current_speaker = None
                
            aligned_turns.append({
                "id": seg_id,
                "speaker": best_speaker,
                "start": s_start,
                "end": s_end,
                "text": s_text,
                "words": []
            })
            seg_id += 1
            continue

        # Map each word to a speaker based on diarization overlap
        for w in words:
            w_start = w.get("start", 0.0) if isinstance(w, dict) else getattr(w, "start", 0.0)
            w_end = w.get("end", 0.0) if isinstance(w, dict) else getattr(w, "end", 0.0)
            w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")
                
            best_speaker = "UNKNOWN"
            max_overlap = 0.0
            
            for d_seg in diarization_segments:
                overlap_start = max(w_start, d_seg.start)
                overlap_end = min(w_end, d_seg.end)
                overlap = max(0.0, overlap_end - overlap_start)
                
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = d_seg.speaker
            
            # Default to containing segment midpoint if zero overlap
            if max_overlap == 0.0:
                midpoint = (w_start + w_end) / 2
                for d_seg in diarization_segments:
                    if d_seg.start <= midpoint <= d_seg.end:
                        best_speaker = d_seg.speaker
                        break
            
            # Flush buffer on speaker transition
            if best_speaker != current_speaker:
                if current_words:
                    aligned_turns.append({
                        "id": seg_id,
                        "speaker": current_speaker,
                        "start": current_words[0]["start"],
                        "end": current_words[-1]["end"],
                        "text": " ".join([word["word"] for word in current_words]),
                        "words": [word["raw_obj"] for word in current_words]
                    })
                    seg_id += 1
                current_speaker = best_speaker
                current_words = []
                
            current_words.append({
                "word": w_text,
                "start": w_start,
                "end": w_end,
                "raw_obj": w
            })

    # Flush final remaining words
    if current_words:
        aligned_turns.append({
            "id": seg_id,
            "speaker": current_speaker,
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
            "text": " ".join([word["word"] for word in current_words]),
            "words": [word["raw_obj"] for word in current_words]
        })

    return aligned_turns


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


def find_nearest_speaker(
    timestamp: float, 
    diarization_segments: list[DiarizationSegment]
) -> Optional[tuple[str, float]]:
    """
    Finds the nearest diarization segment to the given timestamp.
    Returns tuple of (speaker_id, distance_in_seconds) or None.
    """
    if not diarization_segments:
        return None
        
    min_dist = float('inf')
    nearest_speaker = None
    
    for seg in diarization_segments:
        if seg.start <= timestamp <= seg.end:
            dist = 0.0
        elif timestamp < seg.start:
            dist = seg.start - timestamp
        else:
            dist = timestamp - seg.end
            
        if dist < min_dist:
            min_dist = dist
            nearest_speaker = seg.speaker
            
    if nearest_speaker is not None:
        return (nearest_speaker, min_dist)
    return None


def clone_segment(seg, start, end, text, speaker, role, words, seg_id):
    if isinstance(seg, dict):
        return {
            **seg,
            "id": seg_id,
            "start": start,
            "end": end,
            "text": text,
            "speaker": speaker,
            "role": role,
            "words": words
        }
    else:
        # Polymorphic copy for Pydantic models or custom objects
        try:
            if hasattr(seg, "model_copy"):
                new_seg = seg.model_copy(update={
                    "id": seg_id,
                    "start": start,
                    "end": end,
                    "text": text,
                    "speaker": speaker,
                    "role": role,
                    "words": words
                })
                # Set attribute just to be safe if they are not fields
                setattr(new_seg, "speaker", speaker)
                setattr(new_seg, "role", role)
                return new_seg
            elif hasattr(seg, "copy"):
                new_seg = seg.copy(update={
                    "id": seg_id,
                    "start": start,
                    "end": end,
                    "text": text,
                    "speaker": speaker,
                    "role": role,
                    "words": words
                })
                setattr(new_seg, "speaker", speaker)
                setattr(new_seg, "role", role)
                return new_seg
        except Exception:
            pass
            
        new_seg = copy.copy(seg)
        setattr(new_seg, "id", seg_id)
        setattr(new_seg, "start", start)
        setattr(new_seg, "end", end)
        setattr(new_seg, "text", text)
        setattr(new_seg, "speaker", speaker)
        setattr(new_seg, "role", role)
        setattr(new_seg, "words", words)
        return new_seg


def assign_speakers_to_segments(
    scored_segments: list,          # list of ScoredSegment
    diarization_segments: list[DiarizationSegment],
    role_map: dict[str, SpeakerRole],
) -> list:
    """
    Assign speaker labels to Whisper transcript segments using PyAnnote diarization output.
    Uses Word-Level Alignment to map every word to the active speaker at that millisecond,
    splitting the segments at speaker transition boundaries.
    Falls back to segment-level overlap/nearest speaker matching if word timestamps are missing.

    Args:
        scored_segments: Output from confidence_service
        diarization_segments: Output from diarize_audio
        role_map: Mapping from speaker ID to clinical role

    Returns:
        New or modified segments with speaker and role fields populated
    """
    if not diarization_segments:
        logger.warning("No diarization segments — speaker labels unavailable")
        for seg in scored_segments:
            if isinstance(seg, dict):
                seg["speaker"] = "UNKNOWN"
                seg["role"] = SpeakerRole.UNKNOWN
            else:
                setattr(seg, "speaker", "UNKNOWN")
                setattr(seg, "role", SpeakerRole.UNKNOWN)
        return scored_segments

    assigned_turns = []
    seg_id = 0
    assigned_count = 0
    unknown_count = 0

    for seg in scored_segments:
        # Extract word timestamps if available
        words = getattr(seg, "words", None)
        if words is None and isinstance(seg, dict):
            words = seg.get("words")

        start = seg.get("start", 0.0) if isinstance(seg, dict) else getattr(seg, "start", 0.0)
        end = seg.get("end", 0.0) if isinstance(seg, dict) else getattr(seg, "end", 0.0)
        text = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")

        # Fallback to segment-level matching if no words
        if not words:
            best_speaker = None
            max_overlap = 0.0

            # Calculate overlap duration with each diarization turn
            for diar_seg in diarization_segments:
                overlap_start = max(start, diar_seg.start)
                overlap_end = min(end, diar_seg.end)
                overlap = max(0.0, overlap_end - overlap_start)
                
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = diar_seg.speaker

            if best_speaker and max_overlap > 0.0:
                role = role_map.get(best_speaker, SpeakerRole.UNKNOWN)
                assigned_turns.append(clone_segment(seg, start, end, text, best_speaker, role, [], seg_id))
                seg_id += 1
                assigned_count += 1
            else:
                midpoint = (start + end) / 2
                nearest = find_nearest_speaker(midpoint, diarization_segments)
                if nearest and nearest[1] < 2.0:
                    role = role_map.get(nearest[0], SpeakerRole.UNKNOWN)
                    assigned_turns.append(clone_segment(seg, start, end, text, nearest[0], role, [], seg_id))
                    assigned_count += 1
                else:
                    assigned_turns.append(clone_segment(seg, start, end, text, "UNKNOWN", SpeakerRole.UNKNOWN, [], seg_id))
                    unknown_count += 1
                seg_id += 1
            continue

        # Word-level alignment and grouping within this segment
        # current_speaker = None initially
        # First iteration: best_speaker != None → True
        # but current_words is empty → no flush
        # Just sets current_speaker to first word's speaker
        current_speaker = None
        current_words = []

        for w in words:
            w_start = w.get("start", 0.0) if isinstance(w, dict) else getattr(w, "start", 0.0)
            w_end = w.get("end", 0.0) if isinstance(w, dict) else getattr(w, "end", 0.0)
            w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")

            # Guard against zero timestamps by interpolating from the previous word (Issue 2)
            if w_start == 0.0 and w_end == 0.0 and len(current_words) > 0:
                prev_end = current_words[-1]["end"]
                w_start = prev_end
                w_end = prev_end + 0.1
                # Write back to original word dict or object
                if isinstance(w, dict):
                    w["start"] = w_start
                    w["end"] = w_end
                else:
                    try:
                        setattr(w, "start", w_start)
                        setattr(w, "end", w_end)
                    except Exception:
                        pass

            best_speaker = "UNKNOWN"
            max_overlap = 0.0

            # Calculate overlap for this word
            for d_seg in diarization_segments:
                overlap_start = max(w_start, d_seg.start)
                overlap_end = min(w_end, d_seg.end)
                overlap = max(0.0, overlap_end - overlap_start)
                
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = d_seg.speaker

            # Default to containing segment midpoint if zero overlap (e.g. silence)
            if max_overlap == 0.0:
                midpoint = (w_start + w_end) / 2
                for d_seg in diarization_segments:
                    if d_seg.start <= midpoint <= d_seg.end:
                        best_speaker = d_seg.speaker
                        break

            # If speaker changes, package the current buffer (Issue 3)
            if best_speaker != current_speaker:
                if current_words and len(current_words) >= 2:
                    # Flush complete buffer
                    role = role_map.get(current_speaker, SpeakerRole.UNKNOWN)
                    assigned_turns.append(clone_segment(
                        seg, 
                        current_words[0]["start"], 
                        current_words[-1]["end"], 
                        " ".join([word["word"] for word in current_words]),
                        current_speaker,
                        role,
                        [word["raw_obj"] for word in current_words],
                        seg_id
                    ))
                    seg_id += 1
                    if current_speaker != "UNKNOWN":
                        assigned_count += 1
                    else:
                        unknown_count += 1
                    leftover = []
                elif current_words:
                    # Carry over single word to next speaker's buffer rather than creating a one-word segment
                    leftover = current_words
                else:
                    leftover = []

                current_speaker = best_speaker
                current_words = leftover  # carry over orphaned words

            current_words.append({
                "word": w_text,
                "start": w_start,
                "end": w_end,
                "raw_obj": w
            })

        # Flush any remaining words in buffer (Issue 3)
        if current_words:
            # We don't apply the >= 2 restriction to the final flush of the segment 
            # to make sure we don't drop the last word if it happens to be orphaned.
            role = role_map.get(current_speaker, SpeakerRole.UNKNOWN)
            assigned_turns.append(clone_segment(
                seg, 
                current_words[0]["start"], 
                current_words[-1]["end"], 
                " ".join([word["word"] for word in current_words]),
                current_speaker,
                role,
                [word["raw_obj"] for word in current_words],
                seg_id
            ))
            seg_id += 1
            if current_speaker != "UNKNOWN":
                assigned_count += 1
            else:
                unknown_count += 1

    # Log and sanity warning check (Issue 5)
    logger.info(
        f"Speaker assignment: {assigned_count} assigned, "
        f"{unknown_count} unknown "
        f"(Input: {len(scored_segments)} segments -> "
        f"Output: {len(assigned_turns)} segments after splitting)"
    )

    if len(assigned_turns) > len(scored_segments) * 5:
        logger.warning(
            f"Segment count increased {len(assigned_turns) / len(scored_segments):.1f}x "
            f"after speaker splitting — possible diarization fragmentation. "
            f"Check audio quality."
        )

    return assigned_turns

    
    
    

    
    





