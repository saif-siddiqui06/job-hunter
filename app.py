import base64
import csv
import io
import json
import logging
import mimetypes
import os
import secrets
import smtplib

from flask import Flask, Response, request, jsonify, redirect, send_from_directory, session, stream_with_context


def load_dotenv(path):
    """Minimal .env support (KEY=VALUE lines). Variables already set in the environment always win."""
    if os.environ.get("APP_SKIP_DOTENV"):
        return
    try:
        with open(path, encoding="utf-8-sig") as file:
            lines = file.read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


from datetime import timedelta

from werkzeug.middleware.proxy_fix import ProxyFix

from accounts import bp as accounts_bp, require_login
from email_assistant import bp as email_assistant_bp, require_app_request
from services import gmail, history
from services.gmail import build_message
from services.profile import load_profile, load_resume_attachment
from services.storage import root_path
from services.uploads import MAX_REQUEST_BYTES

try:
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
except ImportError:
    Flow = None
    build = None

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("apply_rocket")

# Windows can map .js to text/plain in the registry, which browsers refuse for scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

def load_secret_key():
    """FLASK_SECRET_KEY, or a random key generated once and kept in the data dir, so restarts keep sessions."""
    configured = os.environ.get("FLASK_SECRET_KEY")
    if configured:
        return configured
    path = root_path(".flask_secret")
    try:
        with open(path, encoding="utf-8") as file:
            stored = file.read().strip()
        if stored:
            return stored
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(key)
    return key


APP_PORT = int(os.environ.get("PORT", "5000"))
# Render sets RENDER_EXTERNAL_URL (https://<service>.onrender.com) automatically.
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or f"http://127.0.0.1:{APP_PORT}").rstrip("/")
HOSTED = PUBLIC_BASE_URL.startswith("https://")

app = Flask(__name__, static_folder="static")
app.secret_key = load_secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=HOSTED,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
if HOSTED or os.environ.get("TRUST_PROXY"):
    # Behind the host's HTTPS proxy: trust one hop for the real client IP and the https scheme.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.register_blueprint(accounts_bp)
app.register_blueprint(email_assistant_bp)

EMAIL_COLUMNS = ("email", "Email", "EMAIL", "e-mail", "E-mail")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", f"{PUBLIC_BASE_URL}/auth/google/callback")
if PUBLIC_BASE_URL.startswith(("http://127.0.0.1", "http://localhost")):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # OAuth over plain HTTP is only OK locally

@app.before_request
def guard_requests():
    if request.path.startswith("/api/"):
        blocked = require_app_request()
        if blocked:
            return blocked
    return require_login()

@app.errorhandler(413)
def request_too_large(_error):
    limit_mb = MAX_REQUEST_BYTES // (1024 * 1024)
    return jsonify({"success": False, "error": f"Upload exceeds the maximum allowed size ({limit_mb} MB)."}), 413

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

def extract_recipients(csv_file):
    csv_content = csv_file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(csv_content))

    if not reader.fieldnames:
        return []

    recipients = []
    for row in reader:
        if not row:
            continue

        email_val = next((row.get(column) for column in EMAIL_COLUMNS if row.get(column)), None)
        if not email_val:
            email_val = next(iter(row.values()), "")

        email_val = email_val.strip()
        if "@" in email_val:
            recipients.append(email_val)

    return recipients

def normalize_app_password(password):
    return "".join(password.split())


def generate_followup_draft(previous_subject, previous_body, recipient_email):
    subject = previous_subject or "Following up on my previous message"
    if "follow" not in subject.lower():
        subject = f"Following up on {subject}"

    body = previous_body.strip() if previous_body else ""
    if "thank you" not in body.lower():
        body_text = (
            f"Hi,\n\n"
            f"I wanted to follow up on my previous note regarding the opportunity. "
            f"I am very interested in the role and would appreciate the opportunity to connect. "
            f"I would be glad to share more information about my background and discuss how I could contribute to the team.\n\n"
            f"Thank you for your time and consideration. I would be happy to speak briefly if helpful.\n\n"
            f"Best regards,"
        )
    else:
        body_text = (
            f"Hi,\n\n"
            f"I wanted to follow up on my previous message and thank you again for your time. "
            f"I remain very interested in the opportunity and would welcome a brief conversation to learn more about the role and team.\n\n"
            f"Please let me know if there is a convenient time to connect.\n\n"
            f"Best regards,"
        )

    name = (load_profile().get("fullName") or "").strip()
    if name:
        body_text += f"\n{name}"

    return subject, body_text


def google_oauth_ready():
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

def google_client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }

def progress_event(**payload):
    return json.dumps(payload) + "\n"

