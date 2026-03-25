import copy
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.assessment import (
    AssessmentAnswer,
    CaregiverAssessment,
    PatientAssessment,
    PatientProfile,
)
from app.models.user import User, UserRole


ASSESSMENT_CONFIDENCE_THRESHOLD = 0.65
PRIMARY_QUESTION_SET = "primary"
BACKUP_QUESTION_SET = "backup"
PATIENT_SURVEY = "patient"
CAREGIVER_SURVEY = "caregiver"


ASSESSMENT_QUESTION_CATALOG: Dict[str, Dict[str, Dict[str, Any]]] = {
    PATIENT_SURVEY: {
        PRIMARY_QUESTION_SET: {
            "title": "Quick Support Check",
            "subtitle": "Pick the option that feels closest today. You can skip any question.",
            "questions": [
                {
                    "id": "memory_support",
                    "prompt": "How often do you need reminders for daily tasks?",
                    "options": [
                        {"value": "rarely", "label": "Rarely or never", "description": "Mostly independent", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "A few prompts help", "weight": 2},
                        {"value": "often", "label": "Often", "description": "Frequent reminders help", "weight": 3},
                        {"value": "almost_always", "label": "Almost always", "description": "I rely on reminders most days", "weight": 4},
                    ],
                },
                {
                    "id": "orientation_confusion",
                    "prompt": "How often do you feel unsure about the time, day, or where you are?",
                    "options": [
                        {"value": "never", "label": "Almost never", "description": "I usually know right away", "weight": 0},
                        {"value": "occasionally", "label": "Occasionally", "description": "It happens once in a while", "weight": 1},
                        {"value": "often", "label": "Often", "description": "It happens many days", "weight": 3},
                        {"value": "very_often", "label": "Very often", "description": "I need regular reassurance", "weight": 4},
                    ],
                },
                {
                    "id": "recognition_people",
                    "prompt": "How often is it hard to recognize familiar people right away?",
                    "options": [
                        {"value": "never", "label": "Never", "description": "Faces feel familiar", "weight": 0},
                        {"value": "rarely", "label": "Rarely", "description": "Only in unusual moments", "weight": 1},
                        {"value": "sometimes", "label": "Sometimes", "description": "It takes extra time", "weight": 3},
                        {"value": "often", "label": "Often", "description": "Recognition is regularly difficult", "weight": 4},
                    ],
                },
                {
                    "id": "medication_support",
                    "prompt": "How do you usually manage medications?",
                    "options": [
                        {"value": "independent", "label": "I manage them myself", "description": "No reminders needed", "weight": 0},
                        {"value": "occasional_help", "label": "I need a little help", "description": "A check-in helps", "weight": 1},
                        {"value": "needs_reminders", "label": "I need reminders", "description": "Prompts keep me on track", "weight": 2},
                        {"value": "full_help", "label": "Someone manages them for me", "description": "I rely on direct support", "weight": 4},
                    ],
                },
                {
                    "id": "routine_following",
                    "prompt": "How easy is it to follow your usual daily routine?",
                    "options": [
                        {"value": "easy", "label": "Easy", "description": "My routine feels steady", "weight": 0},
                        {"value": "sometimes_hard", "label": "Sometimes hard", "description": "I need an occasional nudge", "weight": 1},
                        {"value": "often_hard", "label": "Often hard", "description": "I lose track frequently", "weight": 2},
                        {"value": "need_help", "label": "I need help", "description": "Someone usually guides me", "weight": 3},
                    ],
                },
            ],
        },
        BACKUP_QUESTION_SET: {
            "title": "A Few More Questions",
            "subtitle": "These help refine the result when the first answers are incomplete or mixed.",
            "questions": [
                {
                    "id": "recent_memory",
                    "prompt": "How often do you forget recent conversations or plans?",
                    "options": [
                        {"value": "rarely", "label": "Rarely", "description": "I usually remember", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "A reminder helps", "weight": 2},
                        {"value": "often", "label": "Often", "description": "It happens many times a week", "weight": 3},
                        {"value": "almost_always", "label": "Almost always", "description": "I rely on others to fill in gaps", "weight": 4},
                    ],
                },
                {
                    "id": "task_sequence",
                    "prompt": "How easy is it to complete familiar tasks with several steps?",
                    "options": [
                        {"value": "easy", "label": "Easy", "description": "I can do them on my own", "weight": 0},
                        {"value": "sometimes_hard", "label": "Sometimes hard", "description": "I lose track now and then", "weight": 2},
                        {"value": "often_hard", "label": "Often hard", "description": "I need reminders during the task", "weight": 3},
                        {"value": "need_help", "label": "I need help", "description": "Someone usually steps in", "weight": 4},
                    ],
                },
                {
                    "id": "safety_awareness",
                    "prompt": "How often do you worry about getting lost or feeling unsafe outside your routine?",
                    "options": [
                        {"value": "never", "label": "Never", "description": "I feel confident", "weight": 0},
                        {"value": "rarely", "label": "Rarely", "description": "Only in unfamiliar places", "weight": 1},
                        {"value": "sometimes", "label": "Sometimes", "description": "I need occasional support", "weight": 2},
                        {"value": "often", "label": "Often", "description": "I rely on strong support", "weight": 4},
                    ],
                },
                {
                    "id": "communication_clarity",
                    "prompt": "How often is it hard to find the right words or explain what you need?",
                    "options": [
                        {"value": "rarely", "label": "Rarely", "description": "I explain myself easily", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "I pause to find words", "weight": 1},
                        {"value": "often", "label": "Often", "description": "It interrupts conversations", "weight": 2},
                        {"value": "very_hard", "label": "Very hard", "description": "I need help expressing myself", "weight": 3},
                    ],
                },
            ],
        },
    },
    CAREGIVER_SURVEY: {
        PRIMARY_QUESTION_SET: {
            "title": "Caregiver Assessment",
            "subtitle": "Choose the option that best matches what you observe. You can skip any question.",
            "questions": [
                {
                    "id": "reminder_need",
                    "prompt": "How much prompting does the patient need for daily tasks?",
                    "options": [
                        {"value": "independent", "label": "Very little", "description": "Mostly independent", "weight": 0},
                        {"value": "some", "label": "Some prompts", "description": "Occasional reminders help", "weight": 2},
                        {"value": "frequent", "label": "Frequent prompts", "description": "Needs regular reminders", "weight": 3},
                        {"value": "constant", "label": "Constant support", "description": "Needs support throughout the day", "weight": 4},
                    ],
                },
                {
                    "id": "confusion_frequency",
                    "prompt": "How often does the patient seem confused about time, place, or routine?",
                    "options": [
                        {"value": "rarely", "label": "Rarely", "description": "Usually oriented", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "Mild confusion appears", "weight": 2},
                        {"value": "often", "label": "Often", "description": "Confusion interrupts the day", "weight": 3},
                        {"value": "constant", "label": "Constantly", "description": "Needs regular reassurance", "weight": 4},
                    ],
                },
                {
                    "id": "recognition_issues",
                    "prompt": "How often does the patient struggle to recognize familiar people or places?",
                    "options": [
                        {"value": "never", "label": "Never", "description": "Recognition is intact", "weight": 0},
                        {"value": "occasional", "label": "Occasionally", "description": "Brief hesitation", "weight": 1},
                        {"value": "sometimes", "label": "Sometimes", "description": "Recognition delays are noticeable", "weight": 3},
                        {"value": "often", "label": "Often", "description": "Recognition problems are common", "weight": 4},
                    ],
                },
                {
                    "id": "daily_support",
                    "prompt": "How much hands-on help does the patient need with routine tasks?",
                    "options": [
                        {"value": "independent", "label": "Independent", "description": "Mostly self-directed", "weight": 0},
                        {"value": "checkins", "label": "Check-ins", "description": "Needs oversight but not constant help", "weight": 1},
                        {"value": "daily_help", "label": "Daily hands-on help", "description": "Needs practical support every day", "weight": 3},
                        {"value": "continuous", "label": "Continuous support", "description": "Needs close supervision", "weight": 4},
                    ],
                },
                {
                    "id": "safety_risk",
                    "prompt": "How concerned are you about safety risks like wandering, falls, or missed medications?",
                    "options": [
                        {"value": "low", "label": "Low concern", "description": "Risks feel manageable", "weight": 0},
                        {"value": "mild", "label": "Mild concern", "description": "Some extra monitoring helps", "weight": 1},
                        {"value": "moderate", "label": "Moderate concern", "description": "Risks need active management", "weight": 3},
                        {"value": "high", "label": "High concern", "description": "Risks need close attention", "weight": 4},
                    ],
                },
            ],
        },
        BACKUP_QUESTION_SET: {
            "title": "Refine The Assessment",
            "subtitle": "A few backup questions improve confidence when the primary answers are incomplete or mixed.",
            "questions": [
                {
                    "id": "wandering_risk",
                    "prompt": "How often does the patient need support to avoid getting lost or disoriented outside the home?",
                    "options": [
                        {"value": "rarely", "label": "Rarely", "description": "Usually stays oriented", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "Needs reminders in new places", "weight": 2},
                        {"value": "often", "label": "Often", "description": "Needs supervision when out", "weight": 3},
                        {"value": "always", "label": "Almost always", "description": "Needs close monitoring", "weight": 4},
                    ],
                },
                {
                    "id": "communication_change",
                    "prompt": "How often does the patient struggle to follow or respond to conversation clearly?",
                    "options": [
                        {"value": "rarely", "label": "Rarely", "description": "Conversation is mostly clear", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "Needs extra time or cues", "weight": 1},
                        {"value": "often", "label": "Often", "description": "Conversation breaks down regularly", "weight": 2},
                        {"value": "very_often", "label": "Very often", "description": "Needs frequent support", "weight": 3},
                    ],
                },
                {
                    "id": "behavior_changes",
                    "prompt": "How often do mood or behavior changes affect care planning?",
                    "options": [
                        {"value": "rarely", "label": "Rarely", "description": "Little impact", "weight": 0},
                        {"value": "sometimes", "label": "Sometimes", "description": "Needs occasional adjustment", "weight": 1},
                        {"value": "often", "label": "Often", "description": "Regular care adjustments are needed", "weight": 2},
                        {"value": "very_often", "label": "Very often", "description": "Care plans change frequently", "weight": 3},
                    ],
                },
                {
                    "id": "support_reliability",
                    "prompt": "How confident are you that the patient can safely complete a full day without direct support?",
                    "options": [
                        {"value": "very_confident", "label": "Very confident", "description": "Can usually manage", "weight": 0},
                        {"value": "mostly_confident", "label": "Mostly confident", "description": "Needs light oversight", "weight": 1},
                        {"value": "not_confident", "label": "Not very confident", "description": "Needs consistent support", "weight": 3},
                        {"value": "not_safe", "label": "Not safe without support", "description": "Needs close supervision", "weight": 4},
                    ],
                },
            ],
        },
    },
}


