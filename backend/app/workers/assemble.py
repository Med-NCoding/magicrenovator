from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import redact_secrets
from app.repositories.ledger import LedgerRepository
from app.settings import Settings, get_settings
from app.workers.download import probe_video_bytes

CONCEPT_LIMITATION_NOTICE = (
    "Visual concept. Room-by-room renovation concept — not a validated 3D reconstruction, "
    "continuous floor-plan walkthrough, or construction drawing. Confirm measurements, "
    "materials, and feasibility with your renovator."
)


def _sanitize_label_text(text: str, max_len: int = 60) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len] or "Room Concept"


def _build_markdown_brief(
    project_name: str,
    title: str,
    rooms_info: list[dict[str, Any]],
    ledger_summary: dict[str, Any],
) -> str:
    lines = [
        f"# {title} — {project_name}",
        "",
        f"> **Notice:** {CONCEPT_LIMITATION_NOTICE}",
        "",
        "## Room-by-Room Renovation Summary",
        "",
    ]
    for idx, rm in enumerate(rooms_info, start=1):
        lines.append(f"### {idx}. {rm['name']} ({rm['room_type']})")
        lines.append(f"- **Layout Mode:** `{rm.get('layout_mode', 'preserve')}`")
        if rm.get("style"):
            lines.append(f"- **Style Direction:** {rm['style']}")
        preserve_items = rm.get("preserve") or []
        lines.append(f"- **Preserved Features:** {', '.join(preserve_items) if preserve_items else 'Standard room structure'}")
        lines.append("- **Requested Changes:**")
        changes = rm.get("changes") or []
        if changes:
            for c in changes:
                lines.append(f"  - **{c.get('target', 'Surface')}:** {c.get('description', '')}")
        else:
            lines.append("  - General finish update")
        lines.append("")

    lines.append("## Credit Spend Summary")
    known = ledger_summary.get("known_observed_credits", 0)
    accepted_cnt = ledger_summary.get("accepted_outputs", 0)
    lines.append(f"- **Observed Credits Charged:** {known} credits")
    lines.append(f"- **Accepted Outputs:** {accepted_cnt}")
    lines.append("")
    return "\n".join(lines)


