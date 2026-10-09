from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

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


class MockGatewayState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.accounts: dict[str, dict[str, Any]] = {
            "mhk_mock_pro_500": {"account_id": "acc_mock_pro_1", "tier": "pro", "credits": 500},
            "mhk_mock_shared_a": {"account_id": "acc_mock_shared_1", "tier": "pro", "credits": 500},
            "mhk_mock_shared_b": {"account_id": "acc_mock_shared_1", "tier": "pro", "credits": 500},
            "mhk_mock_free_100": {"account_id": "acc_mock_free_1", "tier": "free", "credits": 100},
            "mhk_mock_zero": {"account_id": "acc_mock_zero_1", "tier": "creator", "credits": 0},
        }
        # Shared balance by account_id so two keys for the same provider account share balance
        self.balances_by_account_id: dict[str, int] = {
            "acc_mock_pro_1": 500,
            "acc_mock_shared_1": 500,
            "acc_mock_free_1": 100,
            "acc_mock_zero_1": 0,
        }
        self.tiers_by_account_id: dict[str, Literal["free", "creator", "pro", "business"]] = {
            "acc_mock_pro_1": "pro",
            "acc_mock_shared_1": "pro",
            "acc_mock_free_1": "free",
            "acc_mock_zero_1": "creator",
        }
        self.jobs: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, bytes] = {}
        self.polls_required_for_complete: int = 1
        self.force_account_unavailable: bool = False
        self.force_next_create_status: str | None = None  # "402", "422", "500", "unknown", "missing_id"
        self.force_next_poll_timeout: bool = False

    def resolve_account_for_key(self, key: str) -> tuple[str, Literal["free", "creator", "pro", "business"], int]:
        if key in {"invalid", "mhk_mock_invalid", "bad_key"} or key.startswith("mhk_invalid"):
            raise ProviderRejected(401, "unauthorized", "Invalid Magic Hour API key.")
        if key == "mhk_mock_downtime" or self.force_account_unavailable:
            raise ProviderUnavailable("Magic Hour API is temporarily unreachable.")
        if key in self.accounts:
            acc = self.accounts[key]
            acc_id = acc["account_id"]
            tier = self.tiers_by_account_id.get(acc_id, acc["tier"])
            credits = self.balances_by_account_id.get(acc_id, acc["credits"])
            return acc_id, tier, credits

        # Dynamic deterministic mock key support:
        # e.g., mhk_mock_creator_240 or any valid-looking key in mock mode
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        acc_id = f"acc_mock_{digest}"
        if acc_id not in self.balances_by_account_id:
            if "zero" in key:
                self.balances_by_account_id[acc_id] = 0
                self.tiers_by_account_id[acc_id] = "creator"
            elif "free" in key:
                self.balances_by_account_id[acc_id] = 100
                self.tiers_by_account_id[acc_id] = "free"
            elif "low240" in key:
                self.balances_by_account_id[acc_id] = 240
                self.tiers_by_account_id[acc_id] = "pro"
            elif "5000" in key:
                self.balances_by_account_id[acc_id] = 5000
                self.tiers_by_account_id[acc_id] = "pro"
            else:
                self.balances_by_account_id[acc_id] = 500
                self.tiers_by_account_id[acc_id] = "pro"
        return acc_id, self.tiers_by_account_id[acc_id], self.balances_by_account_id[acc_id]

    def set_balance(self, key_or_account_id: str, credits: int) -> None:
        if key_or_account_id in self.balances_by_account_id:
            self.balances_by_account_id[key_or_account_id] = credits
            return
        acc_id, _, _ = self.resolve_account_for_key(key_or_account_id)
        self.balances_by_account_id[acc_id] = credits


MOCK_STATE = MockGatewayState()


