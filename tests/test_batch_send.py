"""Regression tests for the original batch sender (/send), which now shares the Gmail helpers."""
import io
import json

import app as app_module
from services import gmail


class FakeSMTP:
    instances = []

    def __init__(self, *args, **kwargs):
        self.sent = []
        FakeSMTP.instances.append(self)

    def login(self, user, password):
        self.login_args = (user, password)

    def sendmail(self, sender, recipient, message):
        self.sent.append((sender, recipient, message))

    def quit(self):
        pass


def batch_form(**extra):
    return {
        "email": "me@gmail.com",
        "password": "abcd efgh ijkl mnop",
        "subject": "Software Engineer – open to opportunities",
        "message": "Hi,\n\nI'd love to connect — résumé attached.\n\nBest,\nSaif",
        "csv": (io.BytesIO(b"email,name\na@x.com,A\nb@y.com,B\n"), "r.csv"),
        "resume": (io.BytesIO(b"%PDF-1.4 resume"), "cv.pdf"),
        **extra,
    }


def events(response):
    return [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]


def test_batch_send_via_app_password(client, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(app_module.smtplib, "SMTP_SSL", FakeSMTP)
    response = client.post("/send", data=batch_form(), content_type="multipart/form-data")
    assert events(response)[-1] == {"type": "done", "success": True, "count": 2, "failed": 0, "total": 2, "percent": 100}
    smtp = FakeSMTP.instances[0]
    assert smtp.login_args == ("me@gmail.com", "abcdefghijklmnop")
    raw = smtp.sent[0][2]
    raw.encode("ascii")  # unicode subject/body are MIME-encoded, so SMTP never sees raw non-ASCII
    assert 'filename="cv.pdf"' in raw and "Content-Type: application/pdf" in raw


def test_batch_send_via_google(client, monkeypatch):
    sent = []

    class FakeService:
        def users(self):
            return self

        def messages(self):
            return self

        def send(self, userId, body):
            sent.append(body["raw"])
            return self

        def execute(self):
            return {"id": "x"}

    monkeypatch.setattr(gmail, "load_credentials", lambda: object())
    monkeypatch.setattr(app_module, "build", lambda *args, **kwargs: FakeService())
    response = client.post("/send", data=batch_form(auth_method="google", password=""), content_type="multipart/form-data")
    assert events(response)[-1]["count"] == 2
    assert len(sent) == 2


def test_batch_send_with_connected_app_password_and_profile_resume(client, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(app_module.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(gmail, "connection", lambda: {"method": "app_password", "account": "me@gmail.com"})
    monkeypatch.setattr(gmail, "app_password_credentials", lambda: ("me@gmail.com", "abcdefghijklmnop"))
    client.post("/api/profile/resume", data={"resume": (io.BytesIO(b"%PDF-1.4\n%%EOF"), "Profile_CV.pdf")},
                headers={"X-Requested-With": "ApplyRocket"}, content_type="multipart/form-data")

    form = batch_form(auth_method="connected", email="", password="", use_profile_resume="1")
    del form["resume"]
    response = client.post("/send", data=form, content_type="multipart/form-data")
    assert events(response)[-1]["count"] == 2
    smtp = FakeSMTP.instances[0]
    assert smtp.login_args == ("me@gmail.com", "abcdefghijklmnop")
    assert 'filename="Profile_CV.pdf"' in smtp.sent[0][2]


def test_batch_send_connected_requires_connection(client):
    response = client.post("/send", data=batch_form(auth_method="connected", email="", password=""), content_type="multipart/form-data")
    assert response.status_code == 401


def test_batch_send_google_requires_sign_in(client):
    response = client.post("/send", data=batch_form(auth_method="google", password=""), content_type="multipart/form-data")
    assert response.status_code == 401
