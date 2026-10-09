#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GATEWAY_MODE", "mock")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/renopreview_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ASSET_BUCKET", str(REPO_ROOT / ".test_private_assets"))

from fastapi.testclient import TestClient  # noqa: E402
from app.dependencies import apply_migrations  # noqa: E402
from app.gateways.mock import MOCK_STATE  # noqa: E402
from app.main import app  # noqa: E402
from app.settings import get_settings  # noqa: E402
from app.workers.assemble import run_pending_exports_once  # noqa: E402
from app.workers.download import probe_video_bytes  # noqa: E402
from app.workers.runner import run_job_until_settled  # noqa: E402
from tests.unit.test_photo_normalization import _make_textured_room_image  # noqa: E402


async def run_benchmark(mode: str, confirm_live_spend: bool) -> dict[str, Any]:
    if mode == "live":
        if not confirm_live_spend or not os.environ.get("MAGIC_HOUR_API_KEY"):
            raise RuntimeError(
                "Live benchmark requires both --confirm-live-spend and a customer-supplied MAGIC_HOUR_API_KEY."
            )

    manifest_path = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = manifest["fixtures"]
    banned_tokens = [t.lower() for t in manifest.get("banned_embellishment_tokens", [])]

    apply_migrations()
    MOCK_STATE.reset()
    bench_key = "mhk_mock_5000_benchmark_runner"
    MOCK_STATE.set_balance(bench_key, 5000)
    settings = get_settings()
    client = TestClient(app)

    csrf = client.post("/api/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    conn = client.post(
        "/api/connections/magic-hour",
        json={"key": bench_key},
        headers=headers,
    )
    assert conn.status_code == 200, f"Connection failed: {conn.text}"

    proj = client.post(
        "/api/projects",
        json={"name": "Benchmark Evaluation House"},
        headers=headers,
    ).json()
    project_id = proj["id"]

    results: list[dict[str, Any]] = []
    accepted_clips: list[dict[str, str]] = []

    for idx, fx in enumerate(fixtures):
        fx_id = fx["id"]
        room = client.post(
            f"/api/projects/{project_id}/rooms",
            json={"name": fx["name"][:50], "room_type": fx["room_type"], "sort_order": idx},
            headers=headers,
        ).json()
        room_id = room["id"]

        photo = _make_textured_room_image(width=800, height=600)
        up = client.post(
            f"/api/rooms/{room_id}/assets",
            files={"file": (f"{fx_id}.jpg", photo, "image/jpeg")},
            headers=headers,
        )
        assert up.status_code == 201

        brief_res = client.post(
            f"/api/rooms/{room_id}/briefs",
            json={
                "raw_text": fx["raw_text"],
                "preserve": fx["preserve"],
                "layout_mode": fx["layout_mode"],
            },
            headers=headers,
        )
        assert brief_res.status_code == 201
        brief = brief_res.json()

        compiled_lower = brief["compiled_prompt"].lower()
        found_banned = [tok for tok in banned_tokens if tok in compiled_lower]
        conflict_matches = bool(brief["has_unresolved_conflicts"]) == bool(fx["expected_conflict"])
        keywords_present = all(kw.lower() in compiled_lower for kw in fx.get("expected_keywords", []))

        if fx["expected_conflict"]:
            # Verify quote is blocked while conflict is unresolved
            q_blocked = client.post(
                "/api/quotes",
                json={"brief_id": brief["id"], "kind": "image"},
                headers=headers,
            )
            quote_blocked_correctly = (
                q_blocked.status_code in {400, 409}
                and q_blocked.json().get("error", {}).get("next_action") == "resolve_conflicts"
            )
            results.append(
                {
                    "fixture_id": fx_id,
                    "passed": (not found_banned) and conflict_matches and quote_blocked_correctly,
                    "conflict_detected": brief["has_unresolved_conflicts"],
                    "quote_blocked_on_conflict": quote_blocked_correctly,
                    "banned_tokens_found": found_banned,
                }
            )
            continue

        # Verify video quote is blocked BEFORE still image acceptance
        vid_premature = client.post(
            "/api/quotes",
            json={"brief_id": brief["id"], "kind": "video"},
            headers=headers,
        )
        video_gate_enforced = (
            vid_premature.status_code in {400, 409}
            and vid_premature.json().get("error", {}).get("next_action") == "accept_still_image"
        )

        # Quote & generate still image
        q_img = client.post(
            "/api/quotes",
            json={"brief_id": brief["id"], "kind": "image", "options": {"resolution": "1k"}},
            headers=headers,
        ).json()
        adm_img = client.post(
            "/api/generations",
            json={"quote_id": q_img["quote_id"], "idempotency_key": f"bench_img_{fx_id}"},
            headers=headers,
        ).json()
        settled_img = await run_job_until_settled(adm_img["job_id"], settings=settings)
        img_asset_id = settled_img["output_asset_id"]
        assert img_asset_id is not None

        # Accept still image
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

        # Quote & generate video clip for first 2 non-conflict rooms
        if len(accepted_clips) < 2:
            q_vid = client.post(
                "/api/quotes",
                json={
                    "brief_id": brief["id"],
                    "kind": "video",
                    "options": {
                        "resolution": "720p",
                        "duration_seconds": 5,
                        "motion_preset": fx.get("motion_preset", "gentle_push"),
                    },
                },
                headers=headers,
            ).json()
            adm_vid = client.post(
                "/api/generations",
                json={"quote_id": q_vid["quote_id"], "idempotency_key": f"bench_vid_{fx_id}"},
                headers=headers,
            ).json()
            settled_vid = await run_job_until_settled(adm_vid["job_id"], settings=settings)
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
            accepted_clips.append({"asset_id": vid_asset_id, "room_label": fx["name"][:40]})

        passed = (
            (not found_banned)
            and conflict_matches
            and keywords_present
            and video_gate_enforced
            and settled_img["state"] == "ready_for_review"
        )
        results.append(
            {
                "fixture_id": fx_id,
                "passed": passed,
                "keywords_present": keywords_present,
                "video_gate_enforced": video_gate_enforced,
                "banned_tokens_found": found_banned,
            }
        )

    # Assemble presentation across accepted benchmark clips
    pres = client.post(
        f"/api/projects/{project_id}/presentations",
        json={
            "title": "Benchmark Evaluation Presentation",
            "ordered_clips": accepted_clips,
            "include_concept_label": True,
        },
        headers=headers,
    )
    assert pres.status_code == 201
    export_id = pres.json()["export_id"]
    await run_pending_exports_once(settings=settings)
    exp = client.get(f"/api/exports/{export_id}").json()
    vid_bytes = client.get(exp["presentation_video_url"]).content
    probed = probe_video_bytes(vid_bytes)
    presentation_valid = (
        exp["status"] == "ready"
        and probed["width"] == 1280
        and probed["height"] == 720
        and probed["codec"] == "h264"
    )

    all_passed = all(r["passed"] for r in results) and presentation_valid
    summary = {
        "benchmark_version": manifest["version"],
        "mode": mode,
        "all_passed": all_passed,
        "presentation_valid": presentation_valid,
        "fixtures_evaluated": len(results),
        "results": results,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RenoPreview evaluation benchmark.")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--confirm-live-spend", action="store_true")
    args = parser.parse_args()

    summary = asyncio.run(run_benchmark(args.mode, args.confirm_live_spend))
    print(json.dumps(summary, indent=2))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
