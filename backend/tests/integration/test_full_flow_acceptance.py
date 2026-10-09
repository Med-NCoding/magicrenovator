from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import apply_migrations
from app.gateways.mock import MOCK_STATE
from app.main import app
from app.repositories.ledger import LedgerRepository
from app.settings import get_settings
from app.workers.assemble import run_pending_exports_once
from app.workers.download import probe_video_bytes
from app.workers.runner import run_job_until_settled
from tests.unit.test_photo_normalization import _make_textured_room_image


@pytest.mark.asyncio
async def test_full_end_to_end_multi_room_renovation_acceptance_flow() -> None:
    apply_migrations()
    MOCK_STATE.reset()
    raw_secret_key = "mhk_live_full_acceptance_5000_secret"
    MOCK_STATE.set_balance(raw_secret_key, 5000)
    settings = get_settings()
    client = TestClient(app)

    sess = client.post("/api/session")
    assert sess.status_code == 200
    csrf = sess.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 1. Connect Magic Hour BYOK key
    conn = client.post(
        "/api/connections/magic-hour",
        json={"key": raw_secret_key},
        headers=headers,
    )
    assert conn.status_code == 200
    assert raw_secret_key not in conn.text
    assert conn.json()["credits"] == 5000

    # 2. Create project and verify up to 5 rooms allowed, 6th room rejected
    proj = client.post(
        "/api/projects",
        json={"name": "Maple Street Whole-Home Remodel"},
        headers=headers,
    ).json()
    project_id = proj["id"]

    room_defs = [
        ("Kitchen", "kitchen", "Paint cabinets warm sage green, add brass pulls, and install white quartz countertops."),
        ("Living Room", "living_room", "Refinish floors in light white oak and paint walls soft alabaster white."),
        ("Primary Bathroom", "bathroom", "Replace vanity with fluted white oak and install matte black faucets."),
        ("Primary Bedroom", "bedroom", "Add warm linen wall paint and light oak hardwood flooring."),
        ("Dining Room", "dining_room", "Update wall paint to warm ivory and refinish oak flooring."),
    ]
    created_rooms = []
    for idx, (r_name, r_type, _) in enumerate(room_defs):
        rm_res = client.post(
            f"/api/projects/{project_id}/rooms",
            json={"name": r_name, "room_type": r_type, "sort_order": idx},
            headers=headers,
        )
        assert rm_res.status_code == 201
        created_rooms.append(rm_res.json())

    # 6th room must be rejected by MAX_ROOMS_PER_PROJECT=5
    sixth_res = client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "Bonus Room", "room_type": "bedroom", "sort_order": 5},
        headers=headers,
    )
    assert sixth_res.status_code == 400

    # 3. Complete full image -> review (including 1 revision on Kitchen) -> video -> review for first 2 rooms
    accepted_clips = []
    for idx in range(2):
        rm = created_rooms[idx]
        _, _, prompt_text = room_defs[idx]
        photo = _make_textured_room_image(width=900, height=650)
        up = client.post(
            f"/api/rooms/{rm['id']}/assets",
            files={"file": (f"room_{idx}.jpg", photo, "image/jpeg")},
            headers=headers,
        )
        assert up.status_code == 201

        brief = client.post(
            f"/api/rooms/{rm['id']}/briefs",
            json={
                "raw_text": prompt_text,
                "preserve": ["Room footprint", "Windows", "Doors"],
                "layout_mode": "preserve",
            },
            headers=headers,
        ).json()

        # Image quote & generation
        q_img = client.post(
            "/api/quotes",
            json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
            headers=headers,
        ).json()
        adm_img = client.post(
            "/api/generations",
            json={"quote_id": q_img["quote_id"], "idempotency_key": f"idemp_full_img_{idx}_v1"},
            headers=headers,
        ).json()
        settled_img = await run_job_until_settled(adm_img["job_id"], settings=settings)
        img_asset_id = settled_img["output_asset_id"]
        assert img_asset_id is not None

        # On Kitchen (idx == 0), test 'revise' decision first before accepting v2
        if idx == 0:
            rev_revise = client.post(
                f"/api/assets/{img_asset_id}/reviews",
                json={
                    "decision": "revise",
                    "checklist": {
                        "room_shape_preserved": True,
                        "doors_windows_preserved": True,
                        "fixtures_preserved": True,
                        "materials_colors_accurate": False,
                        "no_unwanted_additions": True,
                        "no_visible_distortions": True,
                    },
                    "notes": "Make the sage green slightly lighter and warmer",
                },
                headers=headers,
            )
            assert rev_revise.status_code == 200
            rev_body = rev_revise.json()
            assert rev_body["next_brief_revision_id"] is not None
            assert rev_body["next_estimated_credits"] is not None

            # Quote and generate v2 image from the linked child brief revision
            q_img2 = client.post(
                "/api/quotes",
                json={"brief_id": rev_body["next_brief_revision_id"], "kind": "image", "options": {"resolution": "1k"}},
                headers=headers,
            ).json()
            adm_img2 = client.post(
                "/api/generations",
                json={"quote_id": q_img2["quote_id"], "idempotency_key": f"idemp_full_img_{idx}_v2"},
                headers=headers,
            ).json()
            settled_img2 = await run_job_until_settled(adm_img2["job_id"], settings=settings)
            img_asset_id = settled_img2["output_asset_id"]
            brief_id_for_video = rev_body["next_brief_revision_id"]
        else:
            brief_id_for_video = brief["id"]

        # Accept the still image
        rev_accept_img = client.post(
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
        assert rev_accept_img.status_code == 200

        # Video quote & generation
        q_vid = client.post(
            "/api/quotes",
            json={
                "brief_id": brief_id_for_video,
                "kind": "video",
                "options": {"resolution": "720p", "duration_seconds": 5, "motion_preset": "gentle_push"},
            },
            headers=headers,
        ).json()
        adm_vid = client.post(
            "/api/generations",
            json={"quote_id": q_vid["quote_id"], "idempotency_key": f"idemp_full_vid_{idx}"},
            headers=headers,
        ).json()
        settled_vid = await run_job_until_settled(adm_vid["job_id"], settings=settings)
        vid_asset_id = settled_vid["output_asset_id"]
        assert vid_asset_id is not None

        # Accept the video clip
        rev_accept_vid = client.post(
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
        assert rev_accept_vid.status_code == 200
        accepted_clips.append({"asset_id": vid_asset_id, "room_label": rm["name"]})

    # 4. Assemble house presentation from the accepted clips
    pres = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Maple Street Final Presentation",
            "ordered_clips": accepted_clips,
            "include_concept_label": True,
        },
        headers=headers,
    )
    assert pres.status_code == 201
    export_id = pres.json()["export_id"]

    await run_pending_exports_once(settings=settings)
    exp = client.get(f"/api/exports/{export_id}").json()
    assert exp["status"] == "ready"
    assert exp["presentation_video_url"] is not None
    assert exp["brief_markdown_url"] is not None
    assert "Maple Street Final Presentation" in exp["brief_markdown"]
    assert raw_secret_key not in str(exp)

    vid_dl = client.get(exp["presentation_video_url"])
    assert vid_dl.status_code == 200
    probed = probe_video_bytes(vid_dl.content)
    assert probed["width"] == 1280
    assert probed["height"] == 720
    assert probed["codec"] == "h264"
