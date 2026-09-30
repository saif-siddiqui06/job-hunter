"""AI Email Assistant API: screenshot/text -> extracted context -> draft -> confirmed send.

    POST   /api/email-assistant/extract   multipart "screenshot" or JSON {"text"}  -> EmailContext
    POST   /api/email-assistant/draft     confirmed context + style/length         -> subject/body/attachResume
    POST   /api/email-assistant/send      final (user-edited) email + Idempotency-Key header
    POST   /api/gmail/app-password        verify an App Password with Gmail and remember the connection
    GET    /api/profile, PUT /api/profile, POST/DELETE /api/profile/resume

Nothing is ever sent without an explicit call to /send, which re-validates every field.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from services import gmail, history, profile as profiles
from services.drafting import DraftInputError, MAX_BODY_CHARS, generate_draft, parse_draft_input
from services.extraction import ExtractionError, analyze_screenshot, analyze_text, is_valid_email
from services.ratelimit import RateLimiter
from services.storage import locked
from services.uploads import UploadError, validate_image, validate_resume

logger = logging.getLogger(__name__)

bp = Blueprint("email_assistant", __name__)

APP_HEADER = "X-Requested-With"
APP_HEADER_VALUE = "ApplyRocket"
ai_limiter = RateLimiter(limit=20, window_seconds=60)
send_limiter = RateLimiter(limit=20, window_seconds=3600)
connect_limiter = RateLimiter(limit=5, window_seconds=600)  # slows down App Password guessing
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
SENDING_TIMEOUT = timedelta(minutes=5)


def error(message, status=400, code=None, **extra):
    body = {"success": False, "error": message}
    if code:
        body["code"] = code
    body.update(extra)
    return jsonify(body), status


def require_app_request():
    """CSRF guard: browsers can't add custom headers to cross-site requests without a CORS preflight."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get(APP_HEADER) != APP_HEADER_VALUE:
        return error("Request blocked. Reload the page and try again.", 403, "csrf")
    return None


bp.before_request(require_app_request)


def _limited(limiter):
    retry_after = limiter.check(request.remote_addr or "local")
    if retry_after:
        response = error(f"Too many requests. Try again in {retry_after} seconds.", 429, "rate_limited")
        response[0].headers["Retry-After"] = str(retry_after)
        return response
    return None


def _self_emails(extra=None):
    emails = [profiles.load_profile().get("email"), gmail.connected_account()]
    if isinstance(extra, str) and is_valid_email(extra.strip()):
        emails.append(extra.strip())
    return [email.lower() for email in emails if email]


def _json_body():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


@bp.errorhandler(UploadError)
@bp.errorhandler(ExtractionError)
def _handle_input_error(exc):
    return error(exc.message, exc.status)


@bp.errorhandler(profiles.ProfileError)
@bp.errorhandler(DraftInputError)
def _handle_validation_error(exc):
    return error(str(exc), 400)


# ---- Profile ---------------------------------------------------------------

@bp.get("/api/profile")
def get_profile():
    return jsonify({"success": True, "profile": profiles.public_profile()})


@bp.put("/api/profile")
def put_profile():
    payload = _json_body()
    if payload is None:
        return error("Send the profile as JSON.")
    return jsonify({"success": True, "profile": profiles.update_profile(payload)})


@bp.post("/api/profile/resume")
def upload_resume():
    data, filename, mime = validate_resume(request.files.get("resume"))
    return jsonify({"success": True, "profile": profiles.save_resume(data, filename, mime)})


@bp.delete("/api/profile/resume")
def remove_resume():
    return jsonify({"success": True, "profile": profiles.delete_resume()})


# ---- Gmail connection --------------------------------------------------------

@bp.post("/api/gmail/app-password")
def connect_app_password():
    limited = _limited(connect_limiter)
    if limited:
        return limited
    payload = _json_body() or {}
    email = payload.get("email").strip() if isinstance(payload.get("email"), str) else ""
    password = payload.get("appPassword") if isinstance(payload.get("appPassword"), str) else ""
    if not is_valid_email(email):
        return error("Enter the Gmail address you want to send from.", 400)
    if not 8 <= len("".join(password.split())) <= 64:
        return error("Paste the 16-letter App Password from your Google Account.", 400)
    try:
        gmail.connect_app_password(email, password)
    except gmail.SendError as exc:
        return error(exc.message, exc.status, exc.code)
    return jsonify({"success": True, "connection": gmail.connection()})


# ---- Extract ---------------------------------------------------------------

@bp.post("/api/email-assistant/extract")
def extract():
    limited = _limited(ai_limiter)
    if limited:
        return limited

    screenshot = request.files.get("screenshot")
    if screenshot is not None:
        image = validate_image(screenshot)
        context = analyze_screenshot(image, _self_emails(request.form.get("senderEmail")))
    else:
        payload = _json_body() or {}
        text = payload.get("text", request.form.get("text"))
        if not isinstance(text, str):
            return error("Upload a screenshot or paste some text to analyze.")
        context = analyze_text(text, _self_emails(payload.get("senderEmail")))
    return jsonify({"success": True, "context": context.to_dict()})


# ---- Draft -----------------------------------------------------------------

def _record_fields(recipient, subject, body, company, role, source_type, attach_resume):
    return {
        "recipient": recipient or "",
        "subject": subject,
        "body": body,
        "company": company,
        "role": role,
        "source_type": source_type,
        "attach_resume": attach_resume,
    }


