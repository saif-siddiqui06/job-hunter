"""Provider request construction, profile/resume handling and Gmail helpers."""
import base64
import io
import json

import pytest
from flask import Flask

from conftest import APP_HEADERS, make_pdf
from services import ai, gmail
from services.ai import GeminiProvider, OllamaProvider, OpenAIProvider, StructuredRequest, to_gemini_schema
from services.extraction import EXTRACTION_SCHEMA


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class Recorder(list):
    """Records requests.post calls and replays queued responses."""

    def __init__(self):
        super().__init__()
        self.responses = []

    def __call__(self, url, **kwargs):
        self.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture
def captured(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(ai.requests, "post", recorder)
    return recorder


def request_with_image():
    return StructuredRequest(system="sys", prompt="prompt", schema={"type": "object", "properties": {}, "required": []},
                             schema_name="x", image=b"img", image_mime="image/png")


# ---- Providers --------------------------------------------------------------

def test_gemini_request_and_parse(monkeypatch, captured):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    captured.responses.append(FakeResponse({"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": '{"ok": true}'}]}}]}))
    assert GeminiProvider().generate_json(request_with_image()) == {"ok": True}
    url, kwargs = captured[0]
    assert url.endswith("/gemini-flash-latest:generateContent")
    assert kwargs["headers"] == {"x-goog-api-key": "gk"}
    body = kwargs["json"]
    assert body["contents"][0]["parts"][0]["inlineData"] == {"mimeType": "image/png", "data": base64.b64encode(b"img").decode()}
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_falls_back_to_lighter_model_when_busy(monkeypatch, captured):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    captured.responses.extend([
        FakeResponse({"error": "overloaded"}, status=503),
        FakeResponse({"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]}),
    ])
    assert GeminiProvider().generate_json(request_with_image()) == {"ok": 1}
    assert captured[1][0].endswith("/gemini-flash-lite-latest:generateContent")


def test_openai_request_uses_strict_json_schema(monkeypatch, captured):
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    captured.responses.append(FakeResponse({"choices": [{"message": {"content": '{"a": 1}'}}]}))
    assert OpenAIProvider().generate_json(request_with_image()) == {"a": 1}
    url, kwargs = captured[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer ok"
    body = kwargs["json"]
    assert body["model"] == "test-model"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ollama_uses_legacy_url_and_vision_model(monkeypatch, captured):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    monkeypatch.setenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
    captured.responses.append(FakeResponse({"message": {"content": '{"b": 2}'}}))
    assert OllamaProvider().generate_json(request_with_image()) == {"b": 2}
    url, kwargs = captured[0]
    assert url == "http://localhost:11434/api/chat"
    assert kwargs["json"]["model"] == "llama3.2-vision"
    assert kwargs["json"]["messages"][1]["images"] == [base64.b64encode(b"img").decode()]


def test_ollama_is_opt_in(monkeypatch):
    for name in ("OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_VISION_MODEL", "AI_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    assert not OllamaProvider().is_configured()  # no ~2 s localhost probe for people without Ollama
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    assert OllamaProvider().is_configured() and not OllamaProvider().supports_vision


def test_generic_ai_variables_configure_the_selected_provider(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_API_KEY", "generic")
    assert GeminiProvider().is_configured()
    assert [p.name for p in ai.provider_chain()] == ["gemini"]


def test_provider_chain_falls_back_and_reports_unavailable(monkeypatch):
    monkeypatch.undo()  # use the real generate_json
    monkeypatch.setenv("AI_PROVIDER", "auto")
    calls = []

    class Broken(ai.Provider):
        def __init__(self, name):
            self.name = name

        def is_configured(self):
            return True

        def generate_json(self, request):
            calls.append(self.name)
            raise ai.ProviderError("boom")

    monkeypatch.setattr(ai, "PROVIDERS", {name: Broken(name) for name in ai.AUTO_ORDER})
    with pytest.raises(ai.AIUnavailable, match="temporarily unavailable"):
        ai.generate_json(StructuredRequest(system="s", prompt="p", schema={}, schema_name="n"))
    assert calls == list(ai.AUTO_ORDER)


def test_ai_provider_none_disables_ai(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("AI_PROVIDER", "none")
    with pytest.raises(ai.AIUnavailable, match="not configured"):
        ai.generate_json(StructuredRequest(system="s", prompt="p", schema={}, schema_name="n"))


def test_gemini_schema_conversion():
    schema = to_gemini_schema(EXTRACTION_SCHEMA)
    assert schema["type"] == "OBJECT"
    assert schema["properties"]["recipient_email"] == {"type": "STRING", "nullable": True}
    assert schema["properties"]["important_details"]["items"] == {"type": "STRING"}
    assert "additionalProperties" not in schema


def test_extraction_schema_is_strict_mode_compatible():
    def check(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                check(child)
    check(EXTRACTION_SCHEMA)


# ---- Profile & resume ----------------------------------------------------------

def test_profile_round_trip_and_validation(client):
    response = client.put("/api/profile", json={"fullName": "  Saif   Siddiqui ", "linkedinUrl": "linkedin.com/in/saif", "skills": "SQL, Python, SQL"}, headers=APP_HEADERS)
    profile = response.get_json()["profile"]
    assert profile["fullName"] == "Saif Siddiqui"
    assert profile["linkedinUrl"] == "https://linkedin.com/in/saif"
    assert profile["skills"] == ["SQL", "Python"]
    assert client.put("/api/profile", json={"email": "nope"}, headers=APP_HEADERS).status_code == 400
    assert client.put("/api/profile", json={"phone": "call me"}, headers=APP_HEADERS).status_code == 400


def test_resume_upload_validation(client, isolated):
    fake_pdf = {"resume": (io.BytesIO(b"not a pdf"), "resume.pdf", "application/pdf")}
    assert client.post("/api/profile/resume", data=fake_pdf, headers=APP_HEADERS, content_type="multipart/form-data").status_code == 415
    exe = {"resume": (io.BytesIO(b"MZ..."), "resume.exe", "application/octet-stream")}
    assert client.post("/api/profile/resume", data=exe, headers=APP_HEADERS, content_type="multipart/form-data").status_code == 415

    evil_name = {"resume": (io.BytesIO(make_pdf()), "../../etc/My Resume.pdf", "application/pdf")}
    response = client.post("/api/profile/resume", data=evil_name, headers=APP_HEADERS, content_type="multipart/form-data")
    assert response.status_code == 200
    assert response.get_json()["profile"]["resume"]["filename"] == "My_Resume.pdf"
    stored = list((isolated / "uploads" / "resume").iterdir())
    assert len(stored) == 1 and stored[0].name.endswith("-My_Resume.pdf")

    response = client.delete("/api/profile/resume", headers=APP_HEADERS)
    assert response.get_json()["profile"]["resume"] is None
    assert list((isolated / "uploads" / "resume").iterdir()) == []


def test_profile_never_exposes_storage_path(client):
    client.post("/api/profile/resume", data={"resume": (io.BytesIO(make_pdf()), "cv.pdf", "application/pdf")},
                headers=APP_HEADERS, content_type="multipart/form-data")
    resume = client.get("/api/profile").get_json()["profile"]["resume"]
    assert set(resume) == {"filename", "size", "uploadedAt"}


# ---- Gmail ------------------------------------------------------------------------

def test_build_message_rejects_header_injection():
    with pytest.raises(ValueError):
        gmail.build_message("me@gmail.com", "a@b.com", "Hi\nBcc: evil@x.com", "body")


def test_build_message_is_seven_bit_safe_with_unicode():
    message = gmail.build_message("me@gmail.com", "a@b.com", "Candidature – Développeur", "Merci beaucoup — à bientôt", sender_name="Saïf")
    raw = message.as_bytes()
    assert raw.decode("ascii")  # safe for SMTP and the Gmail API
    assert message.get_content().strip() == "Merci beaucoup — à bientôt"


class FakeCredentials:
    token = "access"
    refresh_token = "refresh-secret"
    token_uri = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/gmail.send"]
    id_token = "h." + base64.urlsafe_b64encode(json.dumps({"email": "me@gmail.com"}).encode()).decode().rstrip("=") + ".s"


def test_oauth_tokens_are_stored_server_side(isolated, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session

        gmail.store_credentials(FakeCredentials())
        cookie_session = json.dumps(dict(session))
        assert "refresh-secret" not in cookie_session and "csecret" not in cookie_session
        assert gmail.is_connected() and gmail.connected_account() == "me@gmail.com"
        stored = json.loads((isolated / ".gmail_tokens.json").read_text())
        assert "client_secret" not in json.dumps(stored)
        credentials = gmail.load_credentials()
        assert credentials.refresh_token == "refresh-secret" and credentials.client_secret == "csecret"
        gmail.forget_credentials()
        assert not gmail.is_connected()
        assert json.loads((isolated / ".gmail_tokens.json").read_text()) == {}


def test_legacy_cookie_tokens_are_migrated(isolated):
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session

        session["google_credentials"] = {"token": "t", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": []}
        assert gmail.is_connected()
        assert "google_credentials" not in session
        assert gmail.load_credentials().refresh_token == "r"


def test_auth_status_reports_account(client, monkeypatch):
    monkeypatch.setattr(gmail, "connection", lambda: {"method": "google", "account": "me@gmail.com"})
    data = client.get("/auth/status").get_json()
    assert data["connected"] is True and data["method"] == "google"
    assert data["googleConnected"] is True and data["googleAccount"] == "me@gmail.com"


def test_google_sign_in_without_setup_redirects_back(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    response = client.get("/auth/google/start")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/?google_auth=missing_config")


def test_google_sign_in_denied_redirects_back(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    response = client.get("/auth/google/callback?error=access_denied")
    assert response.headers["Location"].endswith("/?google_auth=denied")


def test_request_too_large_returns_json(client):
    response = client.post("/api/email-assistant/extract", data=b"x" * (13 * 1024 * 1024), headers={**APP_HEADERS, "Content-Type": "application/octet-stream"})
    assert response.status_code == 413
    assert "maximum allowed size" in response.get_json()["error"]