def stream_smtp_progress(server, sender, recipients, subject, message, resume_data, resume_name):
    sent = 0
    failed = 0
    total = len(recipients)

    try:
        yield progress_event(type="start", total=total, sent=sent, failed=failed, percent=0)
        for index, recipient in enumerate(recipients, start=1):
            try:
                msg = build_message(sender, recipient, subject, message, resume_data, resume_name)
                server.sendmail(sender, recipient, msg.as_string())
                sent += 1
                status = "sent"
            except Exception:
                failed += 1
                status = "failed"

            yield progress_event(
                type="progress",
                recipient=recipient,
                status=status,
                current=index,
                total=total,
                sent=sent,
                failed=failed,
                percent=round((index / total) * 100),
            )

        yield progress_event(type="done", success=True, count=sent, failed=failed, total=total, percent=100)
    finally:
        try:
            server.quit()
        except Exception:
            pass

def stream_google_progress(credentials, sender, recipients, subject, message, resume_data, resume_name):
    service = build("gmail", "v1", credentials=credentials)
    sent = 0
    failed = 0
    total = len(recipients)

    yield progress_event(type="start", total=total, sent=sent, failed=failed, percent=0)
    for index, recipient in enumerate(recipients, start=1):
        try:
            msg = build_message(sender, recipient, subject, message, resume_data, resume_name)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            sent += 1
            status = "sent"
        except Exception:
            failed += 1
            status = "failed"

        yield progress_event(
            type="progress",
            recipient=recipient,
            status=status,
            current=index,
            total=total,
            sent=sent,
            failed=failed,
            percent=round((index / total) * 100),
        )

    yield progress_event(type="done", success=True, count=sent, failed=failed, total=total, percent=100)

@app.route("/api/log-activity", methods=["POST"])
def log_activity_api():
    payload = request.get_json(silent=True) or {}
    recipient = (payload.get("recipient") or "").strip()
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    status = (payload.get("status") or "draft").strip()

    if not recipient or not subject or not body:
        return jsonify({"success": False, "error": "Recipient, subject, and body are required to log an activity."}), 400
    if not history.STATUS_PATTERN.match(status):
        return jsonify({"success": False, "error": "Unknown status."}), 400

    record = history.add_activity(recipient=recipient[:254], subject=subject[:200], body=body[:20000], status=status)
    return jsonify({"success": True, "activity": history.public_record(record), "activities": history.public_list()})

@app.route("/api/list-activities", methods=["GET"])
def list_activities_api():
    return jsonify({"success": True, "activities": history.public_list()})

@app.route("/api/update-activity/<activity_id>", methods=["PATCH"])
def update_activity_api(activity_id):
    """Updates a history entry's status and/or, for unsent drafts, its recipient/subject/body."""
    data = request.get_json(silent=True) or {}
    record = history.get_activity(activity_id)
    if record is None:
        return jsonify({"success": False, "error": "This entry no longer exists."}), 404

    changes = {}
    status = data.get("status")
    if status is not None:
        if not isinstance(status, str) or not history.STATUS_PATTERN.match(status.strip()) or status.strip() in ("sent", "sending"):
            return jsonify({"success": False, "error": "Unknown status."}), 400
        changes["status"] = status.strip()

    edits = {key: data[key] for key in ("recipient", "subject", "body") if isinstance(data.get(key), str)}
    if "attachResume" in data:
        edits["attach_resume"] = data["attachResume"] is True
    if edits:
        if record.get("status") in ("sent", "sending"):
            return jsonify({"success": False, "error": "Sent emails can't be edited."}), 409
        if "subject" in edits and ("\n" in edits["subject"] or len(edits["subject"]) > 200):
            return jsonify({"success": False, "error": "The subject must be a single line of up to 200 characters."}), 400
        edits = {key: value.strip()[:20000] if isinstance(value, str) else value for key, value in edits.items()}
        changes.update(edits)

    if changes:
        history.update_activity(activity_id, **changes)
    return jsonify({"success": True, "activities": history.public_list()})

@app.route("/api/delete-activity/<activity_id>", methods=["DELETE"])
def delete_activity_api(activity_id):
    history.delete_activity(activity_id)
    return jsonify({"success": True, "activities": history.public_list()})

@app.route("/api/generate-follow-up", methods=["POST"])
def generate_follow_up_api():
    try:
        payload = request.get_json(silent=True) or {}
        previous_subject = (payload.get("subject") or "").strip()
        previous_body = (payload.get("body") or "").strip()
        recipient_email = (payload.get("recipient") or "").strip()

        if not previous_body and not previous_subject:
            return jsonify({"success": False, "error": "Provide the previous email subject or body to generate a follow-up."}), 400

        subject, body = generate_followup_draft(previous_subject, previous_body, recipient_email)
        return jsonify({"success": True, "subject": subject, "body": body, "recipient": recipient_email})
    except Exception:
        logger.exception("Follow-up generation failed")
        return jsonify({"success": False, "error": "Could not generate a follow-up right now."}), 500