#------This Function returns survey metadata and questions---------
def get_question_set(target: str, question_set: str) -> Dict[str, Any]:
    if target not in ASSESSMENT_QUESTION_CATALOG:
        raise ValueError("Unsupported survey target")
    if question_set not in ASSESSMENT_QUESTION_CATALOG[target]:
        raise ValueError("Unsupported question set")
    return copy.deepcopy(ASSESSMENT_QUESTION_CATALOG[target][question_set])


#------This Function returns only the questions for a survey---------
def get_questions(target: str, question_set: str) -> List[Dict[str, Any]]:
    return get_question_set(target, question_set)["questions"]


#------This Function normalizes assessment answers against the catalog---------
def normalize_answers(
    target: str,
    question_set: str,
    answers: List[Dict[str, Any]],
) -> List[AssessmentAnswer]:
    question_defs = get_questions(target, question_set)
    submitted_map: Dict[str, Dict[str, Any]] = {}

    for answer in answers:
        question_id = str(answer.get("question_id") or "").strip()
        if question_id:
            submitted_map[question_id] = answer

    normalized: List[AssessmentAnswer] = []
    for question in question_defs:
        question_id = question["id"]
        submitted = submitted_map.get(question_id, {})
        skipped = bool(submitted.get("skipped", False))
        answer_value = submitted.get("answer")
        valid_values = {option["value"] for option in question["options"]}

        if skipped or answer_value not in valid_values:
            normalized.append(
                AssessmentAnswer(
                    question_id=question_id,
                    answer=None,
                    skipped=True,
                )
            )
            continue

        normalized.append(
            AssessmentAnswer(
                question_id=question_id,
                answer=str(answer_value),
                skipped=False,
            )
        )

    return normalized


