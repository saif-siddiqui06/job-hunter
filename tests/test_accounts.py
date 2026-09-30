"""Accounts: the login wall, sign-up/sign-in, invite codes and per-user data separation."""
import json

import pytest

from conftest import APP_HEADERS
from services import storage, users


def signup(client, username, password="password123", invite=""):
    return client.post("/api/auth/signup", json={"username": username, "password": password, "inviteCode": invite}, headers=APP_HEADERS)


def login(client, username, password="password123"):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=APP_HEADERS)


def test_everything_requires_sign_in(anonymous_client):
    assert anonymous_client.get("/").headers["Location"].endswith("/login")
    for path in ("/api/profile", "/api/list-activities", "/auth/status"):
        response = anonymous_client.get(path)
        assert response.status_code == 401 and response.get_json()["code"] == "login_required", path
    assert anonymous_client.post("/api/email-assistant/extract", json={"text": "x" * 20}, headers=APP_HEADERS).status_code == 401
    assert anonymous_client.post("/send", data={}).status_code == 401
    # The sign-in page, its API, static files and the health check stay public.
    assert anonymous_client.get("/login").status_code == 200
    assert anonymous_client.get("/healthz").get_json() == {"ok": True}
    assert anonymous_client.get("/static/assistant/app.css").status_code == 200
    assert anonymous_client.get("/api/auth/me").get_json()["username"] is None


def test_signup_login_logout(anonymous_client):
    response = signup(anonymous_client, "Saif_01")
    assert response.status_code == 200 and response.get_json()["username"] == "saif_01"
    assert anonymous_client.get("/api/profile").status_code == 200
    anonymous_client.post("/api/auth/logout", headers=APP_HEADERS)
    assert anonymous_client.get("/api/profile").status_code == 401

    assert login(anonymous_client, "saif_01", "wrong-password").status_code == 401
    assert login(anonymous_client, "nobody", "password123").get_json()["error"] == "Wrong username or password."
    assert login(anonymous_client, "SAIF_01").status_code == 200
    assert anonymous_client.get("/api/auth/me").get_json()["username"] == "saif_01"


@pytest.mark.parametrize("username,password,message", [
    ("ab", "password123", "3-32 characters"),
    ("has space", "password123", "3-32 characters"),
    ("../etc", "password123", "3-32 characters"),
    ("valid_name", "short", "at least 8"),
])
def test_signup_validation(anonymous_client, username, password, message):
    response = signup(anonymous_client, username, password)
    assert response.status_code == 400 and message in response.get_json()["error"]


def test_duplicate_username(anonymous_client):
    signup(anonymous_client, "friend")
    assert signup(anonymous_client, "Friend").status_code == 409


def test_invite_code_required_when_configured(anonymous_client, monkeypatch):
    monkeypatch.setenv("SIGNUP_CODE", "rocket-2026")
    assert anonymous_client.get("/api/auth/me").get_json()["signupCodeRequired"] is True
    assert signup(anonymous_client, "stranger", invite="guess").status_code == 403
    assert signup(anonymous_client, "friend", invite="rocket-2026").status_code == 200


def test_passwords_are_hashed(anonymous_client, isolated):
    signup(anonymous_client, "saif", "super-secret-pass")
    stored = (isolated.parent.parent / "users.json").read_text()
    assert "super-secret-pass" not in stored and "password_hash" in stored


def test_each_user_has_private_data(anonymous_client):
    signup(anonymous_client, "alice")
    anonymous_client.put("/api/profile", json={"fullName": "Alice A"}, headers=APP_HEADERS)
    anonymous_client.post("/api/log-activity", json={"recipient": "a@x.com", "subject": "Alice's email", "body": "b"}, headers=APP_HEADERS)
    anonymous_client.post("/api/auth/logout", headers=APP_HEADERS)

    signup(anonymous_client, "bob")
    assert anonymous_client.get("/api/profile").get_json()["profile"]["fullName"] == ""
    assert anonymous_client.get("/api/list-activities").get_json()["activities"] == []
    assert anonymous_client.get("/auth/status").get_json()["connected"] is False

    anonymous_client.post("/api/auth/logout", headers=APP_HEADERS)
    login(anonymous_client, "alice")
    assert anonymous_client.get("/api/profile").get_json()["profile"]["fullName"] == "Alice A"
    assert anonymous_client.get("/api/list-activities").get_json()["activities"][0]["subject"] == "Alice's email"


def test_first_account_adopts_existing_single_user_data(anonymous_client, isolated):
    root = isolated.parent.parent
    storage.set_scope(None)
    (root / "profile.json").write_text(json.dumps({"fullName": "Existing Me"}))
    (root / "activity.json").write_text(json.dumps([{"id": "old1", "subject": "Old email", "status": "sent"}]))
    signup(anonymous_client, "owner")
    assert anonymous_client.get("/api/profile").get_json()["profile"]["fullName"] == "Existing Me"
    assert anonymous_client.get("/api/list-activities").get_json()["activities"][0]["subject"] == "Old email"
    assert not (root / "profile.json").exists()


def test_login_rate_limited(anonymous_client):
    for _ in range(10):
        login(anonymous_client, "nobody", "wrong-password")
    assert login(anonymous_client, "nobody", "wrong-password").status_code == 429


def test_deleted_user_session_is_rejected(client, isolated):
    (isolated.parent.parent / "users.json").write_text("{}")
    assert client.get("/api/profile").status_code == 401


def test_auth_endpoints_need_app_header(anonymous_client):
    response = anonymous_client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert response.status_code == 403
    assert users.exists("x") is False
