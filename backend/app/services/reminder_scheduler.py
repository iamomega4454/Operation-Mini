import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Set, Tuple

from app.models.medication import Medication
from app.models.assessment import PatientProfile
from app.models.user import User, UserRole
from app.services.behavior_controller import get_behavior_mode
from app.services.notifications import notification_service

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
MAX_REPEAT_COUNT = 2
REPEAT_DELAY_SECONDS = 900  # 15 minutes between repeats
MAX_NOTIFICATIONS_PER_PATIENT_PER_CYCLE = 3
INTER_NOTIFICATION_DELAY = 2.0  # seconds between sends to same patient
CAREGIVER_COOLDOWN_SECONDS = 600  # 10-minute cooldown between caregiver alerts per patient
MAX_MED_NAME_LOG_LEN = 20  # truncate medication names in logs


#------This Function ensures datetime is timezone-aware UTC---------
def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert naive datetimes (e.g. from legacy DB data) to UTC-aware.
    Returns None unchanged."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


#------This Function truncates medication names for logging---------
def _short_name(name: str) -> str:
    if len(name) <= MAX_MED_NAME_LOG_LEN:
        return name
    return name[:MAX_MED_NAME_LOG_LEN - 1] + "\u2026"


class ReminderState:
    """Tracks per-medication, per-scheduled-time reminder state to prevent
    duplicates and control repeat / escalation logic."""

    def __init__(self) -> None:
        # Key: (patient_uid, medication_id, scheduled_time_str "HH:MM")
        # Value: {"last_sent_at": datetime, "repeat_count": int}
        self._entries: Dict[Tuple[str, str, str], dict] = {}

    #------This Function handles the Get Or Create Entry---------
    def get(self, patient_uid: str, med_id: str, time_str: str) -> dict:
        key = (patient_uid, med_id, time_str)
        if key not in self._entries:
            self._entries[key] = {"last_sent_at": None, "repeat_count": 0}
        return self._entries[key]

    #------This Function handles the Record Sent---------
    def record_sent(self, patient_uid: str, med_id: str, time_str: str) -> None:
        entry = self.get(patient_uid, med_id, time_str)
        entry["last_sent_at"] = datetime.now(timezone.utc)
        entry["repeat_count"] += 1

    #------This Function handles the Should Send Check---------
    def should_send(self, patient_uid: str, med_id: str, time_str: str, allow_repeat: bool) -> bool:
        entry = self.get(patient_uid, med_id, time_str)

        # Never sent for this time slot today → send
        if entry["last_sent_at"] is None:
            return True

        # Already sent; check if repeat is allowed and under limit
        if not allow_repeat:
            return False

        if entry["repeat_count"] >= MAX_REPEAT_COUNT:
            return False

        # Only repeat if enough time has elapsed since last send
        last = _ensure_utc(entry["last_sent_at"])
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        if elapsed < REPEAT_DELAY_SECONDS:
            return False

        return True

    #------This Function handles the Should Alert Caregiver---------
    def should_alert_caregiver(self, patient_uid: str, med_id: str, time_str: str, mode_alert: bool) -> bool:
        """Only alert caregiver if behavior mode says so AND repeat_count >= 2."""
        if not mode_alert:
            return False
        entry = self.get(patient_uid, med_id, time_str)
        return entry["repeat_count"] >= MAX_REPEAT_COUNT

    #------This Function handles the Reset Daily State---------
    def reset_daily(self) -> None:
        """Clear all tracked entries. Called once per day at midnight."""
        self._entries.clear()
        logger.info("[REMINDER] Daily state reset — all tracking cleared")


# Module-level state (lives for the lifetime of the server process)
_state = ReminderState()
_last_reset_date: str = ""
# Tracks last caregiver alert time per patient for cooldown
_caregiver_last_alert: Dict[str, datetime] = {}


#------This Function handles the time matching---------
def _is_time_due(schedule_time_str: str, now: datetime) -> bool:
    """Check if a schedule_time (HH:MM) matches the current minute."""
    try:
        parts = schedule_time_str.strip().split(":")
        sched_hour, sched_min = int(parts[0]), int(parts[1])
        return now.hour == sched_hour and now.minute == sched_min
    except (ValueError, IndexError):
        return False