#------This Function calculates score and confidence for one assessment---------
def calculate_assessment_metrics(
    target: str,
    question_set: str,
    answers: List[AssessmentAnswer],
) -> Dict[str, Any]:
    question_defs = get_questions(target, question_set)
    question_map = {question["id"]: question for question in question_defs}

    score = 0.0
    answered_count = 0
    skipped_count = 0
    answer_map: Dict[str, str] = {}

    for answer in answers:
        question = question_map.get(answer.question_id)
        if not question or answer.skipped or not answer.answer:
            skipped_count += 1
            continue

        option = _get_option_definition(question, answer.answer)
        if option is None:
            skipped_count += 1
            continue

        answered_count += 1
        answer_map[answer.question_id] = answer.answer
        score += float(option.get("weight", 0))

    inconsistency_count = _detect_inconsistencies(target, answer_map)
    consistency_factor = max(0.55, 1 - (0.15 * inconsistency_count))

    total_questions = len(question_defs)
    confidence = 0.0
    if total_questions > 0:
        confidence = round((answered_count / total_questions) * consistency_factor, 3)

    needs_followup = (
        question_set == PRIMARY_QUESTION_SET
        and (skipped_count > 2 or inconsistency_count > 0 or confidence < ASSESSMENT_CONFIDENCE_THRESHOLD)
    )

    return {
        "score": round(score, 3),
        "condition_level": score_to_level(score),
        "confidence": confidence,
        "answered_count": answered_count,
        "skipped_count": skipped_count,
        "inconsistency_count": inconsistency_count,
        "consistency_factor": round(consistency_factor, 3),
        "needs_followup": needs_followup,
    }


