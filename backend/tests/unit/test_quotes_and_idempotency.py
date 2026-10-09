from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.dependencies import apply_migrations, get_db_conn
from app.main import app
from app.settings import get_settings
from tests.unit.test_photo_normalization import _make_textured_room_image


def _setup_room_with_photo_and_brief(client: TestClient, headers: dict[str, str], key: str = "mhk_live_valid_creator_1234") -> tuple[dict, dict, dict, dict]:
    conn_res = client.post("/api/connections/magic-hour", json={"key": key}, headers=headers)
    assert conn_res.status_code == 200
    proj = client.post("/api/projects", json={"name": "Quote Test House"}, headers=headers).json()
    room = client.post(
        f"/api/projects/{proj['id']}/rooms",
        json={"name": "Kitchen", "room_type": "kitchen"},
        headers=headers,
    ).json()
    photo = _make_textured_room_image(width=800, height=600)
    asset = client.post(
        f"/api/rooms/{room['id']}/assets",
        files={"file": ("kitchen.jpg", photo, "image/jpeg")},
        headers=headers,
    ).json()
    brief = client.post(
        f"/api/rooms/{room['id']}/briefs",
        json={
            "raw_text": "Change cabinet fronts to matte white and handles to brass.",
            "preserve": ["Room footprint", "Windows", "Doors", "Island position"],
            "layout_mode": "preserve",
        },
        headers=headers,
    ).json()
    return proj, room, asset, brief


def test_tier_gating_option_validity_and_video_gate_blocking() -> None:
    apply_migrations()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Connect a FREE tier key (mhk_live_free_tier_key -> tier='free', credits=500)
    _, room, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_free_tier_12345")

    # 1. Free tier requesting paid model 'seedream-v4.5' is rejected with unsupported_option
    paid_model_res = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "model": "seedream-v4.5", "options": {"resolution": "1k"}},
        headers=headers,
    )
    assert paid_model_res.status_code == 400
    assert paid_model_res.json()["error"]["code"] == "unsupported_option"

    # 2. Free tier requesting 2k resolution on 'qwen-edit' is rejected with unsupported_option
    res_2k = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "model": "qwen-edit", "options": {"resolution": "2k"}},
        headers=headers,
    )
    assert res_2k.status_code == 400
    assert res_2k.json()["error"]["code"] == "unsupported_option"

    # 3. Free tier requesting 1k resolution on 'qwen-edit' succeeds (20 credits)
    valid_free = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "model": "qwen-edit", "options": {"resolution": "1k"}},
        headers=headers,
    )
    assert valid_free.status_code == 201
    q_data = valid_free.json()
    assert q_data["model"] == "qwen-edit"
    assert q_data["estimated_credits"] == 20
    assert q_data["sufficient_credits"] is True

    # 4. Video quote before accepting a still image is blocked!
    vid_blocked = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "video", "options": {"duration_seconds": 5}},
        headers=headers,
    )
    assert vid_blocked.status_code == 400
    assert vid_blocked.json()["error"]["code"] == "invalid_brief"
    assert "accept a renovated still image" in vid_blocked.json()["error"]["message"]


def test_insufficient_credits_expired_quote_and_modified_brief_after_quote() -> None:
    apply_migrations()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 1. Zero-credit key can calculate a quote (showing sufficient_credits=False) but admission blocks with 402
    _, room, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_zero_credits_1234")
    q_zero = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    assert q_zero["sufficient_credits"] is False
    admit_zero = client.post(
        "/api/generations",
        json={"quote_id": q_zero["quote_id"], "idempotency_key": "idemp_zero_test_1"},
        headers=headers,
    )
    assert admit_zero.status_code == 402
    assert admit_zero.json()["error"]["code"] == "insufficient_credits"

    # Reconnect a funded creator key
    client.post("/api/connections/magic-hour", json={"key": "mhk_live_valid_creator_9999"}, headers=headers)

    # 2. Expired quote is rejected with stale_quote (409)
    q_exp = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE quotes SET expires_at = %s WHERE id = %s",
                (datetime.now(timezone.utc) - timedelta(minutes=1), q_exp["quote_id"]),
            )
    admit_exp = client.post(
        "/api/generations",
        json={"quote_id": q_exp["quote_id"], "idempotency_key": "idemp_expired_test_1"},
        headers=headers,
    )
    assert admit_exp.status_code == 409
    assert admit_exp.json()["error"]["code"] == "stale_quote"

    # 3. Modifying the brief after creating a quote invalidates the quote with stale_quote (409)
    q_stale = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    client.post(
        f"/api/rooms/{room['id']}/briefs",
        json={
            "raw_text": "Change cabinet fronts to dark navy blue and handles to brushed nickel.",
            "preserve": ["Room footprint", "Windows", "Doors", "Island position"],
            "layout_mode": "preserve",
        },
        headers=headers,
    )
    admit_stale = client.post(
        "/api/generations",
        json={"quote_id": q_stale["quote_id"], "idempotency_key": "idemp_stale_brief_1"},
        headers=headers,
    )
    assert admit_stale.status_code == 409
    assert admit_stale.json()["error"]["code"] == "stale_quote"


