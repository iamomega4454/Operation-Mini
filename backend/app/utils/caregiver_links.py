from datetime import datetime
from typing import Optional

from app.models.user import User, UserRole


#------This Function syncs caregiver role from linked patients---------
def sync_role_from_links(user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return False

    next_role = UserRole.CAREGIVER if user.linked_patients else UserRole.PATIENT
    if user.role == next_role:
        return False

    user.role = next_role
    return True


#------This Function links invited patients for a verified caregiver email---------
async def sync_invited_links(user: User) -> bool:
    if not user.email:
        return sync_role_from_links(user)

    invited_patients = await User.find({"caregiver_emails": user.email}).to_list()
    invited_ids = sorted({patient.firebase_uid for patient in invited_patients if patient.firebase_uid})

    current_ids = sorted(set(user.linked_patients or []))
    merged_ids = sorted(set(current_ids + invited_ids))

    changed = False
    if merged_ids != current_ids:
        user.linked_patients = merged_ids
        changed = True

    if sync_role_from_links(user):
        changed = True

    return changed


#------This Function links a caregiver to a patient---------
async def link_caregiver_to_patient(patient: User, caregiver: User) -> bool:
    patient_changed = False
    caregiver_changed = False

    if caregiver.email not in patient.caregiver_emails:
        patient.caregiver_emails.append(caregiver.email)
        patient.updated_at = datetime.utcnow()
        patient_changed = True

    if patient.firebase_uid not in caregiver.linked_patients:
        caregiver.linked_patients.append(patient.firebase_uid)
        caregiver_changed = True

    if sync_role_from_links(caregiver):
        caregiver_changed = True

    if patient_changed:
        await patient.save()

    if caregiver_changed:
        caregiver.updated_at = datetime.utcnow()
        await caregiver.save()

    if patient_changed or caregiver_changed:
        from app.services.assessment_engine import rebuild_patient_profile

        await rebuild_patient_profile(patient.firebase_uid)

    return patient_changed or caregiver_changed


#------This Function removes a caregiver link from a patient---------
async def unlink_caregiver_from_patient(patient: User, caregiver_email: str) -> Optional[User]:
    patient_changed = False
    if caregiver_email in patient.caregiver_emails:
        patient.caregiver_emails.remove(caregiver_email)
        patient.updated_at = datetime.utcnow()
        await patient.save()
        patient_changed = True

    caregiver = await User.find_one(User.email == caregiver_email)
    if caregiver and patient.firebase_uid in caregiver.linked_patients:
        caregiver.linked_patients.remove(patient.firebase_uid)
        if sync_role_from_links(caregiver):
            caregiver.updated_at = datetime.utcnow()
        else:
            caregiver.updated_at = datetime.utcnow()
        await caregiver.save()

    if patient_changed or caregiver:
        from app.services.assessment_engine import rebuild_patient_profile

        await rebuild_patient_profile(patient.firebase_uid)

    return caregiver
