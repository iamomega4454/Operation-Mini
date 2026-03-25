import asyncio

from app.core.database import close_db, connect_db
from app.models.assessment import PatientProfile
from app.models.user import User, UserRole
from app.services.assessment_engine import score_to_level


LEGACY_SEVERITY_SCORES = {
    "low": 2.0,
    "mild": 5.0,
    "moderate": 10.0,
    "medium": 10.0,
    "high support": 14.0,
    "high": 14.0,
    "severe": 14.0,
}


#------This Function maps a legacy severity string into a score---------
def map_legacy_severity_to_score(severity: str) -> float:
    normalized = severity.strip().lower()
    return LEGACY_SEVERITY_SCORES.get(normalized, 0.0)


#------This Function migrates legacy preference data into patient profiles---------
async def migrate_profiles() -> None:
    await connect_db()

    migrated = 0
    users = await User.find_all().to_list()
    for user in users:
        if user.role == UserRole.ADMIN:
            continue
        if not user.preferences and not (user.illness and user.illness.severity):
            continue

        profile = await PatientProfile.find_one(PatientProfile.patient_id == user.firebase_uid)
        if profile is None:
            profile = PatientProfile(patient_id=user.firebase_uid)

        changed = False
        if user.preferences and not profile.legacy_preferences:
            profile.legacy_preferences = user.preferences
            changed = True

        if profile.final_score <= 0 and user.illness and user.illness.severity:
            inferred_score = map_legacy_severity_to_score(user.illness.severity)
            if inferred_score > 0:
                profile.final_score = inferred_score
                profile.condition_level = score_to_level(inferred_score)
                profile.confidence_score = max(profile.confidence_score, 0.25)
                changed = True

        if changed:
            if profile.id:
                await profile.save()
            else:
                await profile.insert()
            migrated += 1

    await close_db()
    print(f"Migrated {migrated} patient profiles.")


if __name__ == "__main__":
    asyncio.run(migrate_profiles())
