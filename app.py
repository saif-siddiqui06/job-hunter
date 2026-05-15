import base64
import csv
import io
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, Response, request, jsonify, redirect, send_from_directory, session, stream_with_context, url_for

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None
    Flow = None
    build = None

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

EMAIL_COLUMNS = ("email", "Email", "EMAIL", "e-mail", "E-mail")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]
APP_PORT = int(os.environ.get("PORT", "5000"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", f"http://127.0.0.1:{APP_PORT}")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", f"{PUBLIC_BASE_URL}/auth/google/callback")

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

def credentials_to_session(credentials):
    session["google_credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }

def credentials_from_session():
    data = session.get("google_credentials")
    if not data or Credentials is None:
        return None
    return Credentials(**data)

def build_message(sender, recipient, subject, message, resume_data=None, resume_name="resume.pdf"):
    msg = MIMEMultipart()
    if sender:
        msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(message, "plain"))

    if resume_data:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(resume_data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=resume_name)
        msg.attach(part)

    return msg

def send_with_gmail_api(sender, recipients, subject, message, resume_data, resume_name):
    credentials = credentials_from_session()
    if not credentials:
        return None, jsonify({"success": False, "error": "Please sign in with Google first."}), 401

    service = build("gmail", "v1", credentials=credentials)
    sent = 0
    failed = 0

    for recipient in recipients:
        try:
            msg = build_message(sender, recipient, subject, message, resume_data, resume_name)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            sent += 1
        except Exception:
            failed += 1

    return {
        "success": True,
        "count": sent,
        "failed": failed,
        "total": len(recipients),
    }, None, None

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

def stream_google_progress(sender, recipients, subject, message, resume_data, resume_name):
    credentials = credentials_from_session()
    if not credentials:
        yield progress_event(type="error", success=False, error="Please sign in with Google first.")
        return

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

@app.route("/auth/google/start")
def google_start():
    if Flow is None:
        return jsonify({"success": False, "error": "Google login dependencies are not installed. Run pip install -r requirements.txt."}), 500
    if not google_oauth_ready():
        return jsonify({"success": False, "error": "Google login is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first."}), 500

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

    flow = Flow.from_client_config(
        google_client_config(),
        scopes=GOOGLE_SCOPES,
        state=session.get("google_oauth_state"),
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    flow.fetch_token(authorization_response=request.url)
    credentials_to_session(flow.credentials)
    return redirect("/?google_auth=connected")

@app.route("/auth/status")
def auth_status():
    return jsonify({
        "googleConfigured": google_oauth_ready() and Flow is not None and build is not None,
        "googleConnected": bool(session.get("google_credentials")),
        "googleAuthUrl": f"{PUBLIC_BASE_URL}/auth/google/start",
        "googleRedirectUri": GOOGLE_REDIRECT_URI,
    })

@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.pop("google_credentials", None)
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

        # Basic validation
        needs_password = auth_method != "google"
        if not all([email, subject, message, csv_file]) or (needs_password and not password):
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

        if auth_method == "google":
            if not credentials_from_session():
                return jsonify({"success": False, "error": "Please sign in with Google first."}), 401
            return Response(
                stream_with_context(stream_google_progress(email, emails_list, subject, message, resume_data, resume_name)),
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