#------This Function returns the latest patient assessment---------
async def get_latest_patient_assessment(patient_id: str) -> Optional[PatientAssessment]:
    assessments = await PatientAssessment.find(PatientAssessment.patient_id == patient_id).to_list()
    if not assessments:
        return None
    return max(assessments, key=lambda item: item.created_at)


#------This Function returns the latest caregiver assessment for one caregiver---------
async def get_latest_caregiver_assessment(
    patient_id: str,
    caregiver_id: str,
) -> Optional[CaregiverAssessment]:
    assessments = await CaregiverAssessment.find(
        CaregiverAssessment.patient_id == patient_id,
        CaregiverAssessment.caregiver_id == caregiver_id,
    ).to_list()
    if not assessments:
        return None
    return max(assessments, key=lambda item: item.created_at)


#------This Function returns latest caregiver assessments grouped by caregiver---------
async def get_latest_caregiver_assessments_by_patient(patient_id: str) -> List[CaregiverAssessment]:
    assessments = await CaregiverAssessment.find(CaregiverAssessment.patient_id == patient_id).to_list()
    latest_by_caregiver: Dict[str, CaregiverAssessment] = {}

    for assessment in assessments:
        current = latest_by_caregiver.get(assessment.caregiver_id)
        if current is None or assessment.created_at > current.created_at:
            latest_by_caregiver[assessment.caregiver_id] = assessment

    return list(latest_by_caregiver.values())


#------This Function returns the latest patient profile---------
async def get_patient_profile(patient_id: str) -> Optional[PatientProfile]:
    return await PatientProfile.find_one(PatientProfile.patient_id == patient_id)


