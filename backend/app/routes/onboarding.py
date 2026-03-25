from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.core.firebase import get_current_user_uid
from app.models.user import User, IllnessDetails, UserRole
from app.models.medication import Medication
from app.utils.caregiver_links import link_caregiver_to_patient
from datetime import datetime

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class IllnessRequest(BaseModel):
    condition: str
    severity: str = ""
    diagnosis_date: Optional[str] = None
    notes: str = ""


class MedicationRequest(BaseModel):
    name: str
    dosage: str = ""
    frequency: str = ""
    schedule_times: List[str] = []
    notes: str = ""


class CaregiverRequest(BaseModel):
    email: str


class CaregiverIntakeRequest(BaseModel):
    patient_uid: Optional[str] = None
    condition: str
    severity: str
    diagnosis_date: Optional[str] = None
    notes: str = ""
    medications: List[MedicationRequest] = []


#------This Function updates illness---------
@router.put("/illness")
async def update_illness(
    body: IllnessRequest,
    patient_uid: Optional[str] = None,
    uid: str = Depends(get_current_user_uid),
):
    requester = await User.find_one(User.firebase_uid == uid)
    if not requester:
        raise HTTPException(status_code=404, detail="User not found")

    target_uid = patient_uid or uid
    if requester.role == UserRole.CAREGIVER and patient_uid:
        if patient_uid not in requester.linked_patients:
            raise HTTPException(status_code=403, detail="Access denied")
    elif uid != target_uid and requester.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    target_user = await User.find_one(User.firebase_uid == target_uid)
    if not target_user:
        raise HTTPException(status_code=404, detail="Patient not found")

    target_user.illness = IllnessDetails(**body.model_dump())
    target_user.updated_at = datetime.utcnow()
    await target_user.save()
    return {"status": "ok"}


#------This Function adds initial medications---------
@router.post("/medications")
async def add_initial_medications(
    meds: List[MedicationRequest],
    patient_uid: Optional[str] = None,
    uid: str = Depends(get_current_user_uid),
):
    requester = await User.find_one(User.firebase_uid == uid)
    if not requester:
        raise HTTPException(status_code=404, detail="User not found")

    target_uid = patient_uid or uid
    if requester.role == UserRole.CAREGIVER and patient_uid:
        if patient_uid not in requester.linked_patients:
            raise HTTPException(status_code=403, detail="Access denied")
    elif uid != target_uid and requester.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    created = []
    for m in meds:
        med = Medication(patient_uid=target_uid, **m.model_dump())
        await med.insert()
        created.append(str(med.id))
    return {"status": "ok", "medication_ids": created}


#------This Function adds caregiver---------
@router.post("/caregiver")
async def add_caregiver(body: CaregiverRequest, uid: str = Depends(get_current_user_uid)):
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email not in user.caregiver_emails:
        user.caregiver_emails.append(body.email)
        user.updated_at = datetime.utcnow()
        await user.save()

    existing_cg = await User.find_one(User.email == body.email)
    if existing_cg:
        await link_caregiver_to_patient(user, existing_cg)

    return {"status": "ok"}


class PreferencesRequest(BaseModel):
    hobbies: List[str] = []
    important_people: str = ""
    daily_routine: str = ""
    time_preference: str = ""
    music_genres: List[str] = []
    has_pets: str = ""
    favorite_food: str = ""
    communication_style: str = ""
    health_notes: str = ""
    dietary_notes: str = ""
    wellness_habits: str = ""
    extra_notes: str = ""


#------This Function updates preferences---------
@router.put("/preferences")
async def update_preferences(body: PreferencesRequest, uid: str = Depends(get_current_user_uid)):
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.preferences = body.model_dump()
    user.updated_at = datetime.utcnow()
    await user.save()
    return {"status": "ok"}


#------This Function completes onboarding---------
@router.put("/complete")
async def complete_onboarding(uid: str = Depends(get_current_user_uid)):
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_onboarded = True
    user.updated_at = datetime.utcnow()
    await user.save()
    return {"status": "ok"}


#------This Function completes caregiver intake---------
@router.put("/caregiver-intake")
async def complete_caregiver_intake(
    body: CaregiverIntakeRequest,
    uid: str = Depends(get_current_user_uid),
):
    caregiver = await User.find_one(User.firebase_uid == uid)
    if not caregiver:
        raise HTTPException(status_code=404, detail="User not found")
    if caregiver.role != UserRole.CAREGIVER:
        raise HTTPException(status_code=403, detail="Only caregivers can submit caregiver intake")

    target_uid = body.patient_uid
    if not target_uid:
        if not caregiver.linked_patients:
            raise HTTPException(status_code=400, detail="No linked patient found")
        target_uid = caregiver.linked_patients[0]

    if target_uid not in caregiver.linked_patients:
        raise HTTPException(status_code=403, detail="Access denied")

    patient = await User.find_one(User.firebase_uid == target_uid)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient.illness = IllnessDetails(
        condition=body.condition,
        severity=body.severity,
        diagnosis_date=body.diagnosis_date,
        notes=body.notes,
    )
    patient.updated_at = datetime.utcnow()
    await patient.save()

    for med in body.medications:
        if med.name.strip():
            medication = Medication(patient_uid=target_uid, **med.model_dump())
            await medication.insert()

    caregiver.is_onboarded = True
    caregiver.updated_at = datetime.utcnow()
    await caregiver.save()

    return {"status": "ok", "patient_uid": target_uid}
