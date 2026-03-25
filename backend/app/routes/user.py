import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional, List
from app.core.firebase import get_current_user_uid
from app.models.user import User, IllnessDetails
from app.models.medication import Medication
from app.models.relative import Relative
from app.utils.caregiver_links import link_caregiver_to_patient, unlink_caregiver_from_patient
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["user"])


MAX_CONDITION_LENGTH = 200
MAX_SEVERITY_LENGTH = 50
MAX_NOTES_LENGTH = 1000


class PatientProfileUpdate(BaseModel):
    condition: Optional[str] = None
    severity: Optional[str] = None
    diagnosis_date: Optional[str] = None
    notes: Optional[str] = None

    @field_validator('condition')
    @classmethod
    def validate_condition(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > MAX_CONDITION_LENGTH:
                raise ValueError(f'Condition cannot exceed {MAX_CONDITION_LENGTH} characters')
            return v.strip()
        return v

    @field_validator('severity')
    @classmethod
    def validate_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > MAX_SEVERITY_LENGTH:
                raise ValueError(f'Severity cannot exceed {MAX_SEVERITY_LENGTH} characters')
            return v.strip()
        return v

    @field_validator('notes')
    @classmethod
    def validate_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > MAX_NOTES_LENGTH:
                raise ValueError(f'Notes cannot exceed {MAX_NOTES_LENGTH} characters')
            return v.strip()
        return v


class CaregiverAdd(BaseModel):
    email: str
    relationship: str = "family"

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Email cannot be empty')
        v = v.strip().lower()
        if '@' not in v or '.' not in v.split('@')[-1]:
            raise ValueError('Invalid email format')
        if len(v) > 255:
            raise ValueError('Email cannot exceed 255 characters')
        return v

    @field_validator('relationship')
    @classmethod
    def validate_relationship(cls, v: str) -> str:
        if v and len(v) > 50:
            raise ValueError('Relationship cannot exceed 50 characters')
        return v.strip() if v else "family"


#------This Function gets profile---------
@router.get("/profile")
async def get_profile(uid: str = Depends(get_current_user_uid)):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        
        medications = await Medication.find(Medication.patient_uid == uid).to_list()
        meds_serialized = [_serialize_medication(m) for m in medications]

        
        relatives = await Relative.find(Relative.patient_uid == uid).to_list()
        relatives_serialized = [_serialize_relative(r) for r in relatives]

        caregiver_users = await _build_caregiver_list(user)

        return {
            "user": {
                "id": str(user.id),
                "firebase_uid": user.firebase_uid,
                "email": user.email,
                "display_name": user.display_name,
                "photo_url": user.photo_url,
                "role": user.role.value,
                "is_onboarded": user.is_onboarded,
                "aura_module_ip": user.aura_module_ip,
                "preferences": user.preferences,
                "created_at": user.created_at.isoformat(),
            },
            "patient_profile": {
                "condition": user.illness.condition if user.illness else "",
                "severity": user.illness.severity if user.illness else "",
                "diagnosis_date": user.illness.diagnosis_date if user.illness else None,
                "notes": user.illness.notes if user.illness else "",
            },
            "medications": meds_serialized,
            "relatives": relatives_serialized,
            "caregivers": caregiver_users,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get profile for user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve profile")


#------This Function updates profile---------
@router.patch("/profile")
async def update_profile(
    body: PatientProfileUpdate, uid: str = Depends(get_current_user_uid)
):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        
        if user.illness is None:
            user.illness = IllnessDetails()

        updates = body.model_dump(exclude_none=True)
        for key, value in updates.items():
            setattr(user.illness, key, value)

        user.updated_at = datetime.utcnow()
        await user.save()
        logger.info(f"Updated profile for user {uid}")

        return {
            "status": "ok",
            "patient_profile": {
                "condition": user.illness.condition,
                "severity": user.illness.severity,
                "diagnosis_date": user.illness.diagnosis_date,
                "notes": user.illness.notes,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update profile for user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update profile")


#------This Function lists caregivers---------
@router.get("/caregivers")
async def list_caregivers(uid: str = Depends(get_current_user_uid)):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return await _build_caregiver_list(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list caregivers for user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve caregivers")


#------This Function adds caregiver---------
@router.post("/caregivers")
async def add_caregiver(body: CaregiverAdd, uid: str = Depends(get_current_user_uid)):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        
        caregiver = await User.find_one(User.email == body.email)
        if not caregiver:
            if body.email not in user.caregiver_emails:
                user.caregiver_emails.append(body.email)
                user.updated_at = datetime.utcnow()
                await user.save()

            logger.info(f"Stored pending caregiver invite {body.email} for user {uid}")

            return {
                "status": "ok",
                "caregiver": {
                    "id": "",
                    "email": body.email,
                    "name": "",
                    "photo_url": "",
                    "relationship": body.relationship,
                    "pending": True,
                },
            }

        await link_caregiver_to_patient(user, caregiver)

        logger.info(f"Added caregiver {body.email} for user {uid}")

        return {
            "status": "ok",
            "caregiver": {
                "id": str(caregiver.id),
                "email": caregiver.email,
                "name": caregiver.display_name,
                "photo_url": caregiver.photo_url,
                "relationship": body.relationship,
                "pending": False,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add caregiver for user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add caregiver")


#------This Function removes caregiver---------
@router.delete("/caregivers/{caregiver_email}")
async def remove_caregiver(
    caregiver_email: str, uid: str = Depends(get_current_user_uid)
):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        caregiver = await User.find_one(User.email == caregiver_email)
        has_pending_invite = caregiver_email in user.caregiver_emails
        has_active_link = bool(caregiver and uid in caregiver.linked_patients)

        if not has_pending_invite and not has_active_link:
            raise HTTPException(status_code=404, detail="Caregiver not found")

        await unlink_caregiver_from_patient(user, caregiver_email)

        logger.info(f"Removed caregiver {caregiver_email} for user {uid}")

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove caregiver for user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove caregiver")


def _serialize_medication(med: Medication) -> dict:
    return {
        "id": str(med.id),
        "name": med.name,
        "dosage": med.dosage,
        "frequency": med.frequency,
        "schedule_times": med.schedule_times,
        "notes": med.notes,
        "is_active": med.is_active,
        "last_taken": med.last_taken.isoformat() if med.last_taken else None,
        "created_at": med.created_at.isoformat(),
    }


def _serialize_relative(rel: Relative) -> dict:
    return {
        "id": str(rel.id),
        "name": rel.name,
        "relationship": rel.relationship,
        "phone": rel.phone,
        "photos": rel.photos,
        "photo_count": len(rel.photos),
        "has_embeddings": len(rel.face_embeddings) > 0,
        "notes": rel.notes,
        "created_at": rel.created_at.isoformat(),
    }


#------This Function builds caregiver list from linked users and pending invites---------
async def _build_caregiver_list(user: User) -> List[dict]:
    caregivers_by_email = {}

    linked_caregivers = await User.find(User.linked_patients == user.firebase_uid).to_list()
    for caregiver in linked_caregivers:
        caregivers_by_email[caregiver.email] = {
            "id": str(caregiver.id),
            "email": caregiver.email,
            "name": caregiver.display_name,
            "photo_url": caregiver.photo_url,
            "relationship": "caregiver",
        }

    for email in user.caregiver_emails:
        if email not in caregivers_by_email:
            caregivers_by_email[email] = {
                "id": "",
                "email": email,
                "name": "",
                "photo_url": "",
                "relationship": "caregiver",
            }

    return list(caregivers_by_email.values())
