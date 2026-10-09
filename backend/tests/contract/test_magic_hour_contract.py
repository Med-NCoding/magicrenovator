from __future__ import annotations

import json
from typing import Any
import httpx
import pytest

from app.gateways.base import (
    ProviderRejected,
    ProviderUnavailable,
    SubmissionUnknown,
)
from app.gateways.magic_hour import MagicHourGateway
from tests.mock_gateway import MockGateway, MockGatewayState

# Reviewed Magic Hour v1 OpenAPI Contract Snapshot
OPENAPI_CONTRACT_SNAPSHOT: dict[str, Any] = {
    "reviewed_at": "2026-10-03T00:00:00Z",
    "endpoints": {
        "GET /v1/account": {
            "response_required": ["id", "tier", "credits"],
            "allowed_tiers": ["free", "creator", "pro", "business"],
        },
        "POST /v1/files/upload-urls": {
            "request_required": ["items"],
            "item_required": ["type", "extension"],
            "response_item_required": ["upload_url", "expires_at", "file_path"],
        },
        "POST /v1/ai-image-editor": {
            "request_required": ["name", "image_count", "model", "resolution", "style", "assets"],
            "response_required": ["id", "credits_charged"],
        },
        "GET /v1/image-projects/{id}": {
            "response_required": ["id", "status", "credits_charged", "downloads"],
            "allowed_statuses": ["draft", "queued", "rendering", "complete", "error", "canceled"],
        },
        "POST /v1/image-to-video": {
            "request_required": ["name", "end_seconds", "model", "resolution", "audio", "style", "assets"],
            "response_required": ["id", "credits_charged"],
        },
        "GET /v1/video-projects/{id}": {
            "response_required": ["id", "status", "credits_charged", "downloads"],
            "allowed_statuses": ["draft", "queued", "rendering", "complete", "error", "canceled"],
        },
    },
}


@pytest.mark.asyncio
async def test_live_adapter_rejects_mock_or_test_tokens() -> None:
    gateway = MagicHourGateway()
    try:
        for forbidden_key in ("mhk_mock_pro_500", "mock_12345", "test_mock_abc", "fake_key_999", ""):
            with pytest.raises(ProviderRejected) as exc_info:
                await gateway.account(forbidden_key)
            assert exc_info.value.status == 401
            assert exc_info.value.code == "invalid_key"
    finally:
        await gateway.aclose()