#------This Function handles the Fetch Patient Behavior Mode---------
async def _get_patient_behavior(patient_uid: str) -> dict:
    """Fetch PatientProfile and resolve behavior mode.
    Falls back to 'mild' if profile is missing or confidence is low."""
    try:
        profile = await PatientProfile.find_one(PatientProfile.patient_id == patient_uid)
        if profile is None:
            logger.debug("[REMINDER] No PatientProfile for %s — defaulting to mild", patient_uid)
            return get_behavior_mode("mild", 1.0)
        return get_behavior_mode(profile.condition_level, profile.confidence_score)
    except Exception as exc:
        logger.warning("[REMINDER] Error fetching profile for %s: %s — defaulting to mild", patient_uid, exc)
        return get_behavior_mode("mild", 1.0)


#------This Function handles the Caregiver Alert---------
async def _alert_caregivers(patient_uid: str, medication_name: str) -> None:
    """Send a notification to all caregivers linked to this patient."""
    try:
        caregivers = await User.find(
            User.role == UserRole.CAREGIVER,
            User.linked_patients == patient_uid,
        ).to_list()

        if not caregivers:
            logger.info("[REMINDER] No caregivers found for patient %s", patient_uid)
            return

        for cg in caregivers:
            sent = await notification_service.send_notification_to_user(
                user_uid=cg.firebase_uid,
                title="⚠️ Medication Not Taken",
                body=f"Your patient has not taken {medication_name} after repeated reminders.",
                data={
                    "type": "medication_escalation",
                    "patient_uid": patient_uid,
                },
            )
            if sent > 0:
                logger.info(
                    "[REMINDER] Caregiver alert triggered — caregiver=%s, patient=%s, med=%s",
                    cg.firebase_uid, patient_uid, medication_name,
                )
    except Exception as exc:
        logger.error("[REMINDER] Failed to alert caregivers for %s: %s", patient_uid, exc)


