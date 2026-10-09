from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal
from pydantic import BaseModel, Field


class ProviderRejected(Exception):
    def __init__(self, status: int, code: str, message: str = "Provider rejected request") -> None:
        super().__init__(f"ProviderRejected({status}, {code})")
        self.status = status
        self.code = code
        self.message = message


class SubmissionUnknown(Exception):
    def __init__(self, reason: str = "Ambiguous provider submission outcome") -> None:
        super().__init__(reason)
        self.reason = reason


class ProviderUnavailable(Exception):
    def __init__(self, reason: str = "Provider temporarily unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


class NormalizedAccount(BaseModel):
    account_id: str
    tier: Literal["free", "creator", "pro", "business"]
    credits: int = Field(ge=0)


class NormalizedUploadReservation(BaseModel):
    upload_url: str
    expires_at: str
    file_path: str


class NormalizedCreationResult(BaseModel):
    provider_id: str
    credits_charged: int | None = None


class NormalizedDownloadItem(BaseModel):
    url: str
    expires_at: str


class NormalizedProjectStatus(BaseModel):
    provider_id: str
    status: Literal["draft", "queued", "rendering", "complete", "error", "canceled"]
    credits_charged: int | None = None
    downloads: list[NormalizedDownloadItem] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ProviderGateway(ABC):
    @abstractmethod
    async def account(self, key: str) -> NormalizedAccount:
        raise NotImplementedError

    @abstractmethod
    async def reserve_and_upload(
        self,
        key: str,
        media_type: Literal["image", "video", "audio"],
        extension: str,
        file_bytes: bytes,
    ) -> NormalizedUploadReservation:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def get_project_status(
        self,
        key: str,
        kind: Literal["image", "video"],
        provider_id: str,
    ) -> NormalizedProjectStatus:
        raise NotImplementedError
