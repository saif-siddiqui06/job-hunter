"""Sign-up, sign-in and the login wall in front of the whole app."""
from flask import Blueprint, jsonify, redirect, request, send_from_directory, session

from email_assistant import error
from services import users
from services.ratelimit import RateLimiter

bp = Blueprint("accounts", __name__)
login_limiter = RateLimiter(limit=10, window_seconds=600)

PUBLIC_PREFIXES = ("/static/", "/api/auth/")
PUBLIC_PATHS = {"/login", "/healthz", "/favicon.ico"}


def require_login():
    """Blocks everything except the login page, its API and static files until someone signs in."""
    path = request.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return None
    user_id = session.get("user_id")
    if user_id and users.exists(user_id):
        return None
    session.pop("user_id", None)
    if path == "/":
        return redirect("/login")
    return error("Please sign in.", 401, "login_required")


def _start_session(user_id):
    session.clear()  # new session id per sign-in; drops any earlier Gmail session pointer
    session["user_id"] = user_id
    session.permanent = True


@bp.get("/login")
def login_page():
    if session.get("user_id") and users.exists(session["user_id"]):
        return redirect("/")
    return send_from_directory("static", "login.html")


@bp.get("/healthz")
def health():
    return jsonify({"ok": True})


@bp.get("/api/auth/me")
def me():
    user_id = session.get("user_id")
    signed_in = bool(user_id and users.exists(user_id))
    return jsonify({"success": True, "username": user_id if signed_in else None, "signupCodeRequired": users.signup_code_required()})


def _credentials():
    payload = request.get_json(silent=True) or {}
    return payload.get("username"), payload.get("password"), payload.get("inviteCode", "")


@bp.post("/api/auth/signup")
def signup():
    retry_after = login_limiter.check(request.remote_addr or "local")
    if retry_after:
        return error(f"Too many attempts. Try again in {retry_after} seconds.", 429, "rate_limited")
    username, password, invite = _credentials()
    try:
        user_id = users.create(username, password, invite)
    except users.AccountError as exc:
        return error(exc.message, exc.status)
    _start_session(user_id)
    return jsonify({"success": True, "username": user_id})


@bp.post("/api/auth/login")
def login():
    retry_after = login_limiter.check(request.remote_addr or "local")
    if retry_after:
        return error(f"Too many attempts. Try again in {retry_after} seconds.", 429, "rate_limited")
    username, password, _invite = _credentials()
    try:
        user_id = users.authenticate(username, password)
    except users.AccountError as exc:
        return error(exc.message, exc.status)
    _start_session(user_id)
    return jsonify({"success": True, "username": user_id})


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"success": True})
