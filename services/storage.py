"""JSON-file persistence shared by the app.

Flask serves requests on several threads, so every read-modify-write goes through `locked()`
and files are replaced atomically (temp file + os.replace) to avoid half-written JSON.
"""
import contextvars
import json
import logging
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager

from flask import has_request_context, session

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.RLock()


USER_ID_PATTERN = re.compile(r"^[a-z0-9_]{3,32}$")
_scope = contextvars.ContextVar("data_scope", default=None)


def data_dir():
    """Where runtime data lives. Defaults to the project root (where activity.json always lived)."""
    return os.environ.get("APP_DATA_DIR") or _PROJECT_ROOT


def set_scope(user_id):
    """Scopes data_path() to a user outside a request (background jobs, tests)."""
    _scope.set(user_id)


def current_user_id():
    if has_request_context() and session.get("user_id"):
        return session["user_id"]
    return _scope.get()


def root_path(*parts):
    """App-wide files (accounts, secret key), never per user."""
    return os.path.join(data_dir(), *parts)


def data_path(*parts):
    """Per-user files (profile, resume, history, Gmail connection) for the signed-in user."""
    user_id = current_user_id()
    if user_id and USER_ID_PATTERN.match(user_id):
        return os.path.join(data_dir(), "users", user_id, *parts)
    return os.path.join(data_dir(), *parts)


@contextmanager
def locked():
    with _lock:
        yield


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", os.path.basename(path), exc)
        return default


def write_json(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        # Windows/OneDrive can briefly hold the target open; retry the swap a few times.
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
