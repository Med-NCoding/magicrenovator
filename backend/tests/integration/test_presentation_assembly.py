from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import apply_migrations
from app.gateways.mock import MOCK_STATE
from app.main import app
from app.settings import get_settings
from app.workers.assemble import run_pending_exports_once
from app.workers.download import probe_video_bytes
from app.workers.runner import run_job_until_settled
from tests.unit.test_photo_normalization import _make_textured_room_image


async def _add_room_with_accepted_video(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    room_name: str,
    room_type: str,
    suffix: str,
) -> tuple[dict, str, str]:
    settings = get_settings()
    room = client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": room_name, "room_type": room_type},
        headers=headers,
    ).json()
    photo = _make_textured_room_image(width=800, height=600)
    up = client.post(
        f"/api/rooms/{room['id']}/assets",
        files={"file": (f"{suffix}.jpg", photo, "image/jpeg")},
        headers=headers,
    ).json()
    brief_res = client.post(
        f"/api/rooms/{room['id']}/briefs",
        json={
            "raw_text": f"Update {room_name} with white oak cabinets and quartz counters",
            "changes": [{"target": "cabinets", "description": "white oak shaker", "source": "user_control"}],
            "preserve": ["Room layout and wall positions"],
            "layout_mode": "preserve",
            "style": "Warm Contemporary",
        },
        headers=headers,
    )
    assert brief_res.status_code == 201
    brief = brief_res.json()

    # 1. Image quote -> generate -> accept
    img_q = client.post(
        "/api/quotes",
        json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
        headers=headers,
    ).json()
    img_adm = client.post(
        "/api/generations",
        json={"quote_id": img_q["quote_id"], "idempotency_key": f"idemp_img_{suffix}"},
        headers=headers,
    ).json()
    settled_img = await run_job_until_settled(img_adm["job_id"], settings=settings)
    img_asset_id = settled_img["output_asset_id"]
    assert img_asset_id is not None

    rev_img = client.post(
        f"/api/assets/{img_asset_id}/reviews",
        json={
            "decision": "accept",
            "checklist": {
                "room_shape_preserved": True,
                "doors_windows_preserved": True,
                "fixtures_preserved": True,
                "materials_colors_accurate": True,
                "no_unwanted_additions": True,
                "no_visible_distortions": True,
            },
        },
        headers=headers,
    )
    assert rev_img.status_code == 200

    # 2. Video quote -> generate -> accept
    vid_q = client.post(
        "/api/quotes",
        json={
            "brief_id": brief["id"],
            "kind": "video",
            "options": {"resolution": "720p", "duration_seconds": 5, "motion_preset": "gentle_push"},
        },
        headers=headers,
    ).json()
    vid_adm = client.post(
        "/api/generations",
        json={"quote_id": vid_q["quote_id"], "idempotency_key": f"idemp_vid_{suffix}"},
        headers=headers,
    ).json()
    settled_vid = await run_job_until_settled(vid_adm["job_id"], settings=settings)
    vid_asset_id = settled_vid["output_asset_id"]
    assert vid_asset_id is not None

    rev_vid = client.post(
        f"/api/assets/{vid_asset_id}/reviews",
        json={
            "decision": "accept",
            "checklist": {
                "room_shape_preserved": True,
                "doors_windows_preserved": True,
                "fixtures_preserved": True,
                "materials_colors_accurate": True,
                "no_unwanted_additions": True,
                "no_visible_distortions": True,
                "temporal_stability": True,
                "no_bent_edges_or_moving_cabinets": True,
                "no_impossible_extensions": True,
                "camera_movement_suitable": True,
            },
        },
        headers=headers,
    )
    assert rev_vid.status_code == 200
    return room, img_asset_id, vid_asset_id


