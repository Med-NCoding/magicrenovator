from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import redis
import fakeredis
from fastapi import Cookie, Depends, Header, Request, Response

from app.domain.errors import AppError
from app.settings import Settings, get_settings

SESSION_COOKIE_NAME = "rp_session"
_fake_redis_instance: Any = None


def hash_token(raw_token: str, secret: str = "") -> str:
    if secret:
        return hmac.new(secret.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@contextmanager
def get_db_conn(settings: Settings | None = None) -> Generator[Any, None, None]:
    cfg = settings or get_settings()
    conn = psycopg2.connect(cfg.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_migrations(settings: Settings | None = None) -> list[str]:
    cfg = settings or get_settings()
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    applied: list[str] = []
    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for sql_file in sorted(migrations_dir.glob("*.sql")):
                cur.execute("SELECT 1 FROM schema_migrations WHERE filename = %s", (sql_file.name,))
                if cur.fetchone() is None:
                    sql_text = sql_file.read_text(encoding="utf-8")
                    cur.execute(sql_text)
                    cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (sql_file.name,))
                    applied.append(sql_file.name)
    return applied


def get_redis_client(settings: Settings | None = None) -> Any:
    global _fake_redis_instance
    cfg = settings or get_settings()
    if cfg.REDIS_URL.startswith("memory://") or cfg.REDIS_URL.startswith("fakeredis://"):
        if _fake_redis_instance is None:
            _fake_redis_instance = fakeredis.FakeStrictRedis(decode_responses=True)
        return _fake_redis_instance
    return redis.Redis.from_url(cfg.REDIS_URL, decode_responses=True)


class SessionOwner:
    def __init__(self, id_hash: str, csrf_token: str, expires_at: datetime, raw_token: str | None = None) -> None:
        self.id_hash = id_hash
        self.csrf_token = csrf_token
        self.expires_at = expires_at
        self.raw_token = raw_token


def create_or_refresh_session(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> SessionOwner:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    now = datetime.now(timezone.utc)
    if raw_token:
        id_hash = hash_token(raw_token, settings.SESSION_SIGNING_SECRET)
        with get_db_conn(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id_hash, csrf_token, expires_at FROM sessions WHERE id_hash = %s",
                    (id_hash,),
                )
                row = cur.fetchone()
                if row and row["expires_at"] > now:
                    return SessionOwner(
                        id_hash=row["id_hash"],
                        csrf_token=row["csrf_token"],
                        expires_at=row["expires_at"],
                    )

    new_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    id_hash = hash_token(new_token, settings.SESSION_SIGNING_SECRET)
    expires_at = now + timedelta(days=settings.ANONYMOUS_RETENTION_DAYS)

    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (id_hash, csrf_token, created_at, expires_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id_hash) DO UPDATE SET expires_at = EXCLUDED.expires_at
                """,
                (id_hash, csrf_token, now, expires_at),
            )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=(settings.APP_ENV in {"staging", "production"}),
        max_age=settings.ANONYMOUS_RETENTION_DAYS * 86400,
        path="/",
    )
    return SessionOwner(id_hash=id_hash, csrf_token=csrf_token, expires_at=expires_at, raw_token=new_token)


def require_owner(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionOwner:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise AppError(
            code="expired_session",
            message="Your session has expired. Refresh to start or continue a session.",
            status_code=401,
            retryable=True,
            next_action="create_session",
        )
    id_hash = hash_token(raw_token, settings.SESSION_SIGNING_SECRET)
    now = datetime.now(timezone.utc)
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_hash, csrf_token, expires_at FROM sessions WHERE id_hash = %s",
                (id_hash,),
            )
            row = cur.fetchone()
            if not row or row["expires_at"] <= now:
                raise AppError(
                    code="expired_session",
                    message="Your session has expired. Refresh to start a new session.",
                    status_code=401,
                    retryable=True,
                    next_action="create_session",
                )
            return SessionOwner(
                id_hash=row["id_hash"],
                csrf_token=row["csrf_token"],
                expires_at=row["expires_at"],
            )


def require_csrf(
    request: Request,
    owner: SessionOwner = Depends(require_owner),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> SessionOwner:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if origin and host:
            parsed_origin = urlparse(origin)
            origin_host = parsed_origin.netloc.split(":")[0]
            req_host = host.split(":")[0]
            if origin_host not in {req_host, "localhost", "127.0.0.1"}:
                raise AppError(
                    code="csrf_invalid",
                    message="Cross-origin mutation request rejected.",
                    status_code=403,
                    retryable=False,
                    next_action="reload_page",
                )
        if not x_csrf_token or not hmac.compare_digest(x_csrf_token, owner.csrf_token):
            raise AppError(
                code="csrf_invalid",
                message="Missing or invalid CSRF token. Reload the page and try again.",
                status_code=403,
                retryable=True,
                next_action="create_session",
            )
    return owner


def enforce_rate_limit(
    request: Request,
    owner_id_hash: str,
    bucket: str,
    limit: int = 30,
    window_seconds: int = 60,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    r = get_redis_client(cfg)
    client_ip = request.client.host if request.client else "unknown"
    key = f"rl:{bucket}:{owner_id_hash[:16]}:{client_ip}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, window_seconds)
    if count > limit:
        raise AppError(
            code="rate_limited",
            message="Too many requests in a short window. Please wait a moment before trying again.",
            status_code=429,
            retryable=True,
            next_action="wait_and_retry",
        )


def get_gateway(settings: Settings = Depends(get_settings)) -> Any:
    from app.gateways.magic_hour import MagicHourGateway

    return MagicHourGateway(base_url=settings.MAGIC_HOUR_BASE_URL)


