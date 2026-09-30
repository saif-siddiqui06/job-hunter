import io
import json

import pytest

from conftest import APP_HEADERS, make_pdf
from services import gmail, history

SEND = "/api/email-assistant/send"


def send(client, key="key-12345678", **overrides):
    payload = {
        "to": "careers@example.com",
        "subject": "Application for Data Analyst - Saif Siddiqui",
        "body": "Hello Sarah,\n\nPlease find my resume attached.\n\nBest regards,\nSaif Siddiqui",
        "attachResume": False,
        "companyName": "ABC Technologies",
        "jobTitle": "Data Analyst",
        "sourceType": "screenshot",
        "auth": {"method": "google"},
    }
    payload.update(overrides)
    return client.post(SEND, json=payload, headers={**APP_HEADERS, "Idempotency-Key": key})


def upload_resume(client):
    data = {"resume": (io.BytesIO(make_pdf()), "Saif_Siddiqui_Resume.pdf", "application/pdf")}
    client.put("/api/profile", json={"fullName": "Saif Siddiqui"}, headers=APP_HEADERS)
    assert client.post("/api/profile/resume", data=data, headers=APP_HEADERS, content_type="multipart/form-data").status_code == 200


def test_valid_send(client, fake_gmail):
    response = send(client)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["success"] is True and data["sentAt"]
    message = fake_gmail.sent[0]
    assert message["To"] == "careers@example.com"
    assert message["Subject"] == "Application for Data Analyst - Saif Siddiqui"
    assert message["From"] == "me@gmail.com"

    record = history.get_activity(data["historyId"])
    assert record["status"] == "sent"
    assert record["sent_at"] == data["sentAt"]
    assert record["company"] == "ABC Technologies"
    public = client.get("/api/list-activities").get_json()["activities"][0]
    assert not any(key.startswith("_") for key in public)  # idempotency bookkeeping stays server-side


def test_send_with_resume_attachment(client, fake_gmail):
    upload_resume(client)
    response = send(client, attachResume=True)
    assert response.status_code == 200
    message = fake_gmail.sent[0]
    attachments = list(message.iter_attachments())
    assert [part.get_filename() for part in attachments] == ["Saif_Siddiqui_Resume.pdf"]
    assert attachments[0].get_content_type() == "application/pdf"
    assert message["From"] == "Saif Siddiqui <me@gmail.com>"
    assert history.get_activity(response.get_json()["historyId"])["attachment"]["filename"] == "Saif_Siddiqui_Resume.pdf"


def test_attachment_requested_without_resume(client, fake_gmail):
    response = send(client, attachResume=True)
    assert response.status_code == 409
    assert response.get_json()["code"] == "resume_missing"
    assert fake_gmail.sent == []


@pytest.mark.parametrize("to", ["", "not-an-email", "a@b.com, c@d.com", "a@b.com\nBcc: x@y.com"])
def test_invalid_recipient(client, fake_gmail, to):
    response = send(client, to=to)
    assert response.status_code == 400
    assert fake_gmail.sent == []


def test_subject_header_injection_rejected(client, fake_gmail):
    response = send(client, subject="Hello\r\nBcc: attacker@evil.com")
    assert response.status_code == 400
    assert fake_gmail.sent == []


def test_gmail_disconnected(client):
    response = send(client)
    assert response.status_code == 401
    body = response.get_json()
    assert body["code"] == "gmail_not_connected"
    assert body["error"] == "Connect your Gmail account before sending."