#------This Function recomputes the aggregate patient profile---------
async def rebuild_patient_profile(patient_id: str) -> PatientProfile:
    latest_patient = await get_latest_patient_assessment(patient_id)
    caregiver_assessments = await get_latest_caregiver_assessments_by_patient(patient_id)
    profile = await PatientProfile.find_one(PatientProfile.patient_id == patient_id)
    active_caregivers = await User.find(User.linked_patients == patient_id).to_list()
    active_caregiver_ids = {caregiver.firebase_uid for caregiver in active_caregivers}
    if active_caregiver_ids:
        caregiver_assessments = [
            assessment
            for assessment in caregiver_assessments
            if assessment.caregiver_id in active_caregiver_ids
        ]
    else:
        caregiver_assessments = []

    if profile is None:
        profile = PatientProfile(patient_id=patient_id)

    weighted_scores: List[float] = []
    score_weights: List[int] = []
    weighted_answered = 0
    weighted_total = 0
    consistency_parts: List[float] = []
    consistency_weights: List[int] = []

    if latest_patient is not None:
        weighted_scores.append(latest_patient.score)
        score_weights.append(1)
        weighted_answered += latest_patient.answered_count
        weighted_total += latest_patient.answered_count + latest_patient.skipped_count
        consistency_parts.append(latest_patient.consistency_factor)
        consistency_weights.append(1)

    for caregiver_assessment in caregiver_assessments:
        weighted_scores.append(caregiver_assessment.severity_score)
        score_weights.append(2)
        weighted_answered += caregiver_assessment.answered_count * 2
        weighted_total += (caregiver_assessment.answered_count + caregiver_assessment.skipped_count) * 2
        consistency_parts.append(caregiver_assessment.consistency_factor)
        consistency_weights.append(2)

    final_score = 0.0
    if weighted_scores and sum(score_weights) > 0:
        final_score = sum(score * weight for score, weight in zip(weighted_scores, score_weights)) / sum(score_weights)

    caregiver_count = len(caregiver_assessments)
    completeness_factor = (weighted_answered / weighted_total) if weighted_total > 0 else 0.0
    source_consistency = _calculate_source_consistency(weighted_scores)
    response_consistency = _weighted_average(consistency_parts, consistency_weights, default=0.0)
    combined_consistency = round(min(source_consistency, response_consistency), 3)
    confidence_score = round(min(1.0, completeness_factor * combined_consistency * (1 + caregiver_count)), 3)

    user = await User.find_one(User.firebase_uid == patient_id)
    if user and user.preferences:
        profile.legacy_preferences = user.preferences

    profile.condition_level = score_to_level(final_score)
    profile.confidence_score = confidence_score
    profile.final_score = round(final_score, 3)
    profile.caregiver_count = caregiver_count
    profile.last_updated = datetime.utcnow()

    if profile.id:
        await profile.save()
    else:
        await profile.insert()

    return profile


#------This Function builds assessment status for one authenticated user---------
async def build_assessment_status(user: User) -> Dict[str, Any]:
    if user.role == UserRole.ADMIN:
        return {
            "role": user.role.value,
            "threshold": ASSESSMENT_CONFIDENCE_THRESHOLD,
            "pending_surveys": [],
            "recommended_surveys": [],
            "profile": None,
        }

    if user.role == UserRole.PATIENT:
        latest_assessment = await get_latest_patient_assessment(user.firebase_uid)
        profile = await get_patient_profile(user.firebase_uid)

        pending_surveys: List[Dict[str, Any]] = []
        recommended_surveys: List[Dict[str, Any]] = []

        if latest_assessment is None:
            pending_surveys.append(
                _build_survey_status_entry(
                    survey_type=PATIENT_SURVEY,
                    patient_id=user.firebase_uid,
                    patient_name=user.display_name or "You",
                    question_set=PRIMARY_QUESTION_SET,
                    reason="missing_assessment",
                    required=True,
                    confidence=0.0,
                )
            )
        elif latest_assessment.needs_followup or (profile and profile.confidence_score < ASSESSMENT_CONFIDENCE_THRESHOLD):
            recommended_surveys.append(
                _build_survey_status_entry(
                    survey_type=PATIENT_SURVEY,
                    patient_id=user.firebase_uid,
                    patient_name=user.display_name or "You",
                    question_set=BACKUP_QUESTION_SET,
                    reason="low_confidence",
                    required=False,
                    confidence=latest_assessment.confidence,
                )
            )

        return {
            "role": user.role.value,
            "threshold": ASSESSMENT_CONFIDENCE_THRESHOLD,
            "pending_surveys": pending_surveys,
            "recommended_surveys": recommended_surveys,
            "profile": serialize_patient_profile(profile),
        }

    linked_patients = await User.find(User.firebase_uid.in_(user.linked_patients)).to_list() if user.linked_patients else []
    linked_patients_by_id = {patient.firebase_uid: patient for patient in linked_patients}
    pending_surveys: List[Dict[str, Any]] = []
    recommended_surveys: List[Dict[str, Any]] = []

    for patient_id in user.linked_patients:
        patient = linked_patients_by_id.get(patient_id)
        patient_name = patient.display_name if patient and patient.display_name else "Linked Patient"
        latest_assessment = await get_latest_caregiver_assessment(patient_id, user.firebase_uid)
        profile = await get_patient_profile(patient_id)

        if latest_assessment is None:
            pending_surveys.append(
                _build_survey_status_entry(
                    survey_type=CAREGIVER_SURVEY,
                    patient_id=patient_id,
                    patient_name=patient_name,
                    question_set=PRIMARY_QUESTION_SET,
                    reason="missing_assessment",
                    required=True,
                    confidence=0.0,
                )
            )
            continue

        if latest_assessment.needs_followup or (profile and profile.confidence_score < ASSESSMENT_CONFIDENCE_THRESHOLD):
            recommended_surveys.append(
                _build_survey_status_entry(
                    survey_type=CAREGIVER_SURVEY,
                    patient_id=patient_id,
                    patient_name=patient_name,
                    question_set=BACKUP_QUESTION_SET,
                    reason="low_confidence",
                    required=False,
                    confidence=latest_assessment.confidence,
                )
            )

    return {
        "role": user.role.value,
        "threshold": ASSESSMENT_CONFIDENCE_THRESHOLD,
        "pending_surveys": pending_surveys,
        "recommended_surveys": recommended_surveys,
        "profile": None,
    }


