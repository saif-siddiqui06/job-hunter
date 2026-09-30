"""Gmail: connection storage, message building and single-message sending.

A session connects Gmail either with Google sign-in (OAuth) or with a verified App Password.
Both are kept server-side (.gmail_tokens.json, git-ignored); the browser session only holds an
opaque random id. The OAuth client secret is never stored, it's read from the environment.
"""
import base64
import json
import logging
import mimetypes
import os
import secrets
import smtplib
import socket
from email.message import EmailMessage
from email.utils import formataddr

from flask import session

from services.history import utc_now
from services.storage import data_path, locked, read_json, write_json

try:
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:  # optional dependencies; Google sign-in is then reported as not configured
    Credentials = build = None
    RefreshError = HttpError = type("_Unavailable", (Exception,), {})

logger = logging.getLogger(__name__)

SESSION_KEY = "gmail_sid"
LEGACY_SESSION_KEY = "google_credentials"  # tokens used to live in the cookie itself


class SendError(Exception):
    """A send failure with a message that is safe and useful to show to the user."""

    def __init__(self, message, status=502, code="send_failed"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


# ---- Credential storage ----------------------------------------------------

def _token_path():
    return data_path(".gmail_tokens.json")


def _account_from_id_token(id_token):
    """Email claim of the ID token Google returned directly to us over TLS during the code exchange."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except (AttributeError, IndexError, ValueError):
        return None


def _save_entry(entry):
    sid = session.get(SESSION_KEY) or secrets.token_urlsafe(32)
    entry["updated_at"] = utc_now()
    with locked():
        tokens = read_json(_token_path(), {})
        tokens[sid] = entry
        write_json(_token_path(), tokens)
    session[SESSION_KEY] = sid
    session.pop(LEGACY_SESSION_KEY, None)


def store_credentials(credentials):
    _save_entry({
        "method": "google",
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "scopes": list(credentials.scopes or []),
        "account_email": _account_from_id_token(getattr(credentials, "id_token", None)),
    })


def connect_app_password(email, app_password):
    """Checks the App Password with Gmail before saving it, so a wrong one fails now, not at send time."""
    email = email.strip().lower()
    password = "".join(app_password.split())
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
            server.login(email, password)
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(
            "Gmail rejected that App Password. Check the address, then create a new 16-letter App Password and paste it again.",
            401, "gmail_auth",
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise SendError("Couldn't reach Gmail to check the password. Check your internet connection and try again.", 502, "gmail_unreachable") from exc
    _save_entry({"method": "app_password", "account_email": email, "app_password": password})


def _migrate_legacy_session():
    legacy = session.pop(LEGACY_SESSION_KEY, None)
    if not legacy or Credentials is None:
        return
    credentials = Credentials(
        token=legacy.get("token"),
        refresh_token=legacy.get("refresh_token"),
        token_uri=legacy.get("token_uri"),
        scopes=legacy.get("scopes"),
    )
    store_credentials(credentials)


def _entry():
    if LEGACY_SESSION_KEY in session:
        _migrate_legacy_session()
    sid = session.get(SESSION_KEY)
    return read_json(_token_path(), {}).get(sid) if sid else None


def connection():
    """{"method": "google" | "app_password", "account": email or None} for the connected Gmail, else None."""
    entry = _entry()
    if not entry:
        return None
    return {"method": entry.get("method", "google"), "account": entry.get("account_email")}


def app_password_credentials():
    entry = _entry()
    if not entry or entry.get("method") != "app_password":
        return None
    return entry["account_email"], entry["app_password"]


def load_credentials():
    entry = _entry()
    if not entry or entry.get("method", "google") != "google" or Credentials is None:
        return None
    return Credentials(
        token=entry.get("token"),
        refresh_token=entry.get("refresh_token"),
        token_uri=entry.get("token_uri"),
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        scopes=entry.get("scopes"),
    )


def connected_account():
    entry = _entry()
    return entry.get("account_email") if entry else None


def is_connected():
    return _entry() is not None


def forget_credentials():
    sid = session.pop(SESSION_KEY, None)
    session.pop(LEGACY_SESSION_KEY, None)
    if not sid:
        return
    with locked():
        tokens = read_json(_token_path(), {})
        if tokens.pop(sid, None) is not None:
            write_json(_token_path(), tokens)


def _persist_refreshed_token(credentials):
    sid = session.get(SESSION_KEY)
    if not sid or not credentials.token:
        return
    with locked():
        tokens = read_json(_token_path(), {})
        if sid in tokens and tokens[sid].get("token") != credentials.token:
            tokens[sid]["token"] = credentials.token
            tokens[sid]["updated_at"] = utc_now()
            write_json(_token_path(), tokens)


# ---- Messages --------------------------------------------------------------

def build_message(sender, recipient, subject, message, resume_data=None, resume_name="resume.pdf", sender_name=None):
    """RFC 5322 message. The default email policy rejects CR/LF in headers (no header injection)."""
    msg = EmailMessage()
    if sender:
        msg["From"] = formataddr((sender_name, sender)) if sender_name else sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(message, cte="quoted-printable")  # 7-bit safe for both SMTP and the Gmail API
    if resume_data:
        mime = mimetypes.guess_type(resume_name)[0] or "application/octet-stream"
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(resume_data, maintype=maintype, subtype=subtype, filename=resume_name)
    return msg


# ---- Sending ---------------------------------------------------------------

def send_with_google(message):
    """Sends one message with the connected Gmail account. Returns the Gmail message id."""
    credentials = load_credentials()
    if credentials is None:
        raise SendError("Connect your Gmail account before sending.", 401, "gmail_not_connected")
    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except RefreshError as exc:
        logger.warning("Gmail token refresh failed: %s", exc)
        raise SendError("Your Gmail connection expired or was revoked. Reconnect Gmail and try again.", 401, "gmail_auth") from exc
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", 502)
        logger.warning("Gmail API error %s", status)
        if status in (401, 403):
            raise SendError("Gmail refused the request. Reconnect Gmail and allow sending permission.", 401, "gmail_auth") from exc
        if status == 429:
            raise SendError("Gmail's sending limit was reached. Wait a few minutes and try again.", 429, "gmail_rate_limited") from exc
        if status == 400:
            raise SendError("Gmail rejected this message. Check the recipient address and attachment.", 400, "gmail_rejected") from exc
        raise SendError("Gmail is not responding right now. Your draft is saved; try again shortly.", 502) from exc
    except (OSError, socket.timeout) as exc:
        raise SendError("Couldn't reach Gmail. Check your connection and try again.", 502) from exc
    _persist_refreshed_token(credentials)
    return result.get("id")


def send_connected(message):
    """Sends with whichever Gmail connection this session has."""
    stored = app_password_credentials()
    if stored:
        return send_with_app_password(stored[0], stored[1], message)
    return send_with_google(message)


def send_with_app_password(sender, app_password, message):
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender, "".join(app_password.split()))
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(
            "Gmail sign-in failed. Use a 16-character Gmail App Password, not your normal password.", 401, "gmail_auth"
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise SendError("Gmail refused the recipient address. Check it and try again.", 400, "gmail_rejected") from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("SMTP send failed: %s", exc.__class__.__name__)
        raise SendError("Couldn't send through Gmail right now. Your draft is saved; try again shortly.", 502) from exc
    return None
