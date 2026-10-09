from __future__ import annotations

import asyncio
from typing import Any, Literal
import httpx

from app.domain.errors import redact_secrets
from app.gateways.base import (
    NormalizedAccount,
    NormalizedCreationResult,
    NormalizedDownloadItem,
    NormalizedProjectStatus,
    NormalizedUploadReservation,
    ProviderGateway,
    ProviderRejected,
    ProviderUnavailable,
    SubmissionUnknown,
)

_TRUSTED_BASES = ("https://api.magichour.ai/v1",)


def _assert_live_key_allowed(key: str) -> None:
    if not key:
        raise ProviderRejected(401, "invalid_key", "API key is required.")


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


class MagicHourGateway(ProviderGateway):
    def __init__(self, client: httpx.AsyncClient | None = None, base_url: str = "https://api.magichour.ai/v1") -> None:
        normalized_base = base_url.rstrip("/")
        if not any(normalized_base.startswith(trusted) for trusted in _TRUSTED_BASES):
            raise ValueError("Untrusted Magic Hour base URL")
        self.base = normalized_base
        self._external_client = client is not None
        self.client = client or httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def aclose(self) -> None:
        if not self._external_client:
            await self.client.aclose()

    async def _get_with_retry(self, url: str, key: str, timeout: float = 15.0, max_attempts: int = 3) -> httpx.Response:
        _assert_live_key_allowed(key)
        last_err: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = await self.client.get(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                    timeout=timeout,
                )
                if response.status_code in {502, 503, 504} and attempt < max_attempts - 1:
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                return response
            except httpx.TransportError as exc:
                last_err = exc
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                raise ProviderUnavailable("Network error talking to Magic Hour.") from None
        raise ProviderUnavailable(redact_secrets(str(last_err or "Provider unavailable")))

    async def account(self, key: str) -> NormalizedAccount:
        response = await self._get_with_retry(f"{self.base}/account", key=key, timeout=15.0)
        if response.status_code == 401:
            raise ProviderRejected(401, "unauthorized", "Invalid Magic Hour API key.")
        if response.status_code == 429:
            raise ProviderRejected(429, "rate_limited", "Magic Hour rate limit reached.")
        if response.status_code >= 500:
            raise ProviderUnavailable("Magic Hour account service is temporarily unavailable.")
        if response.status_code >= 400:
            data = _safe_json(response)
            raise ProviderRejected(response.status_code, str(data.get("code", "rejected")), "Account check rejected.")
        data = _safe_json(response)
        account_id = data.get("id")
        tier = data.get("tier")
        credits = data.get("credits")
        if (
            not isinstance(account_id, str)
            or tier not in {"free", "creator", "pro", "business"}
            or not isinstance(credits, int)
        ):
            raise ProviderUnavailable("Malformed account response from provider.")
        return NormalizedAccount(account_id=account_id, tier=tier, credits=max(0, credits))

    async def reserve_and_upload(
        self,
        key: str,
        media_type: Literal["image", "video", "audio"],
        extension: str,
        file_bytes: bytes,
    ) -> NormalizedUploadReservation:
        _assert_live_key_allowed(key)
        clean_ext = extension.lstrip(".").lower()
        try:
            res = await self.client.post(
                f"{self.base}/files/upload-urls",
                json={"items": [{"type": media_type, "extension": clean_ext}]},
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=15.0,
            )
        except httpx.TransportError:
            raise ProviderUnavailable("Failed to reserve upload URL with Magic Hour.") from None

        if res.status_code >= 500:
            raise ProviderUnavailable("Magic Hour upload service is unavailable.")
        if res.status_code >= 400:
            data = _safe_json(res)
            raise ProviderRejected(res.status_code, str(data.get("code", "upload_rejected")), "Upload URL reservation rejected.")

        data = _safe_json(res)
        items = data.get("items")
        if not isinstance(items, list) or not items:
            raise ProviderUnavailable("Invalid upload reservation response.")
        first = items[0]
        upload_url = first.get("upload_url")
        expires_at = first.get("expires_at")
        file_path = first.get("file_path")
        if not (isinstance(upload_url, str) and isinstance(expires_at, str) and isinstance(file_path, str)):
            raise ProviderUnavailable("Incomplete upload reservation fields.")

        # PUT normalized bytes to signed URL WITHOUT attaching the Magic Hour bearer token
        try:
            put_res = await self.client.put(
                upload_url,
                content=file_bytes,
                headers={"Content-Type": "application/octet-stream"},
                timeout=30.0,
            )
        except httpx.TransportError:
            raise ProviderUnavailable("Failed to upload bytes to storage.") from None

        if put_res.status_code < 200 or put_res.status_code >= 300:
            raise ProviderUnavailable(f"Upload PUT failed with status {put_res.status_code}.")

        return NormalizedUploadReservation(
            upload_url=upload_url,
            expires_at=expires_at,
            file_path=file_path,
        )

    async def create(self, route: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
        _assert_live_key_allowed(key)
        if route not in {"ai-image-editor", "image-to-video"}:
            raise ValueError("Unsupported creation route")
        try:
            response = await self.client.post(
                f"{self.base}/{route}",
                json=body,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=30.0,
            )
        except httpx.TransportError as exc:
            raise SubmissionUnknown("Transport failure during paid creation call") from exc

        if response.status_code >= 500:
            raise SubmissionUnknown(f"Server 5xx ({response.status_code}) during paid creation call")

        if response.status_code >= 400:
            data = _safe_json(response)
            code = data.get("code")
            err_code = code if isinstance(code, str) and code else "rejected"
            raw_msg = data.get("message")
            safe_msg = redact_secrets(str(raw_msg)) if isinstance(raw_msg, str) and raw_msg.strip() else "Provider rejected creation request"
            raise ProviderRejected(response.status_code, err_code, safe_msg)

        try:
            data = response.json()
        except Exception as exc:
            raise SubmissionUnknown("Malformed JSON on 2xx creation response") from exc

        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"].strip():
            raise SubmissionUnknown("Missing string id on 2xx creation response")
        return data

    async def create_image(
        self,
        key: str,
        name: str,
        model: str,
        resolution: str,
        prompt: str,
        image_file_paths: list[str],
        image_count: int = 1,
        aspect_ratio: str | None = None,
    ) -> NormalizedCreationResult:
        body: dict[str, Any] = {
            "name": name,
            "image_count": image_count,
            "model": model,
            "resolution": resolution,
            "style": {"prompt": prompt},
            "assets": {"image_file_paths": image_file_paths},
        }
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        data = await self.create("ai-image-editor", key, body)
        charged = data.get("credits_charged")
        return NormalizedCreationResult(
            provider_id=data["id"],
            credits_charged=charged if isinstance(charged, int) else None,
        )

    async def create_video(
        self,
        key: str,
        name: str,
        model: str,
        resolution: str,
        end_seconds: int,
        prompt: str,
        image_file_path: str,
        audio: bool = False,
    ) -> NormalizedCreationResult:
        body: dict[str, Any] = {
            "name": name,
            "end_seconds": end_seconds,
            "model": model,
            "resolution": resolution,
            "audio": audio,
            "style": {"prompt": prompt},
            "assets": {"image_file_path": image_file_path},
        }
        data = await self.create("image-to-video", key, body)
        charged = data.get("credits_charged")
        return NormalizedCreationResult(
            provider_id=data["id"],
            credits_charged=charged if isinstance(charged, int) else None,
        )

    async def get_project_status(
        self,
        key: str,
        kind: Literal["image", "video"],
        provider_id: str,
    ) -> NormalizedProjectStatus:
        route_prefix = "image-projects" if kind == "image" else "video-projects"
        res = await self._get_with_retry(f"{self.base}/{route_prefix}/{provider_id}", key=key, timeout=15.0)
        if res.status_code == 401:
            raise ProviderRejected(401, "unauthorized", "Invalid or expired Magic Hour API key.")
        if res.status_code == 404:
            raise ProviderRejected(404, "not_found", "Provider project not found.")
        if res.status_code >= 500:
            raise ProviderUnavailable("Provider status endpoint temporarily unavailable.")
        if res.status_code >= 400:
            data = _safe_json(res)
            raise ProviderRejected(res.status_code, str(data.get("code", "rejected")), "Status check rejected.")

        data = _safe_json(res)
        status_val = data.get("status")
        if status_val not in {"draft", "queued", "rendering", "complete", "error", "canceled"}:
            raise ProviderUnavailable("Malformed status response from provider.")

        raw_downloads = data.get("downloads") or []
        downloads: list[NormalizedDownloadItem] = []
        if isinstance(raw_downloads, list):
            for item in raw_downloads:
                if isinstance(item, dict) and isinstance(item.get("url"), str) and isinstance(item.get("expires_at"), str):
                    downloads.append(NormalizedDownloadItem(url=item["url"], expires_at=item["expires_at"]))

        err_obj = data.get("error")
        err_code = err_obj.get("code") if isinstance(err_obj, dict) else None
        err_msg = err_obj.get("message") if isinstance(err_obj, dict) else None
        charged = data.get("credits_charged")

        return NormalizedProjectStatus(
            provider_id=str(data.get("id", provider_id)),
            status=status_val,
            credits_charged=charged if isinstance(charged, int) else None,
            downloads=downloads,
            error_code=str(err_code) if err_code else None,
            error_message=redact_secrets(str(err_msg)) if err_msg else None,
        )
