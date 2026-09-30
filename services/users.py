"""Accounts: username + password, stored in users.json. Each user's data lives in users/<username>/."""
import hmac
import os
import shutil

from werkzeug.security import check_password_hash, generate_password_hash

from services.history import utc_now
from services.storage import USER_ID_PATTERN, locked, read_json, root_path, write_json

MIN_PASSWORD = 8
# Single-user data from before accounts existed; handed to the first account created.
LEGACY_FILES = ("profile.json", "activity.json", "uploads", ".gmail_tokens.json")


class AccountError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _path():
    return root_path("users.json")


def _load():
    users = read_json(_path(), {})
    return users if isinstance(users, dict) else {}


def normalize(username):
    return (username or "").strip().lower() if isinstance(username, str) else ""


def signup_code_required():
    return bool(os.environ.get("SIGNUP_CODE"))


def _adopt_legacy_data(user_id):
    target = root_path("users", user_id)
    os.makedirs(target, exist_ok=True)
    for name in LEGACY_FILES:
        source = root_path(name)
        if os.path.exists(source) and not os.path.exists(os.path.join(target, name)):
            shutil.move(source, os.path.join(target, name))


def create(username, password, invite_code=""):
    user_id = normalize(username)
    if not USER_ID_PATTERN.match(user_id):
        raise AccountError("Usernames are 3-32 characters: letters, numbers and underscores.")
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    expected = os.environ.get("SIGNUP_CODE", "")
    if expected and not hmac.compare_digest(str(invite_code or "").strip(), expected):
        raise AccountError("That invite code isn't right. Ask the person who runs this app for it.", 403)

    with locked():
        users = _load()
        if user_id in users:
            raise AccountError("That username is taken.", 409)
        first = not users
        users[user_id] = {"password_hash": generate_password_hash(password), "created_at": utc_now()}
        write_json(_path(), users)
        if first:
            _adopt_legacy_data(user_id)
    os.makedirs(root_path("users", user_id), exist_ok=True)
    return user_id


def authenticate(username, password):
    user_id = normalize(username)
    user = _load().get(user_id)
    # Always run a hash check so timing doesn't reveal which usernames exist.
    stored = user["password_hash"] if user else generate_password_hash("not-a-real-password")
    if not check_password_hash(stored, password or "") or not user:
        raise AccountError("Wrong username or password.", 401)
    return user_id


def exists(user_id):
    return bool(user_id) and user_id in _load()
