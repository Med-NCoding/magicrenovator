from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import assets, briefs, connection, exports, generations, projects, quotes, rooms
from app.dependencies import (
    SessionOwner,
    apply_migrations,
    create_or_refresh_session,
    get_db_conn,
    get_redis_client,
)
from app.domain.errors import AppError, ErrorEnvelope, SafeErrorBody, redact_secrets
from app.domain.schemas import SessionResponse
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    import asyncio
    from app.workers.runner import run_worker_once

    settings = get_settings()
    settings.resolved_asset_dir()
    apply_migrations(settings)

    worker_task: asyncio.Task[None] | None = None
    if settings.APP_ENV != "test":
        async def _bg_worker() -> None:
            while True:
                try:
                    await run_worker_once(settings=settings)
                except Exception:
                    pass
                await asyncio.sleep(0.25)

        worker_task = asyncio.create_task(_bg_worker())

    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="magicrenovator API",
    version="0.1.0",
    description="Renovation Concept Visualization API with Magic Hour BYOK",
    lifespan=lifespan,
)


@app.middleware("http")
async def correlation_and_security_middleware(request: Request, call_next: Any) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID") or f"req_{secrets.token_hex(8)}"
    request.state.correlation_id = correlation_id
    response: Response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", f"req_{secrets.token_hex(8)}")
    envelope = exc.to_envelope(correlation_id)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope.model_dump(),
        headers={"X-Correlation-ID": correlation_id},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", f"req_{secrets.token_hex(8)}")
    safe_msg = "Invalid request input. Please check the fields and try again."
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        msg = err.get("msg", "")
        if loc and "key" not in loc.lower():
            safe_msg = redact_secrets(f"Invalid {loc}: {msg}")
            break
    envelope = ErrorEnvelope(
        error=SafeErrorBody(
            code="validation_error",
            message=safe_msg,
            retryable=False,
            next_action="fix_input",
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(
        status_code=422,
        content=envelope.model_dump(),
        headers={"X-Correlation-ID": correlation_id},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", f"req_{secrets.token_hex(8)}")
    envelope = ErrorEnvelope(
        error=SafeErrorBody(
            code="internal_error",
            message="An unexpected error occurred. No additional paid requests were sent.",
            retryable=True,
            next_action="contact_support",
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(
        status_code=500,
        content=envelope.model_dump(),
        headers={"X-Correlation-ID": correlation_id},
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness_check(settings: Settings = Depends(get_settings)) -> JSONResponse:
    try:
        with get_db_conn(settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        r = get_redis_client(settings)
        r.ping()
        if not settings.resolved_catalog_path().exists():
            raise RuntimeError("Catalog file missing")
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "gateway_mode": settings.GATEWAY_MODE,
                "pause_generations": settings.PAUSE_GENERATIONS,
            },
        )
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready"},
        )


@app.post("/api/session", response_model=SessionResponse)
def create_session_endpoint(
    owner: SessionOwner = Depends(create_or_refresh_session),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    return SessionResponse(
        session_active=True,
        csrf_token=owner.csrf_token,
        expires_at=owner.expires_at.isoformat(),
        retention_days=settings.ANONYMOUS_RETENTION_DAYS,
        gateway_mode=settings.GATEWAY_MODE,
    )


app.include_router(connection.router)
app.include_router(projects.router)
app.include_router(rooms.router)
app.include_router(assets.router)
app.include_router(briefs.router)
app.include_router(quotes.router)
app.include_router(generations.router)
app.include_router(exports.router)
