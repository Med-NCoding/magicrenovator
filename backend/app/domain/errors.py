from __future__ import annotations

import re
from typing import Literal, Optional
from pydantic import BaseModel

ErrorCode = Literal[
    "not_connected",
    "invalid_key",
    "insufficient_credits",
    "unsupported_model",
    "unsupported_option",
    "invalid_image",
    "invalid_brief",
    "stale_quote",
    "rate_limited",
    "provider_unavailable",
    "unknown_submission",
    "submission_unknown",
    "save_failed",
    "expired_session",
    "not_found",
    "conflict",
    "unresolved_brief",
    "csrf_invalid",
    "generations_paused",
    "room_limit_reached",
    "concurrency_limit_reached",
    "validation_error",
    "internal_error",
]

_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"mhk_[A-Za-z0-9_\-]+", re.IGNORECASE),
    re.compile(r"https?://[^\s\"']+\?[^\s\"']+", re.IGNORECASE),
    re.compile(r"/var/lib/renopreview[^\s\"']*", re.IGNORECASE),
    re.compile(r"/Users/[^\s\"']+", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    if not text:
        return ""
    cleaned = str(text)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


class SafeErrorBody(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    next_action: str
    correlation_id: str


class ErrorEnvelope(BaseModel):
    error: SafeErrorBody


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
        next_action: str = "none",
    ) -> None:
        super().__init__(redact_secrets(message))
        self.code: ErrorCode = code
        self.message: str = redact_secrets(message)
        self.status_code: int = status_code
        self.retryable: bool = retryable
        self.next_action: str = next_action

    def to_envelope(self, correlation_id: str) -> ErrorEnvelope:
        return ErrorEnvelope(
            error=SafeErrorBody(
                code=self.code,
                message=redact_secrets(self.message),
                retryable=self.retryable,
                next_action=self.next_action,
                correlation_id=correlation_id,
            )
        )
