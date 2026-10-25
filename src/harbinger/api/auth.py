"""Optional single-worker authentication. Opaque, bounded, revocable server sessions."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

COOKIE = "harbinger_session"
SAFE = {"GET", "HEAD", "OPTIONS"}
router = APIRouter(prefix="/auth", tags=["auth"])


def password_hash(password: str, salt: str | None = None) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12–256 characters")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt$16384$8$1${salt}${digest}"


def valid_hash(value: str) -> bool:
    return bool(re.fullmatch(r"scrypt\$16384\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{128}", value))


def verify_password(password: str, value: str) -> bool:
    if not 12 <= len(password) <= 256 or not valid_hash(value):
        return False
    return hmac.compare_digest(password_hash(password, value.split("$")[4]), value)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    sites: frozenset[str]


@dataclass
class LoginSession:
    principal: Principal
    expires: float
    csrf: str


class AuthManager:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.sessions: dict[str, LoginSession] = {}
        self.attempts: dict[str, list[float]] = {}
        self.users = {}
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))
        if not settings.protected_mode:
            return
        if not settings.auth_users_file or not settings.auth_origin:
            raise RuntimeError("Protected mode requires auth_users_file and auth_origin")
        from urllib.parse import urlsplit

        origin = urlsplit(settings.auth_origin)
        if (
            origin.scheme not in {"https", "http"}
            or not origin.netloc
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or (origin.scheme != "https" and settings.auth_cookie_secure)
        ):
            raise RuntimeError(
                "auth_origin must be an exact HTTPS origin (HTTP only with explicit insecure cookie override)"
            )
        try:
            path = settings.auth_users_file
            if path.stat().st_mode & 0o077:
                raise ValueError("Account file permissions must be 0600")
            if path.stat().st_size > 1024 * 1024:
                raise ValueError("Account file too large")
            records = json.loads(path.read_text())
            if not isinstance(records, list) or not 1 <= len(records) <= 1000:
                raise ValueError("Expected 1–1000 users")
            for item in records:
                username, role, sites = item["username"], item["role"], item["sites"]
                if (
                    not isinstance(username, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", username)
                    or username in self.users
                    or role not in {"admin", "operator", "viewer"}
                    or not isinstance(sites, list)
                    or len(sites) > 1000
                    or any(
                        not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", s) for s in sites
                    )
                    or (role != "admin" and not sites)
                    or not valid_hash(item["password_hash"])
                    or set(item) != {"username", "role", "sites", "password_hash"}
                ):
                    raise ValueError("Invalid account")
                self.users[username] = (Principal(username, role, frozenset(sites)), item["password_hash"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("Invalid protected-mode account configuration") from exc

    def cleanup(self):
        now = time.monotonic()
        for token, session in list(self.sessions.items()):
            if session.expires <= now:
                self.revoke(token)
        self.attempts = {
            k: [t for t in v if t > now - 300]
            for k, v in self.attempts.items()
            if any(t > now - 300 for t in v)
        }

    def revoke(self, token):
        self.sessions.pop(token, None)
        from harbinger.api.routers import workbench

        with workbench.lock:
            for key, session in list(workbench.sessions.items()):
                if session.owner == token:
                    del workbench.sessions[key]

    def lookup(self, token):
        with self.lock:
            self.cleanup()
            return self.sessions.get(token)

    def login(self, username, password, address):
        with self.lock:
            self.cleanup()
            # Bound both guessing and process memory. No proxy headers are trusted.
            keys = ("ip:" + address, "user:" + username)
            if len(self.attempts) >= 2048 and any(k not in self.attempts for k in keys):
                raise HTTPException(429, "Login temporarily unavailable")
            if any(len(self.attempts.get(k, [])) >= 10 for k in keys):
                raise HTTPException(429, "Too many login attempts; retry in five minutes")
            for key in keys:
                self.attempts.setdefault(key, []).append(time.monotonic())
            record = self.users.get(username)
            matched = verify_password(password, record[1] if record else self.dummy_hash)
            if not record or not matched:
                raise HTTPException(401, "Invalid credentials")
            if len(self.sessions) >= self.settings.auth_max_sessions:
                raise HTTPException(429, "Session capacity reached")
            token = secrets.token_urlsafe(32)
            session = LoginSession(
                record[0], time.monotonic() + self.settings.auth_ttl_seconds, secrets.token_urlsafe(32)
            )
            self.sessions[token] = session
            return token, session


def owner(request: Request) -> str | None:
    return getattr(request.state, "auth_token", None)


def principal(request: Request) -> Principal | None:
    return getattr(request.state, "principal", None)


def admin_path(path: str) -> bool:
    return (
        path in {"/metrics", "/version", "/ready", "/openapi.json"}
        or any(
            path == p or path.startswith(p + "/")
            for p in ("/v1/models", "/v1/admin", "/v1/monitoring", "/v1/artifacts", "/docs", "/redoc")
        )
        or path.endswith("/inspections")
    )


async def enforce_auth(request: Request, call_next):
    settings = request.app.state.auth_settings
    if not settings.protected_mode:
        return await call_next(request)
    manager = getattr(request.app.state, "auth", None)
    if manager is None:
        return JSONResponse({"detail": "Authentication unavailable"}, status_code=503)
    path = request.url.path.rstrip("/") or "/"
    metrics_token = settings.auth_metrics_token
    if path == "/metrics" and request.method == "GET" and metrics_token is not None:
        expected = "Bearer " + metrics_token.get_secret_value()
        if hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
    # Static pages contain no tenant records. All API routes remain behind this boundary.
    public = path == "/health" or path.startswith("/console/") and not path.endswith(".json")
    public = public or path in {"/", "/console", "/auth/login"}
    token = request.cookies.get(COOKIE, "")
    session = manager.lookup(token)
    if not public and not session:
        return JSONResponse({"detail": "Login required"}, status_code=401)
    if request.method not in SAFE:
        if request.headers.get("origin") != settings.auth_origin:
            return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        if path != "/auth/login":
            if not session or not hmac.compare_digest(
                request.headers.get("x-csrf-token", "").encode(), session.csrf.encode()
            ):
                return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    if session:
        request.state.principal = session.principal
        request.state.auth_token = token
        if admin_path(path) and session.principal.role != "admin":
            return JSONResponse({"detail": "Administrator required"}, status_code=403)
        # Viewers may explore examples, text and what-if, but cannot upload or ingest.
        if path == "/v1/workbench/upload" and session.principal.role == "viewer":
            return JSONResponse({"detail": "Operator required"}, status_code=403)
    if path in {"/", "/console"} and not session:
        return RedirectResponse("/console/login.html")
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256, repr=False)


@router.post("/login")
async def login(request: Request):
    if not request.app.state.auth_settings.protected_mode:
        raise HTTPException(404, "Protected mode is disabled")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 4096:
            raise HTTPException(413, "Login request too large")
    try:
        body = Credentials.model_validate_json(content)
    except ValueError:
        raise HTTPException(422, "Invalid login request") from None
    manager = request.app.state.auth
    token, session = await run_in_threadpool(
        manager.login, body.username, body.password, request.client.host if request.client else "unknown"
    )
    old_token = request.cookies.get(COOKIE)
    if old_token:
        with manager.lock:
            manager.revoke(old_token)
    response = JSONResponse({"username": session.principal.username, "csrf_token": session.csrf})
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=manager.settings.auth_cookie_secure,
        samesite="strict",
        max_age=manager.settings.auth_ttl_seconds,
        path="/",
    )
    return response


@router.get("/me")
def me(request: Request):
    p = principal(request)
    if p is None:
        return {"protected": False}
    s = request.app.state.auth.lookup(owner(request))
    if s is None:
        raise HTTPException(401, "Login required")
    return {
        "protected": True,
        "username": p.username,
        "role": p.role,
        "sites": sorted(p.sites),
        "csrf_token": s.csrf,
    }


@router.post("/logout")
def logout(request: Request):
    manager = getattr(request.app.state, "auth", None)
    if manager:
        with manager.lock:
            manager.revoke(owner(request))
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(
        COOKIE,
        path="/",
        httponly=True,
        secure=request.app.state.auth_settings.auth_cookie_secure,
        samesite="strict",
    )
    return response