def _normalize_and_concat_clips(
    clip_specs: list[dict[str, Any]],
    include_concept_label: bool,
    settings: Settings,
) -> tuple[bytes, dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        normalized_paths: list[Path] = []

        for idx, spec in enumerate(clip_specs):
            src_path = settings.storage_path / spec["storage_key"]
            if not src_path.exists():
                raise RuntimeError(f"Source clip file missing for asset {spec['asset_id']}")

            norm_clip_path = tmp_path / f"norm_{idx}.mp4"
            label_file_path = tmp_path / f"label_{idx}.txt"
            room_label = _sanitize_label_text(spec["room_label"])
            overlay_text = f"{room_label} - Visual concept" if include_concept_label else room_label
            label_file_path.write_text(overlay_text, encoding="utf-8")

            base_vf = (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
            )
            # First try with drawtext using textfile (no shell interpolation); fallback to base_vf if drawtext filter is absent
            drawtext_vf = (
                f"{base_vf},"
                f"drawtext=textfile='{label_file_path.name}':fontcolor=white:fontsize=24:"
                "box=1:boxcolor=black@0.55:boxborderw=8:x=32:y=660"
            )

            cmd_with_text = [
                "ffmpeg",
                "-y",
                "-i",
                str(src_path),
                "-vf",
                drawtext_vf,
                "-r",
                "30",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(norm_clip_path),
            ]
            proc = subprocess.run(
                cmd_with_text,
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if proc.returncode != 0 or not norm_clip_path.exists():
                cmd_fallback = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(src_path),
                    "-vf",
                    base_vf,
                    "-r",
                    "30",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(norm_clip_path),
                ]
                proc2 = subprocess.run(
                    cmd_fallback,
                    cwd=str(tmp_path),
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                if proc2.returncode != 0 or not norm_clip_path.exists():
                    raise RuntimeError(f"FFmpeg clip normalization failed: {proc2.stderr[:200]}")

            normalized_paths.append(norm_clip_path)

        concat_list_path = tmp_path / "concat_list.txt"
        concat_lines = [f"file '{p.name}'" for p in normalized_paths]
        concat_list_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        final_mp4_path = tmp_path / "presentation.mp4"
        concat_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(final_mp4_path),
        ]
        proc_concat = subprocess.run(
            concat_cmd,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc_concat.returncode != 0 or not final_mp4_path.exists():
            raise RuntimeError(f"FFmpeg presentation concat failed: {proc_concat.stderr[:200]}")

        video_bytes = final_mp4_path.read_bytes()
        probed = probe_video_bytes(video_bytes)
        return video_bytes, probed


async def assemble_export(export_id: str, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    ledger = LedgerRepository(cfg)
    now = datetime.now(timezone.utc)

    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*, p.title, p.ordered_clips_json, p.manifest_json, p.include_concept_label,
                       prj.name AS project_name
                FROM exports e
                JOIN presentations p ON p.id = e.presentation_id
                JOIN projects prj ON prj.id = e.project_id
                WHERE e.id = %s
                """,
                (export_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Export {export_id} not found")
            exp = dict(row)

            if exp["status"] == "ready" and exp.get("video_asset_id") and exp.get("brief_asset_id"):
                return exp

            cur.execute(
                "UPDATE exports SET status = 'rendering', updated_at = %s WHERE id = %s",
                (now, export_id),
            )
            cur.execute(
                "UPDATE outbox SET dispatched = TRUE, dispatched_at = %s WHERE export_id = %s AND dispatched = FALSE",
                (now, export_id),
            )

    try:
        manifest = json.loads(exp["manifest_json"]) if isinstance(exp["manifest_json"], str) else exp["manifest_json"]
        clip_specs = manifest.get("clips") or []
        rooms_info = manifest.get("rooms_brief_data") or []
        include_concept = bool(exp.get("include_concept_label", True))

        video_bytes, probed = _normalize_and_concat_clips(
            clip_specs=clip_specs,
            include_concept_label=include_concept,
            settings=cfg,
        )

        ledger_summary = ledger.summarize_owner_ledger(exp["owner_id_hash"])
        md_text = _build_markdown_brief(
            project_name=exp["project_name"],
            title=exp["title"],
            rooms_info=rooms_info,
            ledger_summary=ledger_summary,
        )
        md_bytes = md_text.encode("utf-8")

        owner_prefix = exp["owner_id_hash"][:12]
        vid_asset_id = f"ast_{secrets.token_hex(8)}"
        md_asset_id = f"ast_{secrets.token_hex(8)}"
        vid_token = secrets.token_hex(16)
        md_token = secrets.token_hex(16)

        vid_storage_key = f"private/exports/{owner_prefix}/{vid_token}_presentation.mp4"
        vid_thumb_key = f"private/thumbs/{owner_prefix}/{vid_token}_thumb.jpg"
        md_storage_key = f"private/exports/{owner_prefix}/{md_token}_brief.md"

        vid_path = cfg.storage_path / vid_storage_key
        vid_thumb_path = cfg.storage_path / vid_thumb_key
        md_path = cfg.storage_path / md_storage_key
        vid_path.parent.mkdir(parents=True, exist_ok=True)
        vid_thumb_path.parent.mkdir(parents=True, exist_ok=True)

        vid_path.write_bytes(video_bytes)
        if probed.get("thumb_bytes"):
            vid_thumb_path.write_bytes(probed["thumb_bytes"])
        md_path.write_bytes(md_bytes)

        done_now = datetime.now(timezone.utc)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO assets (
                        id, owner_id_hash, project_id, role, storage_key, sha256,
                        mime_type, bytes_size, width, height, duration_seconds, fps, codec,
                        normalization_transform_json, created_at
                    )
                    VALUES (%s, %s, %s, 'export_presentation_video', %s, %s, 'video/mp4', %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        vid_asset_id,
                        exp["owner_id_hash"],
                        exp["project_id"],
                        vid_storage_key,
                        hashlib.sha256(video_bytes).hexdigest(),
                        len(video_bytes),
                        probed["width"],
                        probed["height"],
                        probed["duration_seconds"],
                        probed["fps"],
                        probed["codec"],
                        json.dumps({"thumbnail_key": vid_thumb_key, "export_id": export_id}),
                        done_now,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO assets (
                        id, owner_id_hash, project_id, role, storage_key, sha256,
                        mime_type, bytes_size, width, height, normalization_transform_json, created_at
                    )
                    VALUES (%s, %s, %s, 'export_brief_markdown', %s, %s, 'text/markdown', %s, 0, 0, %s, %s)
                    """,
                    (
                        md_asset_id,
                        exp["owner_id_hash"],
                        exp["project_id"],
                        md_storage_key,
                        hashlib.sha256(md_bytes).hexdigest(),
                        len(md_bytes),
                        json.dumps({"export_id": export_id}),
                        done_now,
                    ),
                )
                cur.execute(
                    """
                    UPDATE exports
                    SET status = 'ready',
                        video_asset_id = %s,
                        brief_asset_id = %s,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (vid_asset_id, md_asset_id, done_now, export_id),
                )
                return dict(cur.fetchone())

    except Exception as exc:
        err_now = datetime.now(timezone.utc)
        safe_err = {"code": "save_failed", "message": redact_secrets(f"Presentation assembly failed: {exc}")}
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE exports
                    SET status = 'failed', last_safe_error_json = %s, updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (json.dumps(safe_err), err_now, export_id),
                )
                return dict(cur.fetchone())


async def run_pending_exports_once(settings: Settings | None = None) -> list[dict[str, Any]]:
    cfg = settings or get_settings()
    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM exports
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 5
                """
            )
            ids = [r["id"] for r in cur.fetchall()]
    results: list[dict[str, Any]] = []
    for exp_id in ids:
        results.append(await assemble_export(exp_id, settings=cfg))
    return results
