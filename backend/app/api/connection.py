from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, Request

from app.dependencies import (
    SessionOwner,
    enforce_rate_limit,
    get_gateway,
    require_csrf,
    require_owner,
)
from app.domain.schemas import ConnectionStatusResponse, ConnectKeyRequest
from app.gateways.base import ProviderGateway
from app.services.credential_vault import CredentialVaultService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/connections/magic-hour", tags=["connection"])


def _to_status_response(ref: dict[str, Any] | None, settings: Settings, message: str | None = None) -> ConnectionStatusResponse:
    if not ref:
        return ConnectionStatusResponse(
            connected=False,
            masked_key=None,
            tier=None,
            credits=None,
            checked_at=None,
            expires_at=None,
            can_generate_paid=False,
            gateway_mode=settings.GATEWAY_MODE,
            message=message or "Not connected to Magic Hour.",
        )
    credits = int(ref["balance"])
    can_generate = credits > 0 and not settings.PAUSE_GENERATIONS
    default_msg = (
        "Magic Hour connected. Add credits in Magic Hour before starting a paid generation."
        if credits == 0
        else "Magic Hour connected."
    )
    return ConnectionStatusResponse(
        connected=True,
        masked_key=ref["masked_suffix"],
        tier=ref["tier"],
        credits=credits,
        checked_at=ref["balance_checked_at"].isoformat(),
        expires_at=ref["expires_at"].isoformat(),
        can_generate_paid=can_generate,
        gateway_mode=settings.GATEWAY_MODE,
        message=message or default_msg,
    )


@router.post("", response_model=ConnectionStatusResponse)
async def connect_magic_hour(
    request: Request,
    body: ConnectKeyRequest,
    owner: SessionOwner = Depends(require_csrf),
    gateway: ProviderGateway = Depends(get_gateway),
    settings: Settings = Depends(get_settings),
) -> ConnectionStatusResponse:
    enforce_rate_limit(request, owner.id_hash, bucket="connect", limit=15, window_seconds=60, settings=settings)
    vault = CredentialVaultService(settings)
    ref = await vault.connect_key(owner_id_hash=owner.id_hash, raw_key=body.key, gateway=gateway)
    return _to_status_response(ref, settings)


@router.get("", response_model=ConnectionStatusResponse)
async def get_magic_hour_status(
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> ConnectionStatusResponse:
    vault = CredentialVaultService(settings)
    ref = vault.get_active_reference(owner.id_hash)
    return _to_status_response(ref, settings)


@router.post("/refresh", response_model=ConnectionStatusResponse)
async def refresh_magic_hour_balance(
    request: Request,
    owner: SessionOwner = Depends(require_csrf),
    gateway: ProviderGateway = Depends(get_gateway),
    settings: Settings = Depends(get_settings),
) -> ConnectionStatusResponse:
    enforce_rate_limit(request, owner.id_hash, bucket="refresh", limit=30, window_seconds=60, settings=settings)
    vault = CredentialVaultService(settings)
    ref = await vault.refresh_balance(owner_id_hash=owner.id_hash, gateway=gateway)
    return _to_status_response(ref, settings, message="Magic Hour balance refreshed.")


@router.delete("", response_model=ConnectionStatusResponse)
async def disconnect_magic_hour(
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> ConnectionStatusResponse:
    vault = CredentialVaultService(settings)
    vault.disconnect(owner.id_hash)
    return _to_status_response(
        None,
        settings,
        message="Disconnected from Magic Hour. Future app submissions are stopped; any already submitted provider job may continue in Magic Hour.",
    )
