"""Outreach history (activity.json): one record per email, tracked through draft -> sent / failed."""
import re
import uuid
from datetime import datetime, timezone

from services.storage import data_path, locked, read_json, write_json

MAX_ENTRIES = 50
STATUS_PATTERN = re.compile(r"^[a-z][a-z-]{0,19}$")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _path():
    return data_path("activity.json")


def list_activities():
    entries = read_json(_path(), [])
    return entries if isinstance(entries, list) else []


def get_activity(activity_id):
    return next((entry for entry in list_activities() if entry.get("id") == activity_id), None)


def add_activity(**fields):
    """Creates a record and returns it. Unknown statuses default to draft."""
    now = utc_now()
    record = {
        "id": uuid.uuid4().hex[:12],
        "recipient": "",
        "subject": "",
        "body": "",
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }
    record.update({key: value for key, value in fields.items() if value is not None})
    with locked():
        entries = list_activities()
        entries.insert(0, record)
        write_json(_path(), entries[:MAX_ENTRIES])
    return record


def update_activity(activity_id, **fields):
    """Merges fields into a record. Returns the updated record, or None if it no longer exists."""
    with locked():
        entries = list_activities()
        for entry in entries:
            if entry.get("id") == activity_id:
                entry.update(fields)
                entry["updated_at"] = utc_now()
                write_json(_path(), entries)
                return entry
    return None


def delete_activity(activity_id):
    with locked():
        entries = [entry for entry in list_activities() if entry.get("id") != activity_id]
        write_json(_path(), entries)
    return entries


def public_record(record):
    """History entry as shown to the browser (internal send bookkeeping stripped)."""
    return {key: value for key, value in record.items() if not key.startswith("_")}


def public_list():
    return [public_record(entry) for entry in list_activities()]
