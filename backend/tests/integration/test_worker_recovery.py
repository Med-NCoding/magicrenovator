from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from app.dependencies import apply_migrations, get_db_conn
from tests.mock_gateway import MOCK_STATE, MockGateway
from app.main import app
from app.settings import get_settings
from app.workers.runner import (
    force_expire_lease,
    run_job_until_settled,
    run_worker_once,
)
from tests.unit.test_quotes_and_idempotency import _setup_room_with_photo_and_brief


def _create_admitted_image_job(client: TestClient, headers: dict[str, str], brief_id: str, key_suffix: str) -> dict:
    quote = client.post(
        "/api/quotes",
        json={"brief_id": brief_id, "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    res = client.post(
        "/api/generations",
        json={"quote_id": quote["quote_id"], "idempotency_key": f"idemp_recovery_{key_suffix}"},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()


@pytest.mark.asyncio
async def test_crash_before_submit_recovers_and_completes_cleanly() -> None:
    apply_migrations()
    MOCK_STATE.reset()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    _, _, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_recov_before_1")
    job_adm = _create_admitted_image_job(client, headers, brief["id"], "before_submit_1")
    job_id = job_adm["job_id"]

    # 1. Inject crash BEFORE paid provider submit
    with pytest.raises(RuntimeError, match="Simulated crash before provider submit"):
        await run_worker_once(settings=settings, crash_point="before_submit", specific_job_id=job_id)

    # Verify zero provider jobs were created in MockGateway
    assert len(MOCK_STATE.jobs) == 0

    # 2. Expire worker lease and run until settled -> safely submits once and reaches ready_for_review
    settled = await run_job_until_settled(job_id, settings=settings)
    assert settled["state"] == "ready_for_review"
    assert settled["output_asset_id"] is not None
    assert len(MOCK_STATE.jobs) == 1


@pytest.mark.asyncio
async def test_crash_after_submit_before_id_persistence_enters_submission_unknown_without_replay() -> None:
    apply_migrations()
    MOCK_STATE.reset()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    _, _, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_recov_ambig_1")
    job_adm = _create_admitted_image_job(client, headers, brief["id"], "after_submit_1")
    job_id = job_adm["job_id"]

    # 1. Inject crash AFTER provider.create_image succeeded but BEFORE provider_id was persisted in DB
    with pytest.raises(RuntimeError, match="Simulated crash after provider submit before persisting provider_id"):
        await run_worker_once(settings=settings, crash_point="after_submit_before_persist", specific_job_id=job_id)

    # Exactly 1 provider job was created in MockGateway
    assert len(MOCK_STATE.jobs) == 1

    # 2. Expire lease and run worker again -> MUST transition to 'submission_unknown' and NEVER replay the paid POST!
    force_expire_lease(job_id, settings=settings)
    recovered = await run_worker_once(settings=settings, specific_job_id=job_id)
    assert len(recovered) == 1
    assert recovered[0]["state"] == "submission_unknown"
    assert len(MOCK_STATE.jobs) == 1  # Zero automatic paid replays!

    # 3. Verify GET /api/generations/{id} exposes correlation_name and reconcile_without_paid_replay
    snap = client.get(f"/api/generations/{job_id}").json()
    assert snap["state"] == "submission_unknown"
    assert snap["permitted_next_action"] == "reconcile_without_paid_replay"
    assert snap["correlation_name"].startswith("renopreview:")

    # Calling /resume without confirm_not_in_dashboard is blocked with 409 submission_unknown
    res_block = client.post(
        f"/api/generations/{job_id}/resume",
        json={"confirm_not_in_dashboard": False},
        headers=headers,
    )
    assert res_block.status_code == 409
    assert res_block.json()["error"]["code"] == "submission_unknown"


@pytest.mark.asyncio
async def test_crash_after_id_persistence_and_after_completion_and_sse_parity() -> None:
    apply_migrations()
    MOCK_STATE.reset()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    _, _, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_recov_poll_1")
    job_adm = _create_admitted_image_job(client, headers, brief["id"], "after_persist_1")
    job_id = job_adm["job_id"]

    # Step 1: Run 1 tick -> submits and persists provider_id, entering 'queued'
    step1 = await run_worker_once(settings=settings, specific_job_id=job_id)
    assert step1[0]["state"] == "queued"
    assert step1[0]["provider_id"] is not None
    assert len(MOCK_STATE.jobs) == 1

    # Step 2: Simulate crash after provider reports 'complete' but before downloading output
    force_expire_lease(job_id, settings=settings)
    with pytest.raises(RuntimeError, match="Simulated crash after provider complete before download"):
        await run_worker_once(
            settings=settings,
            crash_point="after_complete_before_download",
            specific_job_id=job_id,
        )

    # Job is now in 'saving_output' with known provider_id; still only 1 provider job created
    snap_mid = client.get(f"/api/generations/{job_id}").json()
    assert snap_mid["state"] == "saving_output"
    assert len(MOCK_STATE.jobs) == 1

    # Step 3: Expire lease and run worker -> resumes from 'saving_output', downloads output, and reaches 'ready_for_review'
    force_expire_lease(job_id, settings=settings)
    step3 = await run_worker_once(settings=settings, specific_job_id=job_id)
    assert step3[0]["state"] == "ready_for_review"
    assert step3[0]["output_asset_id"] is not None
    assert len(MOCK_STATE.jobs) == 1

    # Verify SSE endpoint and polling snapshot return identical ordered state events
    snap_final = client.get(f"/api/generations/{job_id}").json()
    sse_res = client.get(f"/api/generations/{job_id}/events")
    assert sse_res.status_code == 200
    sse_events = []
    for block in sse_res.text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                sse_events.append(json.loads(line[len("data: ") :]))

    assert [e["sequence"] for e in sse_events] == [e["sequence"] for e in snap_final["events"]]
    assert [e["state"] for e in sse_events] == [e["state"] for e in snap_final["events"]]

    # Verify Last-Event-ID header filters out earlier events
    first_seq = sse_events[0]["sequence"]
    sse_resume = client.get(
        f"/api/generations/{job_id}/events",
        headers={"Last-Event-ID": str(first_seq)},
    )
    resumed_events = [
        json.loads(line[len("data: ") :])
        for block in sse_resume.text.strip().split("\n\n")
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    assert all(e["sequence"] > first_seq for e in resumed_events)


@pytest.mark.asyncio
async def test_phase8_download_security_and_review_decisions() -> None:
    from app.workers.download import download_and_save_output, validate_download_url

    apply_migrations()
    MOCK_STATE.reset()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 1. Untrusted download host and non-HTTPS URLs are rejected
    with pytest.raises(ValueError, match="HTTPS"):
        validate_download_url("http://assets.magichour.ai/out.jpg", settings)
    with pytest.raises(ValueError, match="ALLOWED_DOWNLOAD_HOSTS"):
        validate_download_url("https://evil.example.com/out.jpg", settings)
    with pytest.raises(ValueError, match="forbidden"):
        validate_download_url("https://127.0.0.1/out.jpg", settings)

    # 2. Generate an image, test corrupted download failure -> retry saving_output -> revise -> accept
    _, room, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_phase8_rev_1")
    job1_adm = _create_admitted_image_job(client, headers, brief["id"], "p8_rev_1")
    job1_id = job1_adm["job_id"]

    # Simulate corrupted output download first
    await run_worker_once(settings=settings, specific_job_id=job1_id)  # -> queued
    force_expire_lease(job1_id, settings=settings)
    with pytest.raises(RuntimeError):
        await run_worker_once(
            settings=settings,
            crash_point="after_complete_before_download",
            specific_job_id=job1_id,
        )
    # Feed corrupted bytes from an allowed host via MockTransport
    import httpx

    corrupt_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"not-a-valid-image"))
    )
    failed_job = await download_and_save_output(
        job_id=job1_id,
        download_url="https://assets.magichour.ai/corrupt.jpg",
        settings=settings,
        http_client=corrupt_client,
    )
    await corrupt_client.aclose()
    assert failed_job["state"] == "failed"
    assert failed_job["output_asset_id"] is None

    # Resume download-only without re-charging provider!
    resumed = client.post(f"/api/generations/{job1_id}/resume", json={}, headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "saving_output"

    settled1 = await run_job_until_settled(job1_id, settings=settings)
    assert settled1["state"] == "ready_for_review"
    out_asset_1 = settled1["output_asset_id"]
    assert out_asset_1 is not None
    assert len(MOCK_STATE.jobs) == 1  # Still only 1 provider submission!

    # Review decision = 'revise' -> marks job1 rejected, creates brief revision #2, video still locked!
    rev_revise = client.post(
        f"/api/assets/{out_asset_1}/reviews",
        json={"decision": "revise", "notes": "Make the oak floor slightly lighter."},
        headers=headers,
    )
    assert rev_revise.status_code == 200
    rev_data = rev_revise.json()
    assert rev_data["decision"] == "revise"
    assert rev_data["next_brief_revision_id"] is not None
    assert rev_data["next_estimated_credits"] == 50

    # Video quote is STILL blocked because image was revised, not accepted!
    vid_still_blocked = client.post(
        "/api/quotes",
        json={"brief_id": rev_data["next_brief_revision_id"], "kind": "video"},
        headers=headers,
    )
    assert vid_still_blocked.status_code == 400

    # Generate image #2 on the revised brief and ACCEPT it
    job2_adm = _create_admitted_image_job(client, headers, rev_data["next_brief_revision_id"], "p8_rev_2")
    settled2 = await run_job_until_settled(job2_adm["job_id"], settings=settings)
    assert settled2["state"] == "ready_for_review"
    out_asset_2 = settled2["output_asset_id"]

    rev_accept = client.post(
        f"/api/assets/{out_asset_2}/reviews",
        json={"decision": "accept", "notes": "Looks great!"},
        headers=headers,
    )
    assert rev_accept.status_code == 200
    assert rev_accept.json()["decision"] == "accept"

    room_after = client.get(f"/api/rooms/{room['id']}").json()
    assert room_after["accepted_image_asset_id"] == out_asset_2
    assert room_after["accepted_image_review_id"] == rev_accept.json()["id"]


@pytest.mark.asyncio
async def test_phase9_video_gate_low_credit_recovery_and_video_completion() -> None:
    apply_migrations()
    MOCK_STATE.reset()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Connect key with 240 credits (enough for 50-credit image, leaving 190 credits < 240 needed for 5s 720p video)
    key = "mhk_live_phase9_240_key"
    MOCK_STATE.set_balance(key, 240)
    _, room, _, brief = _setup_room_with_photo_and_brief(client, headers, key=key)

    # 1. Generate and accept still image (costs 50 credits -> 190 remaining)
    img_adm = _create_admitted_image_job(client, headers, brief["id"], "p9_img_1")
    img_settled = await run_job_until_settled(img_adm["job_id"], settings=settings)
    accepted_img_id = img_settled["output_asset_id"]
    client.post(
        f"/api/assets/{accepted_img_id}/reviews",
        json={"decision": "accept"},
        headers=headers,
    )

    # 2. Quote 5s 720p video clip (costs 240 credits, but only 190 credits remain!)
    vid_quote_low = client.post(
        "/api/quotes",
        json={
            "brief_id": brief["id"],
            "kind": "video",
            "options": {"resolution": "720p", "duration_seconds": 5, "motion_preset": "gentle_push"},
        },
        headers=headers,
    ).json()
    assert vid_quote_low["source_asset_id"] == accepted_img_id
    assert vid_quote_low["estimated_credits"] == 240
    assert vid_quote_low["balance"] == 190
    assert vid_quote_low["sufficient_credits"] is False

    # Attempting to start video generation with 190 < 240 credits fails safely with 402 insufficient_credits
    vid_admit_low = client.post(
        "/api/generations",
        json={"quote_id": vid_quote_low["quote_id"], "idempotency_key": "idemp_p9_vid_low"},
        headers=headers,
    )
    assert vid_admit_low.status_code == 402
    assert vid_admit_low.json()["error"]["code"] == "insufficient_credits"

    # Verify accepted still image and review remain intact!
    room_check = client.get(f"/api/rooms/{room['id']}").json()
    assert room_check["accepted_image_asset_id"] == accepted_img_id

    # 3. Top up mock balance to 500, call /api/connections/magic-hour/refresh, create fresh video quote, and run video to completion!
    MOCK_STATE.set_balance(key, 500)
    ref_res = client.post("/api/connections/magic-hour/refresh", headers=headers)
    assert ref_res.status_code == 200
    assert ref_res.json()["credits"] == 500

    vid_quote_ok = client.post(
        "/api/quotes",
        json={
            "brief_id": brief["id"],
            "kind": "video",
            "options": {"resolution": "720p", "duration_seconds": 5, "motion_preset": "gentle_push"},
        },
        headers=headers,
    ).json()
    assert vid_quote_ok["sufficient_credits"] is True

    vid_adm = client.post(
        "/api/generations",
        json={"quote_id": vid_quote_ok["quote_id"], "idempotency_key": "idemp_p9_vid_ok"},
        headers=headers,
    )
    assert vid_adm.status_code == 201
    vid_settled = await run_job_until_settled(vid_adm.json()["job_id"], settings=settings)
    assert vid_settled["state"] == "ready_for_review"
    clip_asset_id = vid_settled["output_asset_id"]
    assert clip_asset_id is not None

    # Accept the video clip
    clip_rev = client.post(
        f"/api/assets/{clip_asset_id}/reviews",
        json={"decision": "accept"},
        headers=headers,
    )
    assert clip_rev.status_code == 200
    room_final = client.get(f"/api/rooms/{room['id']}").json()
    assert room_final["accepted_clip_asset_id"] == clip_asset_id
