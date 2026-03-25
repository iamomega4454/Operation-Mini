from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import List, Optional

from app.core.firebase import get_current_user_uid
from app.models.assessment import CaregiverAssessment, PatientAssessment
from app.models.user import User, UserRole
from app.services.assessment_engine import (
    ASSESSMENT_CONFIDENCE_THRESHOLD,
    BACKUP_QUESTION_SET,
    CAREGIVER_SURVEY,
    PATIENT_SURVEY,
    PRIMARY_QUESTION_SET,
    build_assessment_status,
    calculate_assessment_metrics,
    get_question_set,
    normalize_answers,
    rebuild_patient_profile,
    serialize_patient_profile,
)

router = APIRouter(tags=["assessment"])


class AssessmentAnswerRequest(BaseModel):
    question_id: str
    answer: Optional[str] = None
    skipped: bool = False

    @field_validator("question_id")
    @classmethod
    def validate_question_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question id is required")
        return value


class PatientAssessmentRequest(BaseModel):
    question_set: str = PRIMARY_QUESTION_SET
    answers: List[AssessmentAnswerRequest] = []

    @field_validator("question_set")
    @classmethod
    def validate_question_set(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {PRIMARY_QUESTION_SET, BACKUP_QUESTION_SET}:
            raise ValueError("Invalid question set")
        return value


class CaregiverAssessmentRequest(PatientAssessmentRequest):
    patient_id: str

    @field_validator("patient_id")
    @classmethod
    def validate_patient_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Patient id is required")
        return value


#------This Function returns assessment status after login---------
@router.get("/assessment/status")
async def get_assessment_status(uid: str = Depends(get_current_user_uid)):
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return await build_assessment_status(user)


#------This Function returns the current assessment question set---------
@router.get("/assessment/questions")
async def get_assessment_questions(
    survey_type: str,
    question_set: str = PRIMARY_QUESTION_SET,
    uid: str = Depends(get_current_user_uid),
):
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    survey_type = survey_type.strip().lower()
    question_set = question_set.strip().lower()

    if survey_type == PATIENT_SURVEY and user.role != UserRole.PATIENT:
        raise HTTPException(status_code=403, detail="Only patients can access patient assessment questions")
    if survey_type == CAREGIVER_SURVEY and user.role != UserRole.CAREGIVER:
        raise HTTPException(status_code=403, detail="Only caregivers can access caregiver assessment questions")

    payload = get_question_set(survey_type, question_set)
    payload["survey_type"] = survey_type
    payload["question_set"] = question_set
    payload["threshold"] = ASSESSMENT_CONFIDENCE_THRESHOLD
    return payload


#------This Function stores the patient assessment---------
@router.post("/assessment/patient")
async def submit_patient_assessment(
    body: PatientAssessmentRequest,
    uid: str = Depends(get_current_user_uid),
):
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != UserRole.PATIENT:
        raise HTTPException(status_code=403, detail="Only patients can submit this assessment")

    normalized_answers = normalize_answers(
        PATIENT_SURVEY,
        body.question_set,
        [answer.model_dump() for answer in body.answers],
    )
    metrics = calculate_assessment_metrics(PATIENT_SURVEY, body.question_set, normalized_answers)

    assessment = PatientAssessment(
        patient_id=uid,
        answers=normalized_answers,
        score=metrics["score"],
        confidence=metrics["confidence"],
        condition_level=metrics["condition_level"],
        question_set=body.question_set,
        answered_count=metrics["answered_count"],
        skipped_count=metrics["skipped_count"],
        inconsistency_count=metrics["inconsistency_count"],
        consistency_factor=metrics["consistency_factor"],
        needs_followup=metrics["needs_followup"],
    )
    await assessment.insert()

    profile = await rebuild_patient_profile(uid)
    requires_backup = body.question_set == PRIMARY_QUESTION_SET and assessment.needs_followup

    return {
        "status": "ok",
        "assessment_id": str(assessment.id),
        "score": assessment.score,
        "confidence": assessment.confidence,
        "condition_level": assessment.condition_level,
        "requires_backup": requires_backup,
        "next_question_set": BACKUP_QUESTION_SET if requires_backup else None,
        "profile": serialize_patient_profile(profile),
    }


#------This Function stores the caregiver assessment---------
@router.post("/caregiver/assessment")
async def submit_caregiver_assessment(
    body: CaregiverAssessmentRequest,
    uid: str = Depends(get_current_user_uid),
):
    caregiver = await User.find_one(User.firebase_uid == uid)
    if not caregiver:
        raise HTTPException(status_code=404, detail="User not found")
    if caregiver.role != UserRole.CAREGIVER:
        raise HTTPException(status_code=403, detail="Only caregivers can submit this assessment")
    if body.patient_id not in caregiver.linked_patients:
        raise HTTPException(status_code=403, detail="Caregiver is not linked to this patient")

    patient = await User.find_one(User.firebase_uid == body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    normalized_answers = normalize_answers(
        CAREGIVER_SURVEY,
        body.question_set,
        [answer.model_dump() for answer in body.answers],
    )
    metrics = calculate_assessment_metrics(CAREGIVER_SURVEY, body.question_set, normalized_answers)

    assessment = CaregiverAssessment(
        patient_id=body.patient_id,
        caregiver_id=uid,
        answers=normalized_answers,
        severity_score=metrics["score"],
        confidence=metrics["confidence"],
        condition_level=metrics["condition_level"],
        question_set=body.question_set,
        answered_count=metrics["answered_count"],
        skipped_count=metrics["skipped_count"],
        inconsistency_count=metrics["inconsistency_count"],
        consistency_factor=metrics["consistency_factor"],
        needs_followup=metrics["needs_followup"],
    )
    await assessment.insert()

    profile = await rebuild_patient_profile(body.patient_id)
    requires_backup = body.question_set == PRIMARY_QUESTION_SET and assessment.needs_followup

    return {
        "status": "ok",
        "assessment_id": str(assessment.id),
        "severity_score": assessment.severity_score,
        "confidence": assessment.confidence,
        "condition_level": assessment.condition_level,
        "patient_id": body.patient_id,
        "patient_name": patient.display_name or "Linked Patient",
        "requires_backup": requires_backup,
        "next_question_set": BACKUP_QUESTION_SET if requires_backup else None,
        "profile": serialize_patient_profile(profile),
    }