@bp.post("/api/email-assistant/draft")
def draft():
    limited = _limited(ai_limiter)
    if limited:
        return limited
    payload = _json_body()
    if payload is None:
        return error("Send the email details as JSON.")

    data = parse_draft_input(payload)
    profile = profiles.load_profile()
    attach_available = profiles.load_resume_attachment() is not None
    result = generate_draft(data, profile, attach_available)

    fields = _record_fields(data.recipientEmail, result.subject, result.body, data.companyName, data.jobTitle, data.sourceType, result.attachResume)
    history_id = payload.get("historyId")
    existing = history.get_activity(history_id) if isinstance(history_id, str) else None
    if existing and existing.get("status") not in ("sent", "sending"):
        record = history.update_activity(history_id, status="draft", **fields)
    else:
        record = history.add_activity(status="draft", **fields)
    return jsonify({"success": True, "draft": result.to_dict(), "historyId": record["id"]})


# ---- Send ------------------------------------------------------------------

def _parse_send(payload):
    to = (payload.get("to") or "").strip() if isinstance(payload.get("to"), str) else ""
    subject = payload.get("subject") if isinstance(payload.get("subject"), str) else ""
    body = payload.get("body") if isinstance(payload.get("body"), str) else ""
    subject = subject.strip()
    body = body.replace("\r\n", "\n").strip()

    if not to:
        return None, "No recipient email found. Add who this email should go to."
    if not is_valid_email(to):
        return None, "The recipient email address isn't valid. Enter a single address like name@company.com."
    if not subject:
        return None, "Add a subject before sending."
    if "\n" in subject or "\r" in subject or len(subject) > 200:
        return None, "The subject must be a single line of up to 200 characters."
    if not body:
        return None, "The email body is empty."
    if len(body) > MAX_BODY_CHARS:
        return None, f"The email body is too long (max {MAX_BODY_CHARS:,} characters)."

    def short(name):
        value = payload.get(name)
        if not isinstance(value, str):
            return None
        return " ".join(value.split())[:120] or None

    return {
        "to": to,
        "subject": subject,
        "body": body,
        "attach_resume": payload.get("attachResume") is True,
        "history_id": payload.get("historyId") if isinstance(payload.get("historyId"), str) else None,
        "company": short("companyName"),
        "role": short("jobTitle"),
        "source_type": payload.get("sourceType") if payload.get("sourceType") in ("screenshot", "clipboard") else None,
    }, None


def _resolve_transport():
    """Returns (send_function, sender_address) for this session's stored Gmail connection."""
    connection = gmail.connection()
    if connection is None:
        raise gmail.SendError("Connect your Gmail account before sending.", 401, "gmail_not_connected")
    return gmail.send_connected, connection["account"]


def _claim_record(data, key, attachment_meta):
    """Atomically finds or creates the history record and marks it as sending.

    Returns (record, response) where response is set when the send must not proceed."""
    fields = _record_fields(data["to"], data["subject"], data["body"], data["company"], data["role"], data["source_type"], data["attach_resume"])
    fields = {name: value for name, value in fields.items() if value is not None}
    now = datetime.now(timezone.utc)
    with locked():
        record = history.get_activity(data["history_id"]) if data["history_id"] else None
        if record is None:
            record = next((entry for entry in history.list_activities() if entry.get("_send_key") == key), None)

        if record and record.get("status") == "sent":
            return record, (jsonify({"success": True, "alreadySent": True, "historyId": record["id"], "sentAt": record.get("sent_at")}), 200)
        if record and record.get("status") == "sending":
            started = record.get("_send_started")
            if started and now - datetime.fromisoformat(started.replace("Z", "+00:00")) < SENDING_TIMEOUT:
                return record, error("This email is already being sent.", 409, "send_in_progress", historyId=record["id"])

        claim = {"status": "sending", "_send_key": key, "_send_started": history.utc_now(), "attachment": attachment_meta, "error": None}
        if record:
            record = history.update_activity(record["id"], **fields, **claim)
        else:
            record = history.add_activity(**fields, **claim)
    return record, None


@bp.post("/api/email-assistant/send")
def send():
    key = request.headers.get("Idempotency-Key", "")
    if not IDEMPOTENCY_KEY.match(key):
        return error("Missing request id. Reload the page and try again.", 400, "idempotency_key")
    payload = _json_body()
    if payload is None:
        return error("Send the email as JSON.")
    data, problem = _parse_send(payload)
    if problem:
        return error(problem, 400, "invalid_email")

    try:
        transport, sender = _resolve_transport()
    except gmail.SendError as exc:
        return error(exc.message, exc.status, exc.code)

    attachment = None
    if data["attach_resume"]:
        attachment = profiles.load_resume_attachment()
        if attachment is None:
            return error("Your resume isn't on file. Upload it or untick the attachment.", 409, "resume_missing")

    limited = _limited(send_limiter)
    if limited:
        return limited

    attachment_meta = {"filename": attachment[1], "size": len(attachment[0])} if attachment else None
    record, response = _claim_record(data, key, attachment_meta)
    if response:
        return response

    sender_name = profiles.load_profile().get("fullName") or None
    try:
        message = gmail.build_message(
            sender, data["to"], data["subject"], data["body"],
            attachment[0] if attachment else None, attachment[1] if attachment else None, sender_name=sender_name,
        )
        message_id = transport(message)
    except gmail.SendError as exc:
        history.update_activity(record["id"], status="failed", error=exc.message)
        return error(exc.message, exc.status, exc.code, historyId=record["id"])
    except Exception:
        logger.exception("Unexpected error while sending")
        message = "Something went wrong while sending. Your draft is saved; try again."
        history.update_activity(record["id"], status="failed", error=message)
        return error(message, 500, "send_failed", historyId=record["id"])

    sent_at = history.utc_now()
    history.update_activity(record["id"], status="sent", sent_at=sent_at, error=None, _gmail_message_id=message_id)
    return jsonify({"success": True, "historyId": record["id"], "sentAt": sent_at})
