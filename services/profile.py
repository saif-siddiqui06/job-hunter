"""The sender's profile (name, contact links, background) and stored resume file.

The profile is the only trusted source of facts about the user that the AI may use in an email.
"""
import io
import logging
import os
import re
import secrets

from services.extraction import is_valid_email
from services.history import utc_now
from services.storage import data_path, locked, read_json, write_json

logger = logging.getLogger(__name__)

TEXT_LIMITS = {
    "fullName": 120,
    "email": 254,
    "phone": 40,
    "linkedinUrl": 300,
    "portfolioUrl": 300,
    "headline": 200,
}
EXPERIENCE_LIMIT = 8000
MAX_SKILLS = 50
MAX_SKILL_LENGTH = 60
PHONE_PATTERN = re.compile(r"^[0-9+()\-.\s]{6,40}$")
URL_PATTERN = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/\S*)?$", re.IGNORECASE)


class ProfileError(ValueError):
    pass


def _profile_path():
    return data_path("profile.json")


def _resume_dir():
    return data_path("uploads", "resume")


def load_profile():
    profile = read_json(_profile_path(), {})
    return profile if isinstance(profile, dict) else {}


def public_profile(profile=None):
    profile = load_profile() if profile is None else profile
    result = {field: profile.get(field, "") for field in TEXT_LIMITS}
    result["skills"] = profile.get("skills", [])
    result["experience"] = profile.get("experience", "")
    resume = profile.get("resume")
    result["resume"] = {key: resume[key] for key in ("filename", "size", "uploadedAt")} if resume else None
    return result


def _single_line(value, field, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProfileError(f"{field} must be text.")
    value = " ".join(value.split())
    if len(value) > limit:
        raise ProfileError(f"{field} is too long (max {limit} characters).")
    return value


def _normalize_url(value, label):
    if not value:
        return ""
    if not URL_PATTERN.match(value):
        raise ProfileError(f"{label} doesn't look like a valid link.")
    return value if value.lower().startswith(("http://", "https://")) else f"https://{value}"


def validate_profile_update(payload):
    """Returns the cleaned subset of fields present in payload."""
    if not isinstance(payload, dict):
        raise ProfileError("Send the profile as a JSON object.")
    cleaned = {}
    for field, limit in TEXT_LIMITS.items():
        if field in payload:
            cleaned[field] = _single_line(payload[field], field, limit)

    if cleaned.get("email") and not is_valid_email(cleaned["email"]):
        raise ProfileError("Your email address doesn't look valid.")
    if cleaned.get("phone") and not PHONE_PATTERN.match(cleaned["phone"]):
        raise ProfileError("Your phone number can only contain digits, spaces and + ( ) - .")
    if "linkedinUrl" in cleaned:
        cleaned["linkedinUrl"] = _normalize_url(cleaned["linkedinUrl"], "LinkedIn URL")
    if "portfolioUrl" in cleaned:
        cleaned["portfolioUrl"] = _normalize_url(cleaned["portfolioUrl"], "GitHub/portfolio URL")

    if "skills" in payload:
        skills = payload["skills"]
        if isinstance(skills, str):
            skills = skills.split(",")
        if not isinstance(skills, list) or not all(isinstance(skill, str) for skill in skills):
            raise ProfileError("Skills must be a list of text values.")
        skills = [" ".join(skill.split()) for skill in skills]
        skills = list(dict.fromkeys(skill for skill in skills if skill))
        if len(skills) > MAX_SKILLS or any(len(skill) > MAX_SKILL_LENGTH for skill in skills):
            raise ProfileError(f"Keep skills to {MAX_SKILLS} items of up to {MAX_SKILL_LENGTH} characters.")
        cleaned["skills"] = skills

    if "experience" in payload:
        experience = payload["experience"] or ""
        if not isinstance(experience, str):
            raise ProfileError("Experience must be text.")
        experience = experience.replace("\r\n", "\n").strip()
        if len(experience) > EXPERIENCE_LIMIT:
            raise ProfileError(f"Experience is too long (max {EXPERIENCE_LIMIT} characters).")
        cleaned["experience"] = experience
    return cleaned


def update_profile(payload):
    cleaned = validate_profile_update(payload)
    with locked():
        profile = load_profile()
        profile.update(cleaned)
        profile["updatedAt"] = utc_now()
        write_json(_profile_path(), profile)
    return public_profile(profile)


def _extract_pdf_text(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
    except Exception as exc:  # pypdf raises a wide range of parse errors on odd PDFs
        logger.info("Could not extract resume text: %s", exc)
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:EXPERIENCE_LIMIT]


def save_resume(data, filename, mime):
    """Stores the resume, replacing any previous file. Fills `experience` from a PDF if it was empty."""
    os.makedirs(_resume_dir(), exist_ok=True)
    stored_name = f"{secrets.token_hex(8)}-{filename}"
    with open(os.path.join(_resume_dir(), stored_name), "wb") as file:
        file.write(data)

    with locked():
        profile = load_profile()
        previous = (profile.get("resume") or {}).get("storedName")
        profile["resume"] = {
            "filename": filename,
            "storedName": stored_name,
            "mime": mime,
            "size": len(data),
            "uploadedAt": utc_now(),
        }
        if not profile.get("experience") and mime == "application/pdf":
            profile["experience"] = _extract_pdf_text(data)
        write_json(_profile_path(), profile)

    if previous:
        _remove_stored_resume(previous)
    return public_profile(profile)


def delete_resume():
    with locked():
        profile = load_profile()
        resume = profile.pop("resume", None)
        write_json(_profile_path(), profile)
    if resume:
        _remove_stored_resume(resume.get("storedName"))
    return public_profile(profile)


def _remove_stored_resume(stored_name):
    path = _resume_file_path(stored_name)
    if path and os.path.exists(path):
        os.remove(path)


def _resume_file_path(stored_name):
    # Only ever resolve names we generated, inside the resume directory.
    if not stored_name or os.path.basename(stored_name) != stored_name:
        return None
    return os.path.join(_resume_dir(), stored_name)


def load_resume_attachment():
    """Returns (data, filename, mime) for the stored resume, or None if there isn't one."""
    resume = load_profile().get("resume")
    if not resume:
        return None
    path = _resume_file_path(resume.get("storedName"))
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as file:
        return file.read(), resume["filename"], resume.get("mime", "application/octet-stream")