def test_duplicate_submit_idempotency_conflict_and_parallel_account_concurrency() -> None:
    apply_migrations()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    _, room, _, brief = _setup_room_with_photo_and_brief(client, headers, key="mhk_live_valid_creator_7777")

    q1 = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    q2 = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "2k"}},
        headers=headers,
    ).json()

    # 1. Admit q1 with idempotency_key
    res1 = client.post(
        "/api/generations",
        json={"quote_id": q1["quote_id"], "idempotency_key": "idemp_unique_key_001"},
        headers=headers,
    )
    assert res1.status_code == 201
    job1 = res1.json()
    assert job1["state"] == "admitted"

    # 2. Duplicate submit with exact same (idempotency_key, quote_id) returns the existing job (200) without duplicate creation
    res_dup = client.post(
        "/api/generations",
        json={"quote_id": q1["quote_id"], "idempotency_key": "idemp_unique_key_001"},
        headers=headers,
    )
    assert res_dup.status_code == 200
    assert res_dup.json()["job_id"] == job1["job_id"]

    # 3. Same idempotency_key with a DIFFERENT quote_id (modified payload) is rejected with 409 conflict
    res_conflict_key = client.post(
        "/api/generations",
        json={"quote_id": q2["quote_id"], "idempotency_key": "idemp_unique_key_001"},
        headers=headers,
    )
    assert res_conflict_key.status_code == 409
    assert res_conflict_key.json()["error"]["code"] == "conflict"

    # 4. Parallel submission on the same Magic Hour account while job1 is still active ('admitted') is blocked with 409 conflict
    res_parallel = client.post(
        "/api/generations",
        json={"quote_id": q2["quote_id"], "idempotency_key": "idemp_unique_key_002"},
        headers=headers,
    )
    assert res_parallel.status_code == 409
    assert res_parallel.json()["error"]["code"] == "conflict"
    assert "currently active" in res_parallel.json()["error"]["message"]


