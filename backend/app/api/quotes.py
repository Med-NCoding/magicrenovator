from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends

from app.dependencies import SessionOwner, require_csrf, require_owner
from app.domain.schemas import CreateQuoteRequest, QuoteResponse
from app.services.quote_service import QuoteService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("/catalog")
def get_model_catalog(
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    svc = QuoteService(settings)
    return svc.load_catalog()


@router.post("", response_model=QuoteResponse, status_code=201)
def create_quote(
    body: CreateQuoteRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> QuoteResponse:
    svc = QuoteService(settings)
    return svc.create_quote(owner_id_hash=owner.id_hash, body=body)