class MockGateway(ProviderGateway):
    def __init__(self, state: MockGatewayState | None = None) -> None:
        self.state = state or MOCK_STATE

    async def account(self, key: str) -> NormalizedAccount:
        acc_id, tier, credits = self.state.resolve_account_for_key(key)
        if "low240" in key and credits < 240:
            credits = 1000
            self.state.balances_by_account_id[acc_id] = credits
        return NormalizedAccount(account_id=acc_id, tier=tier, credits=credits)

    async def reserve_and_upload(
        self,
        key: str,
        media_type: Literal["image", "video", "audio"],
        extension: str,
        file_bytes: bytes,
    ) -> NormalizedUploadReservation:
        acc_id, _, _ = self.state.resolve_account_for_key(key)
        clean_ext = extension.lstrip(".").lower()
        digest = hashlib.sha256(file_bytes).hexdigest()[:16]
        file_path = f"api-assets/{acc_id}/{digest}.{clean_ext}"
        self.state.uploads[file_path] = file_bytes
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        return NormalizedUploadReservation(
            upload_url=f"https://mock.magichour.internal/upload/{file_path}?sig=mock",
            expires_at=expires_at,
            file_path=file_path,
        )

    def _compute_mock_charge(self, kind: Literal["image", "video"], model: str, resolution: str, duration: int = 5) -> int:
        if kind == "image":
            if model in {"qwen-edit", "krea-2"}:
                return {"640px": 10, "1k": 20, "2k": 40}.get(resolution, 20)
            return {"640px": 50, "1k": 50, "2k": 100, "4k": 200}.get(resolution, 50)
        per_sec = {"480p": 24, "720p": 48, "1080p": 72, "4k": 240}.get(resolution, 48)
        return per_sec * duration

    async def _create_job(
        self,
        key: str,
        kind: Literal["image", "video"],
        name: str,
        model: str,
        resolution: str,
        prompt: str,
        source_path: str,
        duration_seconds: int = 5,
    ) -> NormalizedCreationResult:
        acc_id, _, balance = self.state.resolve_account_for_key(key)

        forced = self.state.force_next_create_status
        if forced is not None:
            self.state.force_next_create_status = None
            if forced == "402":
                raise ProviderRejected(402, "insufficient_credits", "Insufficient Magic Hour credits.")
            if forced == "422":
                raise ProviderRejected(422, "unprocessable_entity", "Unsupported option combination.")
            if forced in {"500", "unknown", "missing_id"}:
                raise SubmissionUnknown(f"Simulated {forced} creation ambiguity")

        cost = self._compute_mock_charge(kind, model, resolution, duration_seconds)
        if balance < cost:
            raise ProviderRejected(402, "insufficient_credits", "Insufficient Magic Hour credits.")

        self.state.balances_by_account_id[acc_id] = balance - cost
        job_num = len(self.state.jobs) + 1
        provider_id = f"mh_{kind}_{job_num}_{hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]}"
        self.state.jobs[provider_id] = {
            "provider_id": provider_id,
            "account_id": acc_id,
            "kind": kind,
            "name": name,
            "model": model,
            "resolution": resolution,
            "prompt": prompt,
            "source_path": source_path,
            "duration_seconds": duration_seconds,
            "credits_charged": cost,
            "polls": 0,
            "status": "queued",
        }
        return NormalizedCreationResult(provider_id=provider_id, credits_charged=cost)

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
        if not image_file_paths:
            raise ProviderRejected(400, "invalid_request", "Missing image_file_paths")
        return await self._create_job(
            key=key,
            kind="image",
            name=name,
            model=model,
            resolution=resolution,
            prompt=prompt,
            source_path=image_file_paths[0],
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
        if not image_file_path:
            raise ProviderRejected(400, "invalid_request", "Missing image_file_path")
        return await self._create_job(
            key=key,
            kind="video",
            name=name,
            model=model,
            resolution=resolution,
            prompt=prompt,
            source_path=image_file_path,
            duration_seconds=end_seconds,
        )

    async def get_project_status(
        self,
        key: str,
        kind: Literal["image", "video"],
        provider_id: str,
    ) -> NormalizedProjectStatus:
        self.state.resolve_account_for_key(key)
        if self.state.force_next_poll_timeout:
            self.state.force_next_poll_timeout = False
            raise ProviderUnavailable("Simulated network timeout during status poll")

        job = self.state.jobs.get(provider_id)
        if not job:
            raise ProviderRejected(404, "not_found", "Provider project not found")

        job["polls"] += 1
        if job["status"] in {"queued", "rendering"}:
            if job["polls"] >= self.state.polls_required_for_complete:
                job["status"] = "complete"
            else:
                job["status"] = "rendering"

        downloads: list[NormalizedDownloadItem] = []
        if job["status"] == "complete":
            ext = "png" if kind == "image" else "mp4"
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            downloads.append(
                NormalizedDownloadItem(
                    url=f"https://mock.magichour.internal/outputs/{provider_id}/output.{ext}",
                    expires_at=expires_at,
                )
            )

        return NormalizedProjectStatus(
            provider_id=provider_id,
            status=job["status"],
            credits_charged=job["credits_charged"],
            downloads=downloads,
        )