def test_revision_requoting_credit_check_and_direct_video_mode() -> None:
    import asyncio
    from app.gateways.mock import MOCK_STATE
    from app.workers.runner import run_job_until_settled

    apply_migrations()
    MOCK_STATE.reset()
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    key = "mhk_mock_rev_flow_500"
    MOCK_STATE.set_balance(key, 500)
    _, room, _, brief1 = _setup_room_with_photo_and_brief(client, headers, key=key)

    # 1. Quote and generate initial image
    q1 = client.post(
        "/api/quotes",
        json={"brief_id": brief1["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    adm1 = client.post(
        "/api/generations",
        json={"quote_id": q1["quote_id"], "idempotency_key": "idemp_rev_flow_1"},
        headers=headers,
    ).json()
    settled1 = asyncio.run(run_job_until_settled(adm1["job_id"], settings=settings))
    assert settled1["state"] == "ready_for_review"
    out_img_1 = settled1["output_asset_id"]

    # First accept out_img_1, then decide to revise it -> verify accepted_image_asset_id is cleared while revising
    client.post(
        f"/api/assets/{out_img_1}/reviews",
        json={"decision": "accept"},
        headers=headers,
    )
    assert client.get(f"/api/rooms/{room['id']}").json()["accepted_image_asset_id"] == out_img_1

    # 2. Submit a revision with notes (including opposing/preserve keywords that previously could block re-quoting)
    rev_res = client.post(
        f"/api/assets/{out_img_1}/reviews",
        json={
            "decision": "revise",
            "notes": "Make the yellow light bar disappear, keep everything else there, and make cabinet fronts black instead of white.",
        },
        headers=headers,
    )
    assert rev_res.status_code == 200
    next_brief_id = rev_res.json()["next_brief_revision_id"]
    assert next_brief_id is not None

    # Verify accepted_image_asset_id was cleared when revision was requested
    room_after_revise = client.get(f"/api/rooms/{room['id']}").json()
    assert room_after_revise["accepted_image_asset_id"] is None

    # 3. Re-quote works even if caller passes old brief1["id"] (auto-resolves to active brief) OR next_brief_id
    q2_from_old = client.post(
        "/api/quotes",
        json={"brief_id": brief1["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    )
    assert q2_from_old.status_code == 201
    assert q2_from_old.json()["brief_revision_id"] == next_brief_id
    assert q2_from_old.json()["sufficient_credits"] is True

    # 4. Run the revised image generation and accept it
    adm2 = client.post(
        "/api/generations",
        json={"quote_id": q2_from_old.json()["quote_id"], "idempotency_key": "idemp_rev_flow_2"},
        headers=headers,
    ).json()
    settled2 = asyncio.run(run_job_until_settled(adm2["job_id"], settings=settings))
    assert settled2["state"] == "ready_for_review"
    out_img_2 = settled2["output_asset_id"]
    assert out_img_2 != out_img_1

    # Verify submit worker uploaded out_img_1 (accepted_reference_asset_id) to Magic Hour to edit the previous generated photo
    from app.dependencies import get_db_conn
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT provider_file_paths_json FROM assets WHERE id = %s", (out_img_1,))
            ref_paths = cur.fetchone()["provider_file_paths_json"]
            assert bool(ref_paths), "Expected previous generated image to be uploaded as reference for revision edit"

    acc_img = client.post(
        f"/api/assets/{out_img_2}/reviews",
        json={"decision": "accept"},
        headers=headers,
    )
    assert acc_img.status_code == 200

    # Verify direct download link with download=1 returns attachment Content-Disposition
    room_info = client.get(f"/api/rooms/{room['id']}").json()
    dl_res = client.get(f"{room_info['accepted_image_url']}&download=1")
    assert dl_res.status_code == 200
    assert "attachment" in dl_res.headers.get("content-disposition", "")

    # 5. Quote and generate a video clip, then revise the video clip and re-quote!
    q_vid1 = client.post(
        "/api/quotes",
        json={"brief_id": next_brief_id, "kind": "video", "options": {"resolution": "720p", "duration_seconds": 5}},
        headers=headers,
    ).json()
    adm_vid1 = client.post(
        "/api/generations",
        json={"quote_id": q_vid1["quote_id"], "idempotency_key": "idemp_rev_vid_1"},
        headers=headers,
    ).json()
    settled_vid1 = asyncio.run(run_job_until_settled(adm_vid1["job_id"], settings=settings))
    assert settled_vid1["state"] == "ready_for_review"
    out_vid_1 = settled_vid1["output_asset_id"]

    # Revise the video clip
    rev_vid = client.post(
        f"/api/assets/{out_vid_1}/reviews",
        json={"decision": "revise", "notes": "Add warm under-cabinet lighting to the video."},
        headers=headers,
    )
    assert rev_vid.status_code == 200
    vid_rev_brief_id = rev_vid.json()["next_brief_revision_id"]

    # Re-check credit when balance is too low (160 remaining < 240 needed) -> returns sufficient_credits=False
    q_vid_low = client.post(
        "/api/quotes",
        json={"brief_id": vid_rev_brief_id, "kind": "video", "options": {"resolution": "720p", "duration_seconds": 5}},
        headers=headers,
    ).json()
    assert q_vid_low["sufficient_credits"] is False

    # Top up balance, refresh, re-quote revised video, and run it!
    MOCK_STATE.set_balance(key, 600)
    client.post("/api/connections/magic-hour/refresh", headers=headers)
    q_vid2 = client.post(
        "/api/quotes",
        json={"brief_id": vid_rev_brief_id, "kind": "video", "options": {"resolution": "720p", "duration_seconds": 5}},
        headers=headers,
    ).json()
    assert q_vid2["sufficient_credits"] is True
    adm_vid2 = client.post(
        "/api/generations",
        json={"quote_id": q_vid2["quote_id"], "idempotency_key": "idemp_rev_vid_2"},
        headers=headers,
    )
    assert adm_vid2.status_code == 201
    settled_vid2 = asyncio.run(run_job_until_settled(adm_vid2.json()["job_id"], settings=settings))
    assert settled_vid2["state"] == "ready_for_review"