@app.route("/auth/google/start")
def google_start():
    # Problems come back to the page as ?google_auth=<reason>, which the UI explains, never a raw error page.
    if Flow is None:
        return redirect("/?google_auth=missing_dependencies")
    if not google_oauth_ready():
        return redirect("/?google_auth=missing_config")

    flow = Flow.from_client_config(
        google_client_config(),
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["google_oauth_state"] = state
    return redirect(authorization_url)

@app.route("/auth/google/callback")
def google_callback():
    if Flow is None:
        return redirect("/?google_auth=missing_dependencies")
    if not google_oauth_ready():
        return redirect("/?google_auth=missing_config")

    if request.args.get("error"):
        return redirect("/?google_auth=denied")

    flow = Flow.from_client_config(
        google_client_config(),
        scopes=GOOGLE_SCOPES,
        state=session.get("google_oauth_state"),
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception:
        logger.exception("Google sign-in failed")
        return redirect("/?google_auth=failed")
    gmail.store_credentials(flow.credentials)
    session.pop("google_oauth_state", None)
    return redirect("/?google_auth=connected")

@app.route("/auth/status")
def auth_status():
    connection = gmail.connection()
    return jsonify({
        "connected": connection is not None,
        "method": connection["method"] if connection else None,
        "account": connection["account"] if connection else None,
        "googleConfigured": google_oauth_ready() and Flow is not None and build is not None,
        "googleConnected": bool(connection and connection["method"] == "google"),
        "googleAccount": connection["account"] if connection else None,
        "googleAuthUrl": f"{PUBLIC_BASE_URL}/auth/google/start",
        "googleRedirectUri": GOOGLE_REDIRECT_URI,
    })

@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    gmail.forget_credentials()
    session.pop("google_oauth_state", None)
    return jsonify({"success": True})

@app.route("/send", methods=["POST"])
def send_emails():
    try:
        # Get form data
        email = request.form.get("email", "").strip()
        password = normalize_app_password(request.form.get("password", ""))
        auth_method = request.form.get("auth_method", "app_password")
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        csv_file = request.files.get("csv")
        resume_file = request.files.get("resume")

        # "connected" sends with the Gmail account connected in the app (App Password or Google).
        if auth_method == "connected":
            connection = gmail.connection()
            if connection is None:
                return jsonify({"success": False, "error": "Connect your Gmail account before sending."}), 401
            if connection["method"] == "app_password":
                email, password = gmail.app_password_credentials()
                auth_method = "app_password"
            else:
                email = connection["account"] or ""
                auth_method = "google"

        # Basic validation
        needs_password = auth_method != "google"
        if not all([subject, message, csv_file]) or (needs_password and not (email and password)):
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # Parse CSV
        emails_list = extract_recipients(csv_file)

        if not emails_list:
            return jsonify({"success": False, "error": "No valid emails in CSV"}), 400

        # Read resume if provided
        resume_data = None
        resume_name = "resume.pdf"
        if resume_file:
            resume_data = resume_file.read()
            resume_name = resume_file.filename
        elif request.form.get("use_profile_resume") == "1":
            stored = load_resume_attachment()
            if stored is None:
                return jsonify({"success": False, "error": "Your profile has no resume. Upload one or choose no attachment."}), 400
            resume_data, resume_name = stored[0], stored[1]

        if auth_method == "google":
            credentials = gmail.load_credentials()
            if not credentials:
                return jsonify({"success": False, "error": "Please sign in with Google first."}), 401
            return Response(
                stream_with_context(stream_google_progress(credentials, email, emails_list, subject, message, resume_data, resume_name)),
                mimetype="application/x-ndjson",
            )

        # Send emails via Gmail SMTP
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
        server.login(email, password)
        return Response(
            stream_with_context(stream_smtp_progress(server, email, emails_list, subject, message, resume_data, resume_name)),
            mimetype="application/x-ndjson",
        )

    except smtplib.SMTPAuthenticationError:
        return jsonify({
            "success": False,
            "error": "Gmail authentication failed. Use a 16-character Gmail App Password, not your normal Gmail password. The app now removes spaces automatically."
        }), 401
    except UnicodeDecodeError:
        return jsonify({"success": False, "error": "Could not read CSV. Please upload a UTF-8 CSV file"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=APP_PORT, use_reloader=False)
