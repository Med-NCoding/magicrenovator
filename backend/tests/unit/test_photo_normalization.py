from __future__ import annotations

import io
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.dependencies import apply_migrations, get_db_conn
from app.domain.errors import AppError
from app.main import app
from app.services.asset_service import normalize_photo_bytes, sign_asset_url
from app.settings import get_settings


def _make_textured_room_image(
    width: int = 800,
    height: int = 600,
    mode: str = "RGB",
    fmt: str = "JPEG",
    exif_orientation: int | None = None,
) -> bytes:
    color = (220, 215, 205, 180) if mode == "RGBA" else (220, 215, 205)
    img = Image.new(mode, (width, height), color=color)
    draw = ImageDraw.Draw(img)
    # Draw room cabinets, island, and windows so edge variance is realistic
    for x in range(40, width - 40, 80):
        draw.rectangle([x, 60, x + 60, height - 60], outline=(40, 45, 50), width=3)
    draw.rectangle([120, height // 2, width - 120, height - 40], fill=(160, 140, 120), outline=(30, 30, 30), width=4)

    buf = io.BytesIO()
    if exif_orientation is not None and fmt == "JPEG":
        exif = img.getexif()
        exif[0x0112] = exif_orientation  # Orientation tag
        exif[0x010E] = "Private Camera Description GPS Secret"  # ImageDescription
        img.save(buf, format=fmt, exif=exif.tobytes(), quality=90)
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()


def test_normalize_valid_and_resized_and_exif_and_alpha() -> None:
    # 1. Oversized dimensions (>2048px) get resized preserving aspect ratio
    large_bytes = _make_textured_room_image(width=2800, height=1400, fmt="JPEG")
    res = normalize_photo_bytes(large_bytes, filename="kitchen.jpg")
    assert res["width"] == 2048
    assert res["height"] == 1024
    assert res["resized"] is True
    assert res["orientation_applied"] is False
    assert res["alpha_flattened"] is False
    assert res["blur_advisory"] is False

    # 2. EXIF rotated image (Orientation=6 -> 90 CW) is transposed upright and stripped of EXIF metadata
    rotated_bytes = _make_textured_room_image(width=600, height=900, fmt="JPEG", exif_orientation=6)
    res_rot = normalize_photo_bytes(rotated_bytes, filename="rotated.jpg")
    assert res_rot["orientation_applied"] is True
    assert res_rot["width"] == 900
    assert res_rot["height"] == 600
    # Verify EXIF metadata is completely removed from normalized output
    out_img = Image.open(io.BytesIO(res_rot["normalized_bytes"]))
    assert len(out_img.getexif()) == 0
    assert b"Private Camera Description" not in res_rot["normalized_bytes"]

    # 3. RGBA PNG image has alpha flattened and recorded
    rgba_bytes = _make_textured_room_image(width=640, height=480, mode="RGBA", fmt="PNG")
    res_rgba = normalize_photo_bytes(rgba_bytes, filename="room.png")
    assert res_rgba["alpha_flattened"] is True
    assert res_rgba["true_source_format"] == "PNG"
    assert res_rgba["mime_type"] == "image/jpeg"


def test_reject_false_extension_heic_animated_and_decompression_bomb() -> None:
    settings = get_settings()

    # 1. False extension: text or GIF bytes masquerading as .jpg
    with pytest.raises(AppError) as exc_info:
        normalize_photo_bytes(b"not an image at all", filename="fake.jpg")
    assert exc_info.value.code == "invalid_image"

    gif_img = Image.new("RGB", (200, 200), (100, 100, 100))
    gif_buf = io.BytesIO()
    gif_img.save(gif_buf, format="GIF")
    with pytest.raises(AppError) as exc_gif:
        normalize_photo_bytes(gif_buf.getvalue(), filename="disguised.jpg")
    assert exc_gif.value.code == "invalid_image"

    # 2. Animated WebP rejected
    frame1 = Image.new("RGB", (200, 200), (100, 100, 100))
    frame2 = Image.new("RGB", (200, 200), (180, 180, 180))
    anim_buf = io.BytesIO()
    frame1.save(anim_buf, format="WEBP", save_all=True, append_images=[frame2])
    with pytest.raises(AppError) as exc_anim:
        normalize_photo_bytes(anim_buf.getvalue(), filename="animated.webp")
    assert exc_anim.value.code == "invalid_image"
    assert "Animated" in exc_anim.value.message

    # 3. HEIC magic bytes or .heic filename provides actionable conversion guidance
    heic_header = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 128
    with pytest.raises(AppError) as exc_heic:
        normalize_photo_bytes(heic_header, filename="IMG_1024.HEIC")
    assert exc_heic.value.code == "invalid_image"
    assert "HEIC/HEIF" in exc_heic.value.message
    assert "JPEG, PNG, or WebP" in exc_heic.value.message

    # 4. Oversized byte payload rejected
    oversized = b"\xff\xd8\xff" + b"0" * (settings.MAX_UPLOAD_BYTES + 1024)
    with pytest.raises(AppError) as exc_size:
        normalize_photo_bytes(oversized, filename="huge.jpg")
    assert exc_size.value.code == "invalid_image"
    assert exc_size.value.status_code == 413

    # 5. Huge decoded pixel count (> MAX_IMAGE_PIXELS) rejected before pixel processing
    small_limit_settings = settings.model_copy(update={"MAX_IMAGE_PIXELS": 100_000})
    normal_photo = _make_textured_room_image(width=500, height=500)  # 250,000 pixels > 100,000
    with pytest.raises(AppError) as exc_pixels:
        normalize_photo_bytes(normal_photo, filename="too_many_pixels.jpg", settings=small_limit_settings)
    assert exc_pixels.value.code == "invalid_image"


def test_phase3_api_upload_replace_cross_session_and_tombstone_cleanup() -> None:
    apply_migrations()
    settings = get_settings()
    client_a = TestClient(app)
    client_b = TestClient(app)

    csrf_a = client_a.post("/api/session").json()["csrf_token"]
    csrf_b = client_b.post("/api/session").json()["csrf_token"]
    headers_a = {"X-CSRF-Token": csrf_a}
    headers_b = {"X-CSRF-Token": csrf_b}

    proj = client_a.post("/api/projects", json={"name": "Phase 3 Photo House"}, headers=headers_a).json()
    room = client_a.post(
        f"/api/projects/{proj['id']}/rooms",
        json={"name": "Kitchen", "room_type": "kitchen"},
        headers=headers_a,
    ).json()

    # Upload first room photo
    photo_1 = _make_textured_room_image(width=900, height=600, fmt="JPEG", exif_orientation=6)
    up_res1 = client_a.post(
        f"/api/rooms/{room['id']}/assets",
        files={"file": ("kitchen_1.jpg", photo_1, "image/jpeg")},
        headers=headers_a,
    )
    assert up_res1.status_code == 201
    asset1 = up_res1.json()
    assert asset1["orientation_applied"] is True
    assert asset1["width"] == 600
    assert asset1["height"] == 900

    # Insert a historical brief revision referencing asset1
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_id_hash FROM projects WHERE id = %s", (proj["id"],))
            owner_a_hash = cur.fetchone()["owner_id_hash"]
            cur.execute("DELETE FROM brief_revisions WHERE id = 'brf_hist_1'")
            cur.execute(
                """
                INSERT INTO brief_revisions (
                    id, room_id, source_asset_id, revision_number, raw_text, spec_json,
                    compiled_prompt, source_hash, compiler_version
                )
                VALUES ('brf_hist_1', %s, %s, 1, 'raw', '{}', 'prompt', 'hash1', 'reno-brief-v1')
                """,
                (room["id"], asset1["id"]),
            )

    # Replace room photo with second photo and verify historical revision keeps asset1 reference
    photo_2 = _make_textured_room_image(width=800, height=600, fmt="PNG", mode="RGBA")
    up_res2 = client_a.post(
        f"/api/rooms/{room['id']}/assets",
        files={"file": ("kitchen_2.png", photo_2, "image/png")},
        headers=headers_a,
    )
    assert up_res2.status_code == 201
    asset2 = up_res2.json()
    assert asset2["id"] != asset1["id"]
    assert asset2["alpha_flattened"] is True

    updated_room = client_a.get(f"/api/rooms/{room['id']}").json()
    assert updated_room["primary_asset_id"] == asset2["id"]

    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_asset_id FROM brief_revisions WHERE id = 'brf_hist_1'")
            assert cur.fetchone()["source_asset_id"] == asset1["id"]

    # Owner A can download asset2 via signed URL
    dl_ok = client_a.get(asset2["download_url"])
    assert dl_ok.status_code == 200
    assert dl_ok.headers["content-type"] == "image/jpeg"

    # Cross-session access: Session B cannot download Session A's signed URL or read metadata
    dl_cross = client_b.get(asset2["download_url"])
    assert dl_cross.status_code == 404
    meta_cross = client_b.get(f"/api/assets/{asset2['id']}")
    assert meta_cross.status_code == 404

    # Expired signed link is rejected with 403
    expired_url = sign_asset_url(
        asset2["id"],
        owner_a_hash,
        settings.model_copy(update={"SIGNED_URL_TTL_SECONDS": -10}),
    )
    dl_exp = client_a.get(expired_url)
    assert dl_exp.status_code == 403

    # Verify files exist on disk before tombstone deletion, and are removed after DELETE /api/projects/{id}
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT storage_key, normalization_transform_json FROM assets WHERE id = %s", (asset2["id"],))
            row = cur.fetchone()
            import json

            norm = json.loads(row["normalization_transform_json"])
            file_on_disk = settings.storage_path / row["storage_key"]
            thumb_on_disk = settings.storage_path / norm["thumbnail_key"]
            assert file_on_disk.exists()
            assert thumb_on_disk.exists()

    del_res = client_a.delete(f"/api/projects/{proj['id']}", headers=headers_a)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "tombstoned"
    assert del_res.json()["cleanup_status"] == "cleaned"
    assert not file_on_disk.exists()
    assert not thumb_on_disk.exists()

    # Tombstoned project and its assets are immediately hidden
    assert client_a.get(f"/api/projects/{proj['id']}").status_code == 404
    assert client_a.get(f"/api/assets/{asset2['id']}").status_code == 404