#------This Function handles the Single Check Cycle---------
async def _check_and_send_reminders() -> None:
    """One cycle: find due medications, apply behavior rules, send notifications."""
    global _last_reset_date

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    # Daily state reset at midnight
    if _last_reset_date != today_str:
        _state.reset_daily()
        _caregiver_last_alert.clear()
        _last_reset_date = today_str

    # Query all active medications
    try:
        medications = await Medication.find(Medication.is_active == True).to_list()
    except Exception as exc:
        logger.error("[REMINDER] Failed to query medications: %s", exc)
        return

    if not medications:
        return

    # --- Step 1: Collect all due candidates ---
    candidates = []  # list of (patient_uid, med, time_str, mode)
    for med in medications:
        if not med.schedule_times:
            continue
        med_id = str(med.id)
        patient_uid = med.patient_uid
        for time_str in med.schedule_times:
            if not _is_time_due(time_str, now):
                continue
            mode = await _get_patient_behavior(patient_uid)
            allow_repeat = mode.get("repeat", False)
            if not _state.should_send(patient_uid, med_id, time_str, allow_repeat):
                continue
            candidates.append((patient_uid, med, time_str, mode))

    if not candidates:
        return

    # --- Step 2: Sort by oldest last_sent_at for fairness (never-sent first) ---
    def _sort_key(item: tuple) -> float:
        entry = _state.get(item[0], str(item[1].id), item[2])
        last = entry["last_sent_at"]
        return last.timestamp() if last else 0.0

    candidates.sort(key=_sort_key)

    # --- Step 3: Process with per-patient burst cap ---
    patient_send_count: Dict[str, int] = {}
    caregiver_alerted_this_cycle: Set[str] = set()
    _cooldown_logged_this_cycle: Set[str] = set()
    total_sent = 0
    total_skipped = 0

    for patient_uid, med, time_str, mode in candidates:
        med_id = str(med.id)
        sends = patient_send_count.get(patient_uid, 0)

        if sends >= MAX_NOTIFICATIONS_PER_PATIENT_PER_CYCLE:
            total_skipped += 1
            continue

        # Inter-notification delay (only between sends to same patient)
        if sends > 0:
            await asyncio.sleep(INTER_NOTIFICATION_DELAY)

        # Send the reminder
        try:
            await notification_service.send_medication_reminder(
                patient_uid=patient_uid,
                medication_name=med.name,
                medication_id=med_id,
            )
            current_repeat = _state.get(patient_uid, med_id, time_str)["repeat_count"]
            _state.record_sent(patient_uid, med_id, time_str)
            patient_send_count[patient_uid] = sends + 1
            total_sent += 1

            logger.info(
                "[REMINDER] Sent reminder — patient=%s, med=%s, level=%s, send=%d/%d",
                patient_uid, _short_name(med.name), mode.get("urgency", "?"),
                current_repeat + 1, MAX_REPEAT_COUNT + 1,
            )
        except Exception as exc:
            logger.error("[REMINDER] Failed to send reminder for %s/%s: %s", patient_uid, med.name, exc)
            continue

        # Caregiver escalation: per-cycle dedup + 10-minute cooldown
        if (
            patient_uid not in caregiver_alerted_this_cycle
            and _state.should_alert_caregiver(patient_uid, med_id, time_str, mode.get("alert_caregiver", False))
        ):
            last_alert = _ensure_utc(_caregiver_last_alert.get(patient_uid))
            if last_alert is None or (now - last_alert).total_seconds() >= CAREGIVER_COOLDOWN_SECONDS:
                caregiver_alerted_this_cycle.add(patient_uid)
                _caregiver_last_alert[patient_uid] = now
                logger.info(
                    "[REMINDER] Caregiver alert triggered — patient=%s, med=%s",
                    patient_uid, _short_name(med.name),
                )
                await _alert_caregivers(patient_uid, med.name)
            elif patient_uid not in _cooldown_logged_this_cycle:
                # Log cooldown only once per patient per cycle to reduce noise
                _cooldown_logged_this_cycle.add(patient_uid)
                logger.debug(
                    "[REMINDER] Caregiver cooldown active — patient=%s (%.0fs remaining)",
                    patient_uid, CAREGIVER_COOLDOWN_SECONDS - (now - last_alert).total_seconds(),
                )

    # --- Step 4: Cycle summary ---
    if total_sent > 0 or total_skipped > 0:
        logger.info(
            "[REMINDER] Cycle complete — sent=%d, skipped=%d (burst-capped), patients=%d",
            total_sent, total_skipped, len(patient_send_count),
        )
        # Aggregated burst-skip summary (one line per affected patient)
        if total_skipped > 0:
            skip_by_patient: Dict[str, int] = {}
            for p, m, _, _ in candidates:
                if patient_send_count.get(p, 0) >= MAX_NOTIFICATIONS_PER_PATIENT_PER_CYCLE:
                    skip_by_patient[p] = skip_by_patient.get(p, 0) + 1
            for pid, skipped in skip_by_patient.items():
                logger.debug(
                    "[REMINDER] Skipped %d med(s) due to cap — patient=%s",
                    skipped, pid,
                )
        # Per-patient debug breakdown (once per cycle)
        for pid, count in patient_send_count.items():
            alerted = 1 if pid in caregiver_alerted_this_cycle else 0
            logger.debug(
                "[REMINDER] patient=%s sent=%d alerts=%d",
                pid, count, alerted,
            )


#------This Function handles the Main Reminder Loop---------
async def reminder_check_loop() -> None:
    """Background asyncio loop that checks reminders every CHECK_INTERVAL_SECONDS.
    Follows the same pattern as cleanup_task.py."""
    logger.info("[REMINDER] Reminder scheduler started (interval=%ds)", CHECK_INTERVAL_SECONDS)

    while True:
        cycle_start = asyncio.get_event_loop().time()

        try:
            await _check_and_send_reminders()
        except asyncio.CancelledError:
            logger.info("[REMINDER] Reminder scheduler cancelled")
            break
        except Exception as exc:
            logger.error("[REMINDER] Unexpected error in reminder loop: %s", exc, exc_info=True)

        elapsed = asyncio.get_event_loop().time() - cycle_start
        sleep_for = max(0, CHECK_INTERVAL_SECONDS - elapsed)

        if elapsed > CHECK_INTERVAL_SECONDS:
            logger.warning(
                "[REMINDER] Cycle took %.1fs (> %ds interval) — next cycle starts immediately",
                elapsed, CHECK_INTERVAL_SECONDS,
            )

        try:
            await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            logger.info("[REMINDER] Reminder scheduler cancelled during sleep")
            break

