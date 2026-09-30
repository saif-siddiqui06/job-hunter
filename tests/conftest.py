import io
import os
import sys

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_SKIP_DOTENV", "1")  # tests never read your real keys

import accounts  # noqa: E402
import app as app_module  # noqa: E402
import email_assistant  # noqa: E402
from services import ai, extraction, gmail, storage, users  # noqa: E402

APP_HEADERS = {"X-Requested-With": "ApplyRocket"}


TEST_USER = "tester"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own data dir, no real OCR, no real AI and fresh rate limits.

    Yields the signed-in test user's data folder (what data_path() resolves to)."""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SIGNUP_CODE", raising=False)
    storage.set_scope(TEST_USER)
    accounts.login_limiter.reset()
    monkeypatch.setattr(extraction, "run_ocr", lambda _data: None)
    monkeypatch.setattr(ai, "generate_json", _no_ai)
    monkeypatch.setattr(ai, "is_available", lambda require_vision=False: False)
    email_assistant.ai_limiter.reset()
    email_assistant.send_limiter.reset()
    email_assistant.connect_limiter.reset()
    yield tmp_path / "users" / TEST_USER
    storage.set_scope(None)


def _no_ai(_request):
    raise ai.AIUnavailable("AI generation is temporarily unavailable.")


@pytest.fixture
def anonymous_client():
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def client(anonymous_client):
    """A test client signed in as TEST_USER."""
    users.create(TEST_USER, "password123")
    with anonymous_client.session_transaction() as session:
        session["user_id"] = TEST_USER
    return anonymous_client


class FakeAI:
    """Stands in for every provider. Queue responses (dicts) or exceptions; records the requests."""

    def __init__(self):
        self.responses = []
        self.requests = []

    def queue(self, *responses):
        self.responses.extend(responses)

    def __call__(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response, "fake"


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(ai, "generate_json", fake)
    monkeypatch.setattr(ai, "is_available", lambda require_vision=False: True)
    return fake


class FakeGmail:
    def __init__(self):
        self.sent = []
        self.fail_with = None

    def __call__(self, message):
        if self.fail_with:
            raise self.fail_with
        self.sent.append(message)
        return f"msg-{len(self.sent)}"


@pytest.fixture
def fake_gmail(monkeypatch):
    fake = FakeGmail()
    monkeypatch.setattr(gmail, "connection", lambda: {"method": "google", "account": "me@gmail.com"})
    monkeypatch.setattr(gmail, "is_connected", lambda: True)
    monkeypatch.setattr(gmail, "connected_account", lambda: "me@gmail.com")
    monkeypatch.setattr(gmail, "send_connected", fake)
    return fake


def extraction_response(**overrides):
    base = {
        "recipient_email": None,
        "recipient_name": None,
        "company_name": None,
        "job_title": None,
        "email_type": "job_application",
        "purpose": "",
        "important_details": [],
        "requested_subject": None,
        "resume_requested": False,
        "emails_seen": [],
        "suspicious_instructions": False,
        "transcript": "",
        "confidence": {"recipient_email": 0.0, "company_name": 0.0, "job_title": 0.0},
    }
    base.update(overrides)
    return base


def make_png(text="Please send your resume to careers@example.com", size=(640, 200)):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((10, 10), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_pdf():
    return b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
