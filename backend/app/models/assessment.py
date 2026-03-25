from beanie import Document
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime


class AssessmentAnswer(BaseModel):
    question_id: str
    answer: Optional[str] = None
    skipped: bool = False


class PatientAssessment(Document):
    patient_id: str
    answers: List[AssessmentAnswer] = Field(default_factory=list)
    score: float = 0
    confidence: float = 0
    condition_level: str = "low"
    question_set: str = "primary"
    answered_count: int = 0
    skipped_count: int = 0
    inconsistency_count: int = 0
    consistency_factor: float = 1.0
    needs_followup: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "patient_assessment"


class CaregiverAssessment(Document):
    patient_id: str
    caregiver_id: str
    answers: List[AssessmentAnswer] = Field(default_factory=list)
    severity_score: float = 0
    confidence: float = 0
    condition_level: str = "low"
    question_set: str = "primary"
    answered_count: int = 0
    skipped_count: int = 0
    inconsistency_count: int = 0
    consistency_factor: float = 1.0
    needs_followup: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "caregiver_assessment"


class PatientProfile(Document):
    patient_id: str
    condition_level: str = "low"
    confidence_score: float = 0
    final_score: float = 0
    caregiver_count: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    legacy_preferences: Dict[str, Any] = Field(default_factory=dict)

    class Settings:
        name = "patient_profile"
