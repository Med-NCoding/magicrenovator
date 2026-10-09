from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.dependencies import get_db_conn
from app.domain.errors import AppError, redact_secrets
from app.repositories.jobs import JobRepository
from app.services.asset_service import THUMB_MAX_EDGE, normalize_photo_bytes
from app.settings import Settings, get_settings

MAX_IMAGE_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_VIDEO_DOWNLOAD_BYTES = 150 * 1024 * 1024


def validate_download_url(url: str, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Download URL must use HTTPS.")
    host = (parsed.hostname or "").lower().strip()
    if not host:
        raise ValueError("Download URL is missing hostname.")

    # Reject private/loopback/link-local IP literals
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("Download URL points to a forbidden private or reserved IP address.")
    except ValueError as exc:
        if "forbidden" in str(exc):
            raise

    allowed_hosts = {h.strip().lower() for h in settings.ALLOWED_DOWNLOAD_HOSTS.split(",") if h.strip()}
    trusted_suffixes = (".magichour.ai", ".cloudfront.net", ".amazonaws.com", ".r2.cloudflarestorage.com")
    if host not in allowed_hosts and not host.endswith(trusted_suffixes):
        raise ValueError(f"Download host '{host}' is not in ALLOWED_DOWNLOAD_HOSTS.")


def probe_video_bytes(video_bytes: bytes) -> dict[str, Any]:
    import tempfile

    if len(video_bytes) < 32 or b"ftyp" not in video_bytes[:64]:
        raise ValueError("Downloaded file is not a valid MP4 container.")

    with tempfile.TemporaryDirectory() as tmpdir:
        vid_path = Path(tmpdir) / "probe.mp4"
        thumb_path = Path(tmpdir) / "thumb.jpg"
        vid_path.write_bytes(video_bytes)

        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(vid_path),
        ]
        proc = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode != 0:
            raise ValueError("ffprobe rejected video stream.")
        info = json.loads(proc.stdout or "{}")
        streams = info.get("streams") or []
        if not streams:
            raise ValueError("Video file contains no playable video stream.")
        st = streams[0]
        width = int(st.get("width") or 0)
        height = int(st.get("height") or 0)
        if width < 64 or height < 64:
            raise ValueError("Video dimensions are invalid.")
        codec = str(st.get("codec_name") or "h264")
        dur_raw = st.get("duration") or (info.get("format") or {}).get("duration") or 5.0
        duration = float(dur_raw)
        fps_str = str(st.get("r_frame_rate") or "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            fps = float(num) / max(float(den), 1.0)
        else:
            fps = float(fps_str)

        thumb_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(vid_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={THUMB_MAX_EDGE}:-1",
            str(thumb_path),
        ]
        subprocess.run(thumb_cmd, capture_output=True, timeout=15, check=False)
        thumb_bytes = thumb_path.read_bytes() if thumb_path.exists() else b""

        return {
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "fps": round(fps, 2),
            "codec": codec,
            "thumb_bytes": thumb_bytes,
        }


async def fetch_bounded_url_bytes(
    url: str,
    max_bytes: int,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> bytes:
    validate_download_url(url, settings)
    close_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False)
    try:
        current_url = url
        for _ in range(4):
            validate_download_url(current_url, settings)
            async with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    loc = response.headers.get("location")
                    if not loc:
                        raise ValueError("Redirect missing Location header.")
                    current_url = loc
                    continue
                if response.status_code != 200:
                    raise ValueError(f"Download failed with status {response.status_code}.")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Downloaded media exceeds maximum allowed size.")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise ValueError("Too many redirects while downloading output.")
    finally:
        if close_client:
            await client.aclose()


async def download_and_save_output(
    job_id: str,
    download_url: str,
    settings: Settings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    job_repo = JobRepository(cfg)

    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM generations WHERE id = %s", (job_id,))
            job_row = cur.fetchone()
            if not job_row:
                raise ValueError(f"Job {job_id} not found")
            job = dict(job_row)
            cur.execute("SELECT * FROM assets WHERE id = %s", (job["source_asset_id"],))
            source_asset = dict(cur.fetchone())

    # If output_asset_id is already saved, transition to ready_for_review idempotently
    if job.get("output_asset_id"):
        if job["state"] != "ready_for_review":
            return job_repo.transition_job(
                job_id=job_id,
                next_state="ready_for_review",
                safe_message="Output media already verified in private storage; ready for review.",
                clear_lease=True,
            )
        return job

    try:
        validate_download_url(download_url, cfg)

        if job["kind"] == "image":
            raw_bytes = await fetch_bounded_url_bytes(
                download_url,
                max_bytes=MAX_IMAGE_DOWNLOAD_BYTES,
                settings=cfg,
                http_client=http_client,
            )
            norm = normalize_photo_bytes(raw_bytes, filename="output.jpg", settings=cfg)
            asset_id = f"ast_{secrets.token_hex(8)}"
            token = secrets.token_hex(16)
            owner_prefix = job["owner_id_hash"][:12]
            storage_key = f"private/assets/{owner_prefix}/{token}.jpg"
            thumb_key = f"private/thumbs/{owner_prefix}/{token}_thumb.jpg"

            full_path = cfg.storage_path / storage_key
            thumb_path = cfg.storage_path / thumb_key
            full_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(norm["normalized_bytes"])
            thumb_path.write_bytes(norm["thumb_bytes"])

            now = datetime.now(timezone.utc)
            norm_meta = {
                "thumbnail_key": thumb_key,
                "provider_id": job.get("provider_id"),
                "job_id": job_id,
            }
            with get_db_conn(cfg) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO assets (
                            id, owner_id_hash, project_id, room_id, role, storage_key,
                            sha256, mime_type, bytes_size, source_width, source_height,
                            width, height, normalization_transform_json, created_at
                        )
                        VALUES (%s, %s, %s, %s, 'generated_image', %s, %s, 'image/jpeg', %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            asset_id,
                            job["owner_id_hash"],
                            job["project_id"],
                            job["room_id"],
                            storage_key,
                            norm["sha256"],
                            norm["bytes_size"],
                            norm["width"],
                            norm["height"],
                            norm["width"],
                            norm["height"],
                            json.dumps(norm_meta),
                            now,
                        ),
                    )
        else:
            raw_bytes = await fetch_bounded_url_bytes(
                download_url,
                max_bytes=MAX_VIDEO_DOWNLOAD_BYTES,
                settings=cfg,
                http_client=http_client,
            )
            video_meta = probe_video_bytes(raw_bytes)
            asset_id = f"ast_{secrets.token_hex(8)}"
            token = secrets.token_hex(16)
            owner_prefix = job["owner_id_hash"][:12]
            storage_key = f"private/assets/{owner_prefix}/{token}.mp4"
            thumb_key = f"private/thumbs/{owner_prefix}/{token}_thumb.jpg"

            full_path = cfg.storage_path / storage_key
            thumb_path = cfg.storage_path / thumb_key
            full_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(raw_bytes)
            if video_meta["thumb_bytes"]:
                thumb_path.write_bytes(video_meta["thumb_bytes"])

            sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
            now = datetime.now(timezone.utc)
            norm_meta = {
                "thumbnail_key": thumb_key if video_meta["thumb_bytes"] else None,
                "provider_id": job.get("provider_id"),
                "job_id": job_id,
            }
            with get_db_conn(cfg) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO assets (
                            id, owner_id_hash, project_id, room_id, role, storage_key,
                            sha256, mime_type, bytes_size, width, height,
                            duration_seconds, fps, codec, normalization_transform_json, created_at
                        )
                        VALUES (%s, %s, %s, %s, 'generated_video', %s, %s, 'video/mp4', %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            asset_id,
                            job["owner_id_hash"],
                            job["project_id"],
                            job["room_id"],
                            storage_key,
                            sha256_hex,
                            len(raw_bytes),
                            video_meta["width"],
                            video_meta["height"],
                            video_meta["duration_seconds"],
                            video_meta["fps"],
                            video_meta["codec"],
                            json.dumps(norm_meta),
                            now,
                        ),
                    )

        return job_repo.transition_job(
            job_id=job_id,
            next_state="ready_for_review",
            safe_message="Generated output verified and stored privately; ready for review.",
            output_asset_id=asset_id,
            clear_lease=True,
            safe_payload={"output_asset_id": asset_id},
        )
    except Exception as exc:
        safe_err = {
            "code": "save_failed",
            "message": redact_secrets(f"Output verification or download failed: {exc}"),
            "retryable": True,
        }
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            safe_message="Failed to download or verify provider output. You can retry saving without re-submitting.",
            last_safe_error=safe_err,
            clear_lease=True,
        )
