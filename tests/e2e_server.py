"""Runs the real app for browser end-to-end tests, with a deterministic fake AI and a fake Gmail.

    python tests/e2e_server.py [port]

Everything else (routing, validation, extraction merge/verification, drafting pipeline, idempotency,
history) is the production code. Data goes to a temporary directory. For testing only.
"""
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA_DIR = tempfile.mkdtemp(prefix="applyrocket-e2e-")
os.environ["APP_DATA_DIR"] = DATA_DIR
os.environ["SIGNUP_CODE"] = "e2e-invite"
os.environ["APP_SKIP_DOTENV"] = "1"  # never use real keys in tests

import app as app_module  # noqa: E402
from services import ai, extraction, gmail  # noqa: E402

SCREENSHOT_TRANSCRIPT = (
    "Hi Saif,\nThanks for applying. Please send your resume to careers@example.com for the "
    "Data Analyst position at ABC Technologies. You can CC hr@example.com.\n\nBest regards,\nSarah Khan"
)


def _untrusted(prompt):
    match = re.search(r"<(untrusted_[0-9a-f]+)>\n(.*)\n</\1>", prompt, re.S)
    return match.group(2) if match else ""


def _detail(prompt, label):
    match = re.search(rf"^{label}: (.+)$", prompt, re.M)
    return match.group(1).strip() if match else None


def fake_generate_json(request):
    if request.schema_name == "email_context":
        text = SCREENSHOT_TRANSCRIPT if request.image is not None else _untrusted(request.prompt)
        emails = extraction.find_emails(text)
        rules = extraction._rule_extract(text, emails)
        rules.update(
            recipient_email=next((e for e in emails if e.startswith("careers")), emails[0] if emails else None),
            emails_seen=emails,
            transcript=text if request.image is not None else "",
            confidence={"recipient_email": 0.9, "company_name": 0.9, "job_title": 0.9},
        )
        return rules, "fake"

    role = _detail(request.prompt, "Role") or "the role"
    company = _detail(request.prompt, "Company")
    name = _detail(request.prompt, "Recipient name")
    style = re.search(r"^Style: (\w+)", request.prompt, re.M).group(1)
    greeting = f"Hello {name.split()[0]}," if name else "Hello Hiring Team,"
    body = (
        f"{greeting}\n\nI'd like to apply for the {role} position{f' at {company}' if company else ''}. "
        f"This is the {style.lower()} version of the email.\n\nI've attached my resume for your review."
    )
    return {"subject": f"Application for {role}", "body": body, "attach_resume": True}, "fake"


SENT_LOG = os.path.join(DATA_DIR, "sent.json")


def fake_send(message):
    if "FAIL" in message["Subject"]:
        raise gmail.SendError("Gmail is not responding right now. Your draft is saved; try again shortly.", 502)
    sent = json.load(open(SENT_LOG)) if os.path.exists(SENT_LOG) else []
    sent.append({"to": message["To"], "subject": message["Subject"], "attachments": [p.get_filename() for p in message.iter_attachments()]})
    json.dump(sent, open(SENT_LOG, "w"))
    return f"fake-{len(sent)}"


E2E_APP_PASSWORD = "abcdefghijklmnop"
CONNECTION = {"value": None}  # starts disconnected so the Connect Gmail flow is exercised


def fake_connect(email, app_password):
    if "".join(app_password.split()) != E2E_APP_PASSWORD:
        raise gmail.SendError("Gmail rejected that App Password. Check the address, then create a new 16-letter App Password and paste it again.", 401, "gmail_auth")
    CONNECTION["value"] = {"method": "app_password", "account": email.strip().lower()}


class FakeSMTP:
    """Stands in for smtp.gmail.com in the batch sender."""

    def __init__(self, *args, **kwargs):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, sender, recipient, message):
        sent = json.load(open(SENT_LOG)) if os.path.exists(SENT_LOG) else []
        sent.append({"to": recipient, "subject": "(batch)", "attachments": [], "batch": True})
        json.dump(sent, open(SENT_LOG, "w"))

    def quit(self):
        pass


app_module.smtplib.SMTP_SSL = FakeSMTP
gmail.app_password_credentials = lambda: (CONNECTION["value"]["account"], E2E_APP_PASSWORD) if CONNECTION["value"] else None
ai.generate_json = fake_generate_json
ai.is_available = lambda require_vision=False: True
extraction.run_ocr = lambda _data: None
gmail.connection = lambda: CONNECTION["value"]
gmail.connected_account = lambda: (CONNECTION["value"] or {}).get("account")
gmail.is_connected = lambda: CONNECTION["value"] is not None
gmail.connect_app_password = fake_connect
gmail.forget_credentials = lambda: CONNECTION.update(value=None)
gmail.send_connected = fake_send


from accounts import PUBLIC_PATHS  # noqa: E402

PUBLIC_PATHS.add("/__e2e/sent")


@app_module.app.get("/__e2e/sent")
def e2e_sent():
    return app_module.jsonify(json.load(open(SENT_LOG)) if os.path.exists(SENT_LOG) else [])


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5055
    print(f"E2E server on http://127.0.0.1:{port} (data: {DATA_DIR})", flush=True)
    app_module.app.run(port=port, debug=False, use_reloader=False, threaded=True)