@pytest.mark.asyncio
async def test_magic_hour_gateway_openapi_contract_and_error_semantics() -> None:
    captured_requests: list[httpx.Request] = []
    mode = {"scenario": "happy"}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        path = request.url.path

        # Signed S3/CDN upload URL PUT must NOT carry Magic Hour Authorization header
        if request.method == "PUT" and "upload.magichour.ai" in request.url.host:
            assert "authorization" not in {k.lower() for k in request.headers.keys()}
            return httpx.Response(200)

        # All Magic Hour API calls must carry Bearer token
        auth = request.headers.get("Authorization", "")
        assert auth == "Bearer mhk_live_real_contract_key"

        if path == "/v1/account":
            return httpx.Response(
                200,
                json={
                    "id": "usr_live_123",
                    "email": "renovator@example.com",
                    "tier": "creator",
                    "credits": 650,
                    "subscription": {"status": "active"},
                },
            )

        if path == "/v1/files/upload-urls":
            payload = json.loads(request.content.decode("utf-8"))
            assert set(OPENAPI_CONTRACT_SNAPSHOT["endpoints"]["POST /v1/files/upload-urls"]["request_required"]).issubset(
                payload.keys()
            )
            item = payload["items"][0]
            assert set(OPENAPI_CONTRACT_SNAPSHOT["endpoints"]["POST /v1/files/upload-urls"]["item_required"]).issubset(
                item.keys()
            )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "upload_url": "https://upload.magichour.ai/put-target?sig=abc",
                            "expires_at": "2026-10-04T02:00:00Z",
                            "file_path": "api-assets/usr_live_123/room_norm.jpg",
                        }
                    ]
                },
            )

        if path == "/v1/ai-image-editor":
            payload = json.loads(request.content.decode("utf-8"))
            req_fields = OPENAPI_CONTRACT_SNAPSHOT["endpoints"]["POST /v1/ai-image-editor"]["request_required"]
            assert set(req_fields).issubset(payload.keys())
            assert isinstance(payload["style"]["prompt"], str)
            assert isinstance(payload["assets"]["image_file_paths"], list)

            if mode["scenario"] == "402":
                return httpx.Response(402, json={"code": "insufficient_credits", "message": "Not enough credits"})
            if mode["scenario"] == "422":
                return httpx.Response(422, json={"code": "unprocessable_entity", "message": "Invalid resolution"})
            if mode["scenario"] == "500":
                return httpx.Response(500, json={"message": "Internal error"})
            if mode["scenario"] == "missing_id":
                return httpx.Response(200, json={"credits_charged": 50})
            if mode["scenario"] == "timeout":
                raise httpx.ReadTimeout("Simulated read timeout during paid creation", request=request)

            return httpx.Response(200, json={"id": "img_proj_99", "credits_charged": 50})

        if path == "/v1/image-projects/img_proj_99":
            return httpx.Response(
                200,
                json={
                    "id": "img_proj_99",
                    "name": "renopreview:rm_1:job_1:brf_1",
                    "status": "complete",
                    "image_count": 1,
                    "type": "AI_IMAGE_EDITOR",
                    "created_at": "2026-10-04T00:00:00Z",
                    "enabled": True,
                    "credits_charged": 50,
                    "downloads": [
                        {
                            "url": "https://assets.magichour.ai/img_proj_99/result.png",
                            "expires_at": "2026-10-05T00:00:00Z",
                        }
                    ],
                    "error": None,
                },
            )

        if path == "/v1/image-to-video":
            payload = json.loads(request.content.decode("utf-8"))
            req_fields = OPENAPI_CONTRACT_SNAPSHOT["endpoints"]["POST /v1/image-to-video"]["request_required"]
            assert set(req_fields).issubset(payload.keys())
            assert isinstance(payload["style"]["prompt"], str)
            assert isinstance(payload["assets"]["image_file_path"], str)
            return httpx.Response(200, json={"id": "vid_proj_88", "credits_charged": 240})

        if path == "/v1/video-projects/vid_proj_88":
            return httpx.Response(
                200,
                json={
                    "id": "vid_proj_88",
                    "name": "renopreview:rm_1:job_2:brf_1",
                    "status": "complete",
                    "type": "IMAGE_TO_VIDEO",
                    "created_at": "2026-10-04T00:00:00Z",
                    "width": 1280,
                    "height": 720,
                    "enabled": True,
                    "start_seconds": 0,
                    "end_seconds": 5,
                    "credits_charged": 240,
                    "fps": 30,
                    "downloads": [
                        {
                            "url": "https://videos.magichour.ai/vid_proj_88/clip.mp4",
                            "expires_at": "2026-10-05T00:00:00Z",
                        }
                    ],
                    "error": None,
                },
            )

        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    live_gw = MagicHourGateway(client=client)
    mock_gw = MockGateway(state=MockGatewayState())

    # Verify both live_gw (with MockTransport) and mock_gw pass the exact same normalized workflow contract
    for gw, key in [(live_gw, "mhk_live_real_contract_key"), (mock_gw, "mhk_mock_pro_500")]:
        acct = await gw.account(key)
        assert acct.tier in ("creator", "pro")
        assert acct.credits >= 500

        up = await gw.reserve_and_upload(key, "image", "jpg", b"normalized-jpeg-bytes")
        assert up.file_path.endswith(".jpg")

        img_res = await gw.create_image(
            key=key,
            name="renopreview:rm_1:job_1:brf_1",
            model="seedream-v4.5",
            resolution="1k",
            prompt="Edit the provided kitchen photo into a realistic renovation concept.",
            image_file_paths=[up.file_path],
        )
        assert img_res.provider_id
        assert img_res.credits_charged == 50

        img_status = await gw.get_project_status(key, "image", img_res.provider_id)
        assert img_status.status == "complete"
        assert len(img_status.downloads) == 1

        vid_res = await gw.create_video(
            key=key,
            name="renopreview:rm_1:job_2:brf_1",
            model="kling-3.0",
            resolution="720p",
            end_seconds=5,
            prompt="Slow, steady, gentle forward camera push.",
            image_file_path=up.file_path,
            audio=False,
        )
        assert vid_res.provider_id
        assert vid_res.credits_charged == 240

        vid_status = await gw.get_project_status(key, "video", vid_res.provider_id)
        assert vid_status.status == "complete"
        assert len(vid_status.downloads) == 1

    # Verify 402, 422, 500, missing_id, and timeout semantics on paid creation
    mode["scenario"] = "402"
    with pytest.raises(ProviderRejected) as exc_402:
        await live_gw.create_image(
            key="mhk_live_real_contract_key",
            name="test",
            model="seedream-v4.5",
            resolution="1k",
            prompt="prompt",
            image_file_paths=["api-assets/usr/1.jpg"],
        )
    assert exc_402.value.status == 402
    assert exc_402.value.code == "insufficient_credits"

    mode["scenario"] = "422"
    with pytest.raises(ProviderRejected) as exc_422:
        await live_gw.create_image(
            key="mhk_live_real_contract_key",
            name="test",
            model="seedream-v4.5",
            resolution="1k",
            prompt="prompt",
            image_file_paths=["api-assets/usr/1.jpg"],
        )
    assert exc_422.value.status == 422

    # 500, timeout, and 200-without-id on paid POST must raise SubmissionUnknown (never auto-retried!)
    for ambiguous_mode in ("500", "missing_id", "timeout"):
        mode["scenario"] = ambiguous_mode
        before_count = len(captured_requests)
        with pytest.raises(SubmissionUnknown):
            await live_gw.create_image(
                key="mhk_live_real_contract_key",
                name="test",
                model="seedream-v4.5",
                resolution="1k",
                prompt="prompt",
                image_file_paths=["api-assets/usr/1.jpg"],
            )
        # Verify exactly 1 POST was sent (no automatic retry on paid creation!)
        assert len(captured_requests) - before_count == 1

    await client.aclose()