#------This Function serializes patient profile responses---------
def serialize_patient_profile(profile: Optional[PatientProfile]) -> Optional[Dict[str, Any]]:
    if profile is None:
        return None

    return {
        "patient_id": profile.patient_id,
        "condition_level": profile.condition_level,
        "confidence_score": profile.confidence_score,
        "final_score": profile.final_score,
        "caregiver_count": profile.caregiver_count,
        "last_updated": profile.last_updated.isoformat(),
    }


#------This Function maps score ranges to condition levels---------
def score_to_level(score: float) -> str:
    if score >= 13:
        return "high"
    if score >= 8:
        return "moderate"
    if score >= 4:
        return "mild"
    return "low"


#------This Function returns one option definition for a question---------
def _get_option_definition(question: Dict[str, Any], answer_value: str) -> Optional[Dict[str, Any]]:
    for option in question["options"]:
        if option["value"] == answer_value:
            return option
    return None


#------This Function counts rule-based inconsistencies in answers---------
def _detect_inconsistencies(target: str, answer_map: Dict[str, str]) -> int:
    inconsistencies = 0

    if target == PATIENT_SURVEY:
        if answer_map.get("orientation_confusion") in {"often", "very_often"} and answer_map.get("routine_following") == "easy":
            inconsistencies += 1
        if answer_map.get("recognition_people") == "often" and answer_map.get("memory_support") == "rarely":
            inconsistencies += 1
        if answer_map.get("medication_support") == "independent" and answer_map.get("memory_support") in {"often", "almost_always"}:
            inconsistencies += 1
        if answer_map.get("safety_awareness") == "often" and answer_map.get("task_sequence") == "easy":
            inconsistencies += 1
        return inconsistencies

    if answer_map.get("daily_support") == "independent" and answer_map.get("safety_risk") == "high":
        inconsistencies += 1
    if answer_map.get("reminder_need") == "independent" and answer_map.get("confusion_frequency") in {"often", "constant"}:
        inconsistencies += 1
    if answer_map.get("recognition_issues") == "often" and answer_map.get("daily_support") == "independent":
        inconsistencies += 1
    if answer_map.get("wandering_risk") == "always" and answer_map.get("support_reliability") == "very_confident":
        inconsistencies += 1
    return inconsistencies


#------This Function measures agreement across assessment sources---------
def _calculate_source_consistency(scores: List[float]) -> float:
    if len(scores) <= 1:
        return 1.0

    spread = max(scores) - min(scores)
    return round(max(0.6, 1 - (spread / 20.0)), 3)


#------This Function computes a weighted average with a default---------
def _weighted_average(values: List[float], weights: List[int], default: float = 0.0) -> float:
    if not values or not weights or len(values) != len(weights):
        return default

    total_weight = sum(weights)
    if total_weight <= 0:
        return default

    return round(sum(value * weight for value, weight in zip(values, weights)) / total_weight, 3)


#------This Function builds one survey status entry---------
def _build_survey_status_entry(
    survey_type: str,
    patient_id: str,
    patient_name: str,
    question_set: str,
    reason: str,
    required: bool,
    confidence: float,
) -> Dict[str, Any]:
    return {
        "survey_type": survey_type,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "question_set": question_set,
        "reason": reason,
        "required": required,
        "confidence": round(confidence, 3),
    }