@pytest.mark.asyncio
async def test_presentation_assembly_1_2_3_clips_reordering_idempotency_and_label_sanitization() -> None:
    apply_migrations()
    MOCK_STATE.reset()
    MOCK_STATE.set_balance("mhk_live_presentation_test_key_1", 5000)
    settings = get_settings()
    client = TestClient(app)
    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    conn = client.post(
        "/api/connections/magic-hour",
        json={"key": "mhk_live_presentation_test_key_1"},
        headers=headers,
    )
    assert conn.status_code == 200

    project = client.post(
        "/api/projects",
        json={"name": "Oakwood Whole-Home Concept"},
        headers=headers,
    ).json()
    project_id = project["id"]

    # Reject presentation assembly before any accepted clips exist
    empty_res = client.post(
        f"/api/projects/{project_id}/presentations",
        json={"title": "Empty Presentation", "ordered_clips": []},
        headers=headers,
    )
    assert empty_res.status_code == 400
    assert empty_res.json()["error"]["next_action"] == "accept_room_clip"

    # Room 1: Kitchen
    r1, _, clip1 = await _add_room_with_accepted_video(
        client, headers, project_id, "Kitchen", "kitchen", "r1"
    )
    provider_jobs_after_r1 = len(MOCK_STATE.jobs)

    # 1. Assemble 1-clip presentation with malicious characters in label to test sanitization
    pres_1 = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Single Room Concept",
            "ordered_clips": [{"asset_id": clip1, "room_label": "Kitchen; rm -rf / ' \" $(whoami)\x00\n"}],
            "include_concept_label": True,
        },
        headers=headers,
    )
    assert pres_1.status_code == 201
    p1_data = pres_1.json()
    await run_pending_exports_once(settings=settings)
    exp1 = client.get(f"/api/exports/{p1_data['export_id']}").json()
    assert exp1["status"] == "ready"
    assert exp1["presentation_video_url"] is not None
    assert exp1["brief_markdown_url"] is not None
    assert "Visual concept. Room-by-room renovation concept" in exp1["concept_limitation_notice"]
    assert "Visual concept. Room-by-room renovation concept" in exp1["brief_markdown"]
    # Zero provider calls made during local FFmpeg presentation assembly!
    assert len(MOCK_STATE.jobs) == provider_jobs_after_r1

    # Verify downloaded MP4 from signed URL is valid 1280x720@30fps H.264
    vid1_res = client.get(exp1["presentation_video_url"])
    assert vid1_res.status_code == 200
    probed1 = probe_video_bytes(vid1_res.content)
    assert probed1["width"] == 1280
    assert probed1["height"] == 720
    assert probed1["codec"] == "h264"

    # Room 2: Bathroom, Room 3: Living Room
    r2, _, clip2 = await _add_room_with_accepted_video(
        client, headers, project_id, "Primary Bath", "bathroom", "r2"
    )
    r3, _, clip3 = await _add_room_with_accepted_video(
        client, headers, project_id, "Living Room", "living_room", "r3"
    )
    provider_jobs_after_3_rooms = len(MOCK_STATE.jobs)

    # 2. Assemble 2-clip presentation
    pres_2 = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Two Room Concept",
            "ordered_clips": [
                {"asset_id": clip1, "room_label": "Kitchen"},
                {"asset_id": clip2, "room_label": "Primary Bath"},
            ],
            "include_concept_label": True,
        },
        headers=headers,
    )
    assert pres_2.status_code == 201
    p2_data = pres_2.json()
    await run_pending_exports_once(settings=settings)
    exp2 = client.get(f"/api/exports/{p2_data['export_id']}").json()
    assert exp2["status"] == "ready"

    # 3. Assemble 3-clip presentation (Order A: clip1, clip2, clip3)
    pres_3a = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Three Room Concept",
            "ordered_clips": [
                {"asset_id": clip1, "room_label": "Kitchen"},
                {"asset_id": clip2, "room_label": "Primary Bath"},
                {"asset_id": clip3, "room_label": "Living Room"},
            ],
            "include_concept_label": True,
        },
        headers=headers,
    ).json()
    await run_pending_exports_once(settings=settings)
    exp3a = client.get(f"/api/exports/{pres_3a['export_id']}").json()
    assert exp3a["status"] == "ready"
    assert len(exp3a["room_media"]) == 6  # 3 images + 3 clips

    # 4. Submitting the exact same 3-clip order reuses the existing export idempotently
    pres_3a_dup = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Three Room Concept",
            "ordered_clips": [
                {"asset_id": clip1, "room_label": "Kitchen"},
                {"asset_id": clip2, "room_label": "Primary Bath"},
                {"asset_id": clip3, "room_label": "Living Room"},
            ],
            "include_concept_label": True,
        },
        headers=headers,
    ).json()
    assert pres_3a_dup["export_id"] == pres_3a["export_id"]
    assert pres_3a_dup["manifest_hash"] == pres_3a["manifest_hash"]
    assert pres_3a_dup["status"] == "ready"

    # 5. Reordering the 3 clips (Order B: clip3, clip1, clip2) produces a distinct manifest_hash and new export
    pres_3b = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Three Room Concept",
            "ordered_clips": [
                {"asset_id": clip3, "room_label": "Living Room"},
                {"asset_id": clip1, "room_label": "Kitchen"},
                {"asset_id": clip2, "room_label": "Primary Bath"},
            ],
            "include_concept_label": True,
        },
        headers=headers,
    ).json()
    assert pres_3b["manifest_hash"] != pres_3a["manifest_hash"]
    assert pres_3b["export_id"] != pres_3a["export_id"]
    await run_pending_exports_once(settings=settings)
    exp3b = client.get(f"/api/exports/{pres_3b['export_id']}").json()
    assert exp3b["status"] == "ready"

    # Verify zero provider jobs were created by any presentation assemblies
    assert len(MOCK_STATE.jobs) == provider_jobs_after_3_rooms