class FakeSMTP:
    accept = True
    logins = []
    messages = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))
        if not FakeSMTP.accept:
            raise gmail.smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, message):
        FakeSMTP.messages.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.accept, FakeSMTP.logins, FakeSMTP.messages = True, [], []
    monkeypatch.setattr(gmail.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def connect(client, email="Me@Gmail.com", password="abcd efgh ijkl mnop"):
    return client.post("/api/gmail/app-password", json={"email": email, "appPassword": password}, headers=APP_HEADERS)


def test_connect_app_password_then_send(client, fake_smtp):
    response = connect(client)
    assert response.status_code == 200
    assert response.get_json()["connection"] == {"method": "app_password", "account": "me@gmail.com"}
    assert fake_smtp.logins == [("me@gmail.com", "abcdefghijklmnop")]  # checked with Gmail before saving

    status = client.get("/auth/status").get_json()
    assert status["connected"] is True and status["method"] == "app_password" and status["account"] == "me@gmail.com"
    assert "abcdefghijklmnop" not in json.dumps(status)

    assert send(client).status_code == 200
    assert fake_smtp.messages[0]["From"] == "me@gmail.com"

    client.post("/auth/logout")
    assert client.get("/auth/status").get_json()["connected"] is False


def test_wrong_app_password_is_not_saved(client, fake_smtp):
    fake_smtp.accept = False
    response = connect(client)
    assert response.status_code == 401
    assert "rejected that App Password" in response.get_json()["error"]
    assert client.get("/auth/status").get_json()["connected"] is False


@pytest.mark.parametrize("email,password", [("not-an-email", "abcdefghijklmnop"), ("me@gmail.com", "short")])
def test_connect_validation(client, fake_smtp, email, password):
    assert connect(client, email, password).status_code == 400
    assert fake_smtp.logins == []


def test_connect_is_rate_limited(client, fake_smtp):
    fake_smtp.accept = False
    for _ in range(5):
        connect(client)
    assert connect(client).status_code == 429


def test_send_failure_keeps_the_draft(client, fake_gmail):
    fake_gmail.fail_with = gmail.SendError("Gmail is not responding right now. Your draft is saved; try again shortly.", 502)
    response = send(client)
    assert response.status_code == 502
    data = response.get_json()
    record = history.get_activity(data["historyId"])
    assert record["status"] == "failed"
    assert record["body"].startswith("Hello Sarah")
    assert "not responding" in record["error"]

    # Retrying the same email (same record + key) after a failure is allowed and succeeds.
    fake_gmail.fail_with = None
    retry = send(client, historyId=data["historyId"])
    assert retry.status_code == 200
    assert history.get_activity(data["historyId"])["status"] == "sent"
    assert len(history.list_activities()) == 1


def test_duplicate_send_prevented(client, fake_gmail):
    first = send(client).get_json()
    second = send(client).get_json()  # double click: same idempotency key
    third = send(client, key="another-key-1", historyId=first["historyId"]).get_json()  # same email reopened
    assert second["alreadySent"] is True and third["alreadySent"] is True
    assert second["historyId"] == first["historyId"]
    assert len(fake_gmail.sent) == 1
    assert len(history.list_activities()) == 1


def test_send_in_progress_rejected(client, fake_gmail):
    record = history.add_activity(status="sending", _send_started=history.utc_now(), _send_key="key-12345678")
    response = send(client, historyId=record["id"])
    assert response.status_code == 409
    assert response.get_json()["code"] == "send_in_progress"
    assert fake_gmail.sent == []


def test_send_uses_the_edited_draft(client, fake_gmail):
    record = history.add_activity(status="draft", subject="Old", body="Old body", recipient="old@example.com")
    response = send(client, historyId=record["id"], subject="Edited subject", body="Edited body")
    assert response.status_code == 200
    assert fake_gmail.sent[0]["Subject"] == "Edited subject"
    stored = history.get_activity(record["id"])
    assert (stored["subject"], stored["body"], stored["recipient"]) == ("Edited subject", "Edited body", "careers@example.com")


def test_missing_idempotency_key(client, fake_gmail):
    response = client.post(SEND, json={"to": "a@b.com"}, headers=APP_HEADERS)
    assert response.status_code == 400


def test_send_requires_app_header(client, fake_gmail):
    response = client.post(SEND, json={}, headers={"Idempotency-Key": "key-12345678"})
    assert response.status_code == 403
    assert fake_gmail.sent == []


def test_send_rate_limited(client, fake_gmail):
    for index in range(20):
        assert send(client, key=f"key-{index:08d}").status_code == 200
    response = send(client, key="key-overflow")
    assert response.status_code == 429


def test_saved_draft_edits_and_sent_lock(client):
    record = history.add_activity(status="draft", subject="S", body="B", recipient="a@b.com")
    response = client.patch(f"/api/update-activity/{record['id']}", json={"subject": "New", "body": "New body", "attachResume": True}, headers=APP_HEADERS)
    assert response.status_code == 200
    assert history.get_activity(record["id"])["subject"] == "New"
    history.update_activity(record["id"], status="sent")
    response = client.patch(f"/api/update-activity/{record['id']}", json={"body": "changed"}, headers=APP_HEADERS)
    assert response.status_code == 409
