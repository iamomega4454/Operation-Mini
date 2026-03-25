import logging
import httpx
from typing import Any, Dict
from datetime import datetime

from app.models.user import User, UserRole
from app.models.journal import JournalEntry
from app.models.medication import Medication
from app.models.reminder import Reminder, ReminderStatus
from app.models.relative import Relative
from app.models.sos import SOSEvent
from app.models.suggestion import Suggestion
from app.services.notifications import notification_service
from app.utils.caregiver_links import link_caregiver_to_patient, unlink_caregiver_from_patient

logger = logging.getLogger(__name__)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "Get the user's full profile: name, age, medical condition, diagnosis date, severity, notes. Use this early in conversations to personalize interactions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_context",
            "description": "Get comprehensive user context including profile, medications, relatives, and recent interactions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": "Update core medical profile fields like condition, severity, diagnosis date, and notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string", "description": "Medical condition name"},
                    "severity": {"type": "string", "description": "Condition severity"},
                    "diagnosis_date": {"type": "string", "description": "Diagnosis date"},
                    "notes": {"type": "string", "description": "Additional medical notes"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_account_profile",
            "description": "Update account details such as display name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "display_name": {"type": "string", "description": "Updated display name"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_journal_entries",
            "description": "Read recent journal entries to remember conversations and events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of entries to retrieve (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_journal",
            "description": "Search for specific events, people, or topics in journal memories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_memory_entry",
            "description": "Save a new memory or journal entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Memory content to save"},
                    "mood": {"type": "string", "description": "Optional mood tag"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory_entry",
            "description": "Edit an existing memory entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "content": {"type": "string"},
                    "mood": {"type": "string"},
                },
                "required": ["entry_id", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory_entry",
            "description": "Remove an incorrect or outdated memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_medications",
            "description": "Check current medications, dosages, and schedules. ALWAYS check this when medications are mentioned.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_medication",
            "description": "Add a new medication.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dosage": {"type": "string"},
                    "frequency": {"type": "string"},
                    "schedule_times": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_medication",
            "description": "Modify existing medication details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "medication_id": {"type": "string"},
                    "name": {"type": "string"},
                    "dosage": {"type": "string"},
                    "frequency": {"type": "string"},
                    "schedule_times": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["medication_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_medication",
            "description": "Remove a medication.",
            "parameters": {
                "type": "object",
                "properties": {"medication_id": {"type": "string"}},
                "required": ["medication_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_medication_taken",
            "description": "Mark a medication dose as taken right now.",
            "parameters": {
                "type": "object",
                "properties": {"medication_id": {"type": "string"}},
                "required": ["medication_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder that shows in the app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "datetime": {"type": "string", "description": "ISO 8601 datetime string"},
                    "repeat": {"type": "string", "description": "Repeat pattern (daily, weekly, etc.)"},
                },
                "required": ["title", "datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reminders",
            "description": "List all reminders, optionally filter by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: active, completed, or all"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_reminder",
            "description": "Modify a reminder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "datetime": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Remove a reminder.",
            "parameters": {
                "type": "object",
                "properties": {"reminder_id": {"type": "string"}},
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_reminder",
            "description": "Mark a reminder as completed.",
            "parameters": {
                "type": "object",
                "properties": {"reminder_id": {"type": "string"}},
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relatives",
            "description": "List all family members/relatives with contact info.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_relative",
            "description": "Add a new relative/family member.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "relationship": {"type": "string"},
                    "phone": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_relative",
            "description": "Update relative details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_id": {"type": "string"},
                    "name": {"type": "string"},
                    "relationship": {"type": "string"},
                    "phone": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["relative_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_relative",
            "description": "Remove a relative by ID.",
            "parameters": {
                "type": "object",
                "properties": {"relative_id": {"type": "string"}},
                "required": ["relative_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_relative",
            "description": "Call a family member using their phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_name": {"type": "string", "description": "Name of the relative to call"},
                },
                "required": ["relative_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "identify_person_from_relatives",
            "description": "Use the Aura camera to identify a person and match against the relatives list.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_caregivers",
            "description": "Get list of caregivers with contact info.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_caregiver",
            "description": "Add a new caregiver by their email address.",
            "parameters": {
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_caregiver",
            "description": "Remove caregiver access by email.",
            "parameters": {
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_sos",
            "description": "Send emergency SOS alert to caregivers. ONLY for real emergencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Emergency level 1-5"},
                    "trigger": {"type": "string", "description": "Trigger type: button, voice, or auto"},
                    "message": {"type": "string", "description": "SOS message"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_sos",
            "description": "Check for any active SOS alerts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_sos_alert",
            "description": "Resolve an active SOS alert.",
            "parameters": {
                "type": "object",
                "properties": {"sos_id": {"type": "string"}},
                "required": ["sos_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_internet",
            "description": "Search the web for current information, news, or facts.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wikipedia",
            "description": "Get information from Wikipedia about a topic.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Perform a mathematical calculation.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Math expression to evaluate"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aura_status",
            "description": "Check if the Aura module (camera/microphone device) is connected.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aura_live_context",
            "description": "Fetch live Aura context including latest transcript, snapshot URL, and video feed URL.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_location",
            "description": "Get the patient's latest known location.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_suggestions",
            "description": "Get daily activity and wellness suggestions for the patient.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_steps",
            "description": "Get the patient's step count and activity data.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


#------This Function executes a tool call by name---------
async def execute_tool(name: str, args: Dict[str, Any], uid: str, aura_module_ip: str = "") -> str:
    try:
        return await _dispatch(name, args, uid, aura_module_ip)
    except Exception as e:
        logger.error(f"[AgentTools] Tool '{name}' failed: {e}", exc_info=True)
        return f"Tool '{name}' encountered an error: {str(e)}"


#------This Function dispatches to the right tool implementation---------
async def _dispatch(name: str, args: Dict[str, Any], uid: str, aura_module_ip: str) -> str:
    if name == "get_user_profile":
        return await _get_user_profile(uid)
    if name == "get_user_context":
        return await _get_user_context(uid)
    if name == "update_user_profile":
        return await _update_user_profile(uid, args)
    if name == "update_account_profile":
        return await _update_account_profile(uid, args)
    if name == "get_journal_entries":
        return await _get_journal_entries(uid, args.get("limit", 10))
    if name == "search_journal":
        return await _search_journal(uid, args.get("query", ""))
    if name == "add_memory_entry":
        return await _add_memory_entry(uid, args)
    if name == "update_memory_entry":
        return await _update_memory_entry(uid, args)
    if name == "delete_memory_entry":
        return await _delete_memory_entry(uid, args.get("entry_id", ""))
    if name == "get_medications":
        return await _get_medications(uid)
    if name == "add_medication":
        return await _add_medication(uid, args)
    if name == "update_medication":
        return await _update_medication(uid, args)
    if name == "delete_medication":
        return await _delete_medication(uid, args.get("medication_id", ""))
    if name == "mark_medication_taken":
        return await _mark_medication_taken(uid, args.get("medication_id", ""))
    if name == "create_reminder":
        return await _create_reminder(uid, args)
    if name == "get_reminders":
        return await _get_reminders(uid, args.get("status", "active"))
    if name == "update_reminder":
        return await _update_reminder(uid, args)
    if name == "delete_reminder":
        return await _delete_reminder(uid, args.get("reminder_id", ""))
    if name == "complete_reminder":
        return await _complete_reminder(uid, args.get("reminder_id", ""))
    if name == "get_relatives":
        return await _get_relatives(uid)
    if name == "add_relative":
        return await _add_relative(uid, args)
    if name == "update_relative":
        return await _update_relative(uid, args)
    if name == "delete_relative":
        return await _delete_relative(uid, args.get("relative_id", ""))
    if name == "call_relative":
        return await _call_relative(uid, args.get("relative_name", ""))
    if name == "identify_person_from_relatives":
        return await _identify_person(uid, aura_module_ip)
    if name == "get_caregivers":
        return await _get_caregivers(uid)
    if name == "add_caregiver":
        return await _add_caregiver(uid, args.get("email", ""))
    if name == "remove_caregiver":
        return await _remove_caregiver(uid, args.get("email", ""))
    if name == "trigger_sos":
        return await _trigger_sos(uid, args)
    if name == "get_active_sos":
        return await _get_active_sos(uid)
    if name == "resolve_sos_alert":
        return await _resolve_sos(uid, args.get("sos_id", ""))
    if name == "search_internet":
        return await _search_internet(args.get("query", ""))
    if name == "search_wikipedia":
        return await _search_wikipedia(args.get("query", ""))
    if name == "calculate":
        return _calculate(args.get("expression", ""))
    if name == "get_aura_status":
        return await _get_aura_status(uid, aura_module_ip)
    if name == "get_aura_live_context":
        return await _get_aura_live_context(uid, aura_module_ip)
    if name == "get_current_location":
        return await _get_current_location(uid)
    if name == "get_suggestions":
        return await _get_suggestions(uid)
    if name == "get_steps":
        return await _get_steps(uid)
    return f"Unknown tool: {name}"


# ─── User Profile ───────────────────────────────────────────────────────────

async def _get_user_profile(uid: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User profile not found."
    illness = user.illness
    lines = [
        "User Profile:",
        f"Name: {user.display_name or 'Unknown'}",
        f"Email: {user.email}",
    ]
    if illness:
        lines += [
            f"Medical Condition: {illness.condition or 'Unknown'}",
            f"Severity: {illness.severity or 'Unknown'}",
            f"Diagnosed: {illness.diagnosis_date or 'Unknown'}",
            f"Notes: {illness.notes or 'None'}",
        ]
    if user.preferences:
        lines.append(f"Preferences: {user.preferences}")
    return "\n".join(lines)


async def _get_user_context(uid: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    meds = await Medication.find(Medication.patient_uid == uid, Medication.is_active == True).to_list()
    relatives = await Relative.find(Relative.patient_uid == uid).to_list()
    illness = user.illness
    lines = [f"User Context for {user.display_name or user.email}:"]
    if illness:
        lines.append(f"Condition: {illness.condition} ({illness.severity})")
    if meds:
        med_list = ", ".join(f"{m.name} {m.dosage}" for m in meds)
        lines.append(f"Medications: {med_list}")
    if relatives:
        rel_list = ", ".join(f"{r.name} ({r.relationship})" for r in relatives)
        lines.append(f"Relatives: {rel_list}")
    return "\n".join(lines)


async def _update_user_profile(uid: str, args: Dict[str, Any]) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    from app.models.user import IllnessDetails
    if user.illness is None:
        user.illness = IllnessDetails()
    if "condition" in args:
        user.illness.condition = args["condition"]
    if "severity" in args:
        user.illness.severity = args["severity"]
    if "diagnosis_date" in args:
        user.illness.diagnosis_date = args["diagnosis_date"]
    if "notes" in args:
        user.illness.notes = args["notes"]
    user.updated_at = datetime.utcnow()
    await user.save()
    return "Medical profile updated successfully."


async def _update_account_profile(uid: str, args: Dict[str, Any]) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    if "display_name" in args:
        user.display_name = args["display_name"]
    user.updated_at = datetime.utcnow()
    await user.save()
    return "Account profile updated successfully."


# ─── Journal ────────────────────────────────────────────────────────────────

async def _get_journal_entries(uid: str, limit: int = 10) -> str:
    entries = await JournalEntry.find(
        JournalEntry.patient_uid == uid
    ).sort("-created_at").limit(limit).to_list()
    if not entries:
        return "No journal entries found."
    return "\n\n".join(
        f"[{e.created_at.strftime('%Y-%m-%d')}] {e.content[:300]}"
        for e in entries
    )


async def _search_journal(uid: str, query: str) -> str:
    entries = await JournalEntry.find(
        JournalEntry.patient_uid == uid
    ).sort("-created_at").to_list()
    q = query.lower()
    matches = [e for e in entries if q in e.content.lower()][:5]
    if not matches:
        return f"No journal entries found matching '{query}'."
    return "\n".join(f"[{e.created_at.strftime('%Y-%m-%d')}] {e.content[:200]}" for e in matches)


async def _add_memory_entry(uid: str, args: Dict[str, Any]) -> str:
    entry = JournalEntry(
        patient_uid=uid,
        content=args.get("content", ""),
        mood=args.get("mood", ""),
        source="ai_generated",
    )
    await entry.insert()
    return "Memory saved successfully."


async def _update_memory_entry(uid: str, args: Dict[str, Any]) -> str:
    entry = await JournalEntry.get(args["entry_id"])
    if not entry or entry.patient_uid != uid:
        return "Journal entry not found."
    entry.content = args.get("content", entry.content)
    if "mood" in args:
        entry.mood = args["mood"]
    await entry.save()
    return "Memory updated successfully."


async def _delete_memory_entry(uid: str, entry_id: str) -> str:
    entry = await JournalEntry.get(entry_id)
    if not entry or entry.patient_uid != uid:
        return "Journal entry not found."
    await entry.delete()
    return "Memory deleted successfully."


# ─── Medications ────────────────────────────────────────────────────────────

async def _get_medications(uid: str) -> str:
    meds = await Medication.find(Medication.patient_uid == uid).to_list()
    if not meds:
        return "No medications found."
    return "\n".join(
        f"• [{str(m.id)}] {m.name} — {m.dosage} ({m.frequency}) at {', '.join(m.schedule_times) or 'no schedule'}"
        + ("" if m.is_active else " [INACTIVE]")
        for m in meds
    )


async def _add_medication(uid: str, args: Dict[str, Any]) -> str:
    med = Medication(
        patient_uid=uid,
        name=args.get("name", ""),
        dosage=args.get("dosage", ""),
        frequency=args.get("frequency", ""),
        schedule_times=args.get("schedule_times", []),
        notes=args.get("notes", ""),
    )
    await med.insert()
    return f"Medication '{med.name}' added successfully (ID: {med.id})."


async def _update_medication(uid: str, args: Dict[str, Any]) -> str:
    med = await Medication.get(args["medication_id"])
    if not med or med.patient_uid != uid:
        return "Medication not found."
    for field in ["name", "dosage", "frequency", "schedule_times", "notes"]:
        if field in args:
            setattr(med, field, args[field])
    await med.save()
    return f"Medication '{med.name}' updated successfully."


async def _delete_medication(uid: str, med_id: str) -> str:
    med = await Medication.get(med_id)
    if not med or med.patient_uid != uid:
        return "Medication not found."
    await med.delete()
    return "Medication deleted."


async def _mark_medication_taken(uid: str, med_id: str) -> str:
    med = await Medication.get(med_id)
    if not med or med.patient_uid != uid:
        return "Medication not found."
    med.last_taken = datetime.utcnow()
    await med.save()
    return f"Marked '{med.name}' as taken at {med.last_taken.strftime('%H:%M')}."


# ─── Reminders ──────────────────────────────────────────────────────────────

async def _create_reminder(uid: str, args: Dict[str, Any]) -> str:
    try:
        dt_str = args.get("datetime", "")
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.utcnow()
        reminder = Reminder(
            patient_uid=uid,
            title=args.get("title", "Reminder"),
            description=args.get("description", ""),
            datetime=dt,
            repeat_pattern=args.get("repeat"),
            created_by="orito",
            source="ai_generated",
        )
        await reminder.insert()
        return f"Reminder '{reminder.title}' created for {dt.strftime('%Y-%m-%d %H:%M')}."
    except Exception as e:
        return f"Could not create reminder: {e}"


async def _get_reminders(uid: str, status_filter: str = "active") -> str:
    query = Reminder.find(Reminder.patient_uid == uid)
    if status_filter == "active":
        query = query.find(Reminder.status == ReminderStatus.ACTIVE.value)
    elif status_filter == "completed":
        query = query.find(Reminder.status == ReminderStatus.COMPLETED.value)
    reminders = await query.sort("datetime").to_list()
    if not reminders:
        return "No reminders found."
    return "\n".join(
        f"• [{str(r.id)}] {r.title} — {r.datetime.strftime('%Y-%m-%d %H:%M')} [{r.status}]"
        for r in reminders
    )


async def _update_reminder(uid: str, args: Dict[str, Any]) -> str:
    reminder = await Reminder.get(args["reminder_id"])
    if not reminder or reminder.patient_uid != uid:
        return "Reminder not found."
    for field in ["title", "description", "status"]:
        if field in args:
            setattr(reminder, field, args[field])
    if "datetime" in args:
        try:
            reminder.datetime = datetime.fromisoformat(args["datetime"].replace("Z", "+00:00"))
        except Exception:
            pass
    reminder.updated_at = datetime.utcnow()
    await reminder.save()
    return f"Reminder '{reminder.title}' updated."


async def _delete_reminder(uid: str, reminder_id: str) -> str:
    reminder = await Reminder.get(reminder_id)
    if not reminder or reminder.patient_uid != uid:
        return "Reminder not found."
    await reminder.delete()
    return "Reminder deleted."


async def _complete_reminder(uid: str, reminder_id: str) -> str:
    reminder = await Reminder.get(reminder_id)
    if not reminder or reminder.patient_uid != uid:
        return "Reminder not found."
    reminder.status = ReminderStatus.COMPLETED.value
    reminder.updated_at = datetime.utcnow()
    await reminder.save()
    return f"Reminder '{reminder.title}' marked as completed."


# ─── Relatives ──────────────────────────────────────────────────────────────

async def _get_relatives(uid: str) -> str:
    relatives = await Relative.find(Relative.patient_uid == uid).to_list()
    if not relatives:
        return "No relatives found."
    return "\n".join(
        f"• [{str(r.id)}] {r.name} ({r.relationship}) — {r.phone or 'no phone'}"
        + (f" — {r.notes}" if r.notes else "")
        for r in relatives
    )


async def _add_relative(uid: str, args: Dict[str, Any]) -> str:
    rel = Relative(
        patient_uid=uid,
        name=args.get("name", ""),
        relationship=args.get("relationship", ""),
        phone=args.get("phone", ""),
        notes=args.get("notes", ""),
    )
    await rel.insert()
    return f"Relative '{rel.name}' ({rel.relationship}) added successfully (ID: {rel.id})."


async def _update_relative(uid: str, args: Dict[str, Any]) -> str:
    rel = await Relative.get(args["relative_id"])
    if not rel or rel.patient_uid != uid:
        return "Relative not found."
    for field in ["name", "relationship", "phone", "notes"]:
        if field in args:
            setattr(rel, field, args[field])
    await rel.save()
    return f"Relative '{rel.name}' updated."


async def _delete_relative(uid: str, rel_id: str) -> str:
    rel = await Relative.get(rel_id)
    if not rel or rel.patient_uid != uid:
        return "Relative not found."
    await rel.delete()
    return "Relative removed."


async def _call_relative(uid: str, relative_name: str) -> str:
    relatives = await Relative.find(Relative.patient_uid == uid).to_list()
    match = next(
        (r for r in relatives if relative_name.lower() in r.name.lower()),
        None
    )
    if not match:
        return f"Could not find '{relative_name}' in relatives list. Please check the name."
    if not match.phone:
        return f"{match.name} ({match.relationship}) does not have a phone number saved."
    return f"CALL_ACTION:{match.phone}|Calling {match.name} ({match.relationship}) at {match.phone}."


async def _identify_person(uid: str, aura_module_ip: str) -> str:
    if not aura_module_ip:
        user = await User.find_one(User.firebase_uid == uid)
        aura_module_ip = user.aura_module_ip if user else ""
    if not aura_module_ip:
        return "Aura module not connected. Cannot perform face recognition."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"http://{aura_module_ip}:8001/recognize",
                json={"uid": uid},
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("identifiedFaces"):
                faces = data["identifiedFaces"]
                results = [
                    f"{f['person_name']} (confidence: {f['confidence']:.0%})"
                    for f in faces if f.get("confidence", 0) >= 0.6
                ]
                return f"Face recognition result: {', '.join(results)}" if results else "Faces detected but confidence too low."
            return data.get("error", "No faces recognized.")
        return "Aura module returned an error during face recognition."
    except Exception as e:
        return f"Face recognition failed: {e}"


# ─── Caregivers ─────────────────────────────────────────────────────────────

async def _get_caregivers(uid: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    if not user.caregiver_emails:
        return "No caregivers found."
    caregivers = await User.find(User.email.in_(user.caregiver_emails)).to_list()
    if not caregivers:
        return f"Caregiver emails: {', '.join(user.caregiver_emails)}"
    return "\n".join(f"• {c.display_name or c.email} ({c.email})" for c in caregivers)


async def _add_caregiver(uid: str, email: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    caregiver = await User.find_one(User.email == email)
    if not caregiver:
        if email not in user.caregiver_emails:
            user.caregiver_emails.append(email)
            user.updated_at = datetime.utcnow()
            await user.save()
        return f"Caregiver invite for '{email}' saved. Their role will sync after they register."
    await link_caregiver_to_patient(user, caregiver)
    return f"Caregiver '{caregiver.display_name or email}' added successfully."


async def _remove_caregiver(uid: str, email: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    await unlink_caregiver_from_patient(user, email)
    return f"Caregiver '{email}' removed."


# ─── SOS ────────────────────────────────────────────────────────────────────

async def _trigger_sos(uid: str, args: Dict[str, Any]) -> str:
    patient = await User.find_one(User.firebase_uid == uid)
    if not patient:
        return "User not found."
    event = SOSEvent(
        patient_uid=uid,
        level=args.get("level", 3),
        trigger=args.get("trigger", "auto"),
        message=args.get("message", "SOS triggered by Orito AI"),
        location=patient.last_location,
    )
    await event.insert()
    caregivers = await User.find(
        User.role == UserRole.CAREGIVER,
        User.linked_patients == uid,
    ).to_list()
    notified = 0
    for cg in caregivers:
        cnt = await notification_service.send_sos_notification(
            caregiver_uid=cg.firebase_uid,
            patient_name=patient.display_name or "Patient",
            patient_uid=uid,
            sos_id=str(event.id),
            location=patient.last_location,
        )
        notified += cnt
    return f"SOS triggered! Alert sent to {len(caregivers)} caregiver(s). Notifications: {notified}."


async def _get_active_sos(uid: str) -> str:
    events = await SOSEvent.find(
        SOSEvent.patient_uid == uid,
        SOSEvent.resolved == False,
    ).sort("-created_at").to_list()
    if not events:
        return "No active SOS alerts."
    return "\n".join(
        f"• [{str(e.id)}] Level {e.level} — {e.message} ({e.created_at.strftime('%Y-%m-%d %H:%M')})"
        for e in events
    )


async def _resolve_sos(uid: str, sos_id: str) -> str:
    event = await SOSEvent.get(sos_id)
    if not event or event.patient_uid != uid:
        return "SOS event not found."
    event.resolved = True
    event.resolved_at = datetime.utcnow()
    await event.save()
    return "SOS alert resolved."


# ─── Web / Wikipedia / Calculator ───────────────────────────────────────────

async def _search_internet(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": "AuraBot/1.0"},
            )
        data = resp.json()
        abstract = data.get("AbstractText", "")
        if abstract:
            return f"Search result for '{query}': {abstract}"
        related = [r.get("Text", "") for r in data.get("RelatedTopics", [])[:3] if r.get("Text")]
        if related:
            return f"Search results for '{query}':\n" + "\n".join(f"• {t}" for t in related)
        return f"No results found for '{query}'."
    except Exception as e:
        return f"Search failed: {e}"


async def _search_wikipedia(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + query.replace(" ", "_"),
                headers={"User-Agent": "AuraBot/1.0"},
            )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("extract", "No Wikipedia article found.")[:500]
        return f"Wikipedia: article not found for '{query}'."
    except Exception as e:
        return f"Wikipedia search failed: {e}"


def _calculate(expression: str) -> str:
    import ast
    import operator
    ops = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.Mod: operator.mod,
    }
    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return ops[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported expression")
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Calculation error: {e}"


# ─── Aura Module ────────────────────────────────────────────────────────────

async def _get_aura_ip(uid: str, aura_module_ip: str) -> str:
    if aura_module_ip:
        return aura_module_ip
    user = await User.find_one(User.firebase_uid == uid)
    return user.aura_module_ip if user and user.aura_module_ip else ""


async def _get_aura_status(uid: str, aura_module_ip: str) -> str:
    ip = await _get_aura_ip(uid, aura_module_ip)
    if not ip:
        return "Aura module is NOT connected. No module IP found for this user."
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{ip}:8001/health")
        if resp.status_code == 200:
            data = resp.json()
            return (
                f"Aura module is CONNECTED\n"
                f"IP: {ip}\n"
                f"Version: {data.get('version', 'unknown')}\n"
                f"Features: camera, microphone, face_recognition"
            )
        return f"Aura module at {ip} returned status {resp.status_code}."
    except Exception:
        return f"Aura module at {ip} is NOT reachable."


async def _get_aura_live_context(uid: str, aura_module_ip: str) -> str:
    ip = await _get_aura_ip(uid, aura_module_ip)
    if not ip:
        return "Aura module not connected."
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"http://{ip}:8001/context")
        if resp.status_code == 200:
            data = resp.json()
            lines = ["Aura Live Context:"]
            if data.get("transcript"):
                lines.append(f"Latest transcript: {data['transcript']}")
            if data.get("snapshot_url"):
                lines.append(f"Snapshot URL: {data['snapshot_url']}")
            if data.get("video_feed_url"):
                lines.append(f"Video feed: {data['video_feed_url']}")
            return "\n".join(lines)
        return "Could not fetch live context from Aura module."
    except Exception as e:
        return f"Aura live context error: {e}"


# ─── Location / Suggestions / Steps ─────────────────────────────────────────

async def _get_current_location(uid: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user or not user.last_location:
        return "No location data available."
    loc = user.last_location
    lat = loc.get("latitude", loc.get("lat", "?"))
    lon = loc.get("longitude", loc.get("lon", "?"))
    ts = loc.get("timestamp", "unknown time")
    return f"Last known location: {lat}, {lon} (as of {ts})"


async def _get_suggestions(uid: str) -> str:
    try:
        suggestions = await Suggestion.find(
            Suggestion.user_uid == uid
        ).sort("-created_at").limit(5).to_list()
        if not suggestions:
            return "No suggestions available right now."
        return "Today's suggestions:\n" + "\n".join(
            f"• {s.title}: {s.description}" for s in suggestions
        )
    except Exception:
        return "Could not load suggestions."


async def _get_steps(uid: str) -> str:
    user = await User.find_one(User.firebase_uid == uid)
    if not user:
        return "User not found."
    prefs = user.preferences or {}
    steps = prefs.get("today_steps", None)
    if steps is None:
        return "No step data available today."
    return f"Today's steps: {steps:,}"
