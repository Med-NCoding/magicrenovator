from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.domain.schemas import AssetMetadataResponse, RoomAnnotation
from app.repositories.projects import ProjectRepository
from app.settings import Settings, get_settings

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
HEIC_BRANDS = (
    b"ftypheic",
    b"ftypheix",
    b"ftyphevc",
    b"ftypheim",
    b"ftypmif1",
    b"ftypmsf1",
    b"ftypavif",
)
NEUTRAL_BG_RGB = (245, 244, 240)
MAX_NORMALIZED_EDGE = 2048
THUMB_MAX_EDGE = 480


def sign_asset_url(
    asset_id: str,
    owner_id_hash: str,
    settings: Settings | None = None,
    variant: str = "full",
) -> str:
    cfg = settings or get_settings()
    exp = int(time.time()) + cfg.SIGNED_URL_TTL_SECONDS
    payload = f"{asset_id}:{owner_id_hash}:{variant}:{exp}"
    sig = hmac.new(
        cfg.SESSION_SIGNING_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"/api/assets/{asset_id}/download?variant={variant}&exp={exp}&sig={sig}"


def verify_signed_asset_url(
    asset_id: str,
    owner_id_hash: str,
    variant: str,
    exp: int,
    sig: str,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    now = int(time.time())
    if exp < now:
        raise AppError(
            code="not_found",
            message="Signed asset link has expired. Refresh to get a new link.",
            status_code=403,
            retryable=True,
            next_action="refresh_project",
        )
    payload = f"{asset_id}:{owner_id_hash}:{variant}:{exp}"
    expected = hmac.new(
        cfg.SESSION_SIGNING_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise AppError(
            code="not_found",
            message="Asset not found.",
            status_code=404,
            retryable=False,
            next_action="none",
        )


def _is_heic_signature(raw_bytes: bytes, filename: str | None) -> bool:
    header = raw_bytes[:64].lower()
    if any(brand in header for brand in HEIC_BRANDS):
        return True
    if filename:
        lower_name = filename.lower().strip()
        if lower_name.endswith(".heic") or lower_name.endswith(".heif"):
            return True
    return False


def _assess_blur_and_aspect(rgb_img: Image.Image) -> tuple[bool, str | None]:
    w, h = rgb_img.size
    aspect = w / float(max(h, 1))
    if aspect > 3.2 or aspect < 0.31:
        return (
            True,
            "Extreme panoramic or narrow aspect ratio detected. A standard horizontal or vertical room framing produces more consistent geometry.",
        )
    sample = rgb_img.convert("L").resize((min(w, 256), min(h, 256)), Image.Resampling.BILINEAR)
    edges = sample.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(edges)
    edge_stddev = stat.stddev[0] if stat.stddev else 0.0
    if edge_stddev < 4.5:
        return (
            True,
            "Photo appears very soft or low-contrast. Clear lighting and visible room edges improve renovation fidelity.",
        )
    return False, None


def normalize_photo_bytes(
    raw_bytes: bytes,
    filename: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Validate, decode, orient, strip metadata, flatten alpha, resize within bounds,
    and generate normalized JPEG + thumbnail bytes.
    """
    cfg = settings or get_settings()
    if not raw_bytes:
        raise AppError(
            code="invalid_image",
            message="Uploaded image file is empty.",
            status_code=400,
            retryable=False,
            next_action="upload_valid_image",
        )
    if len(raw_bytes) > cfg.MAX_UPLOAD_BYTES:
        raise AppError(
            code="invalid_image",
            message=f"Image file exceeds the {cfg.MAX_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit.",
            status_code=413,
            retryable=False,
            next_action="upload_smaller_image",
        )

    if _is_heic_signature(raw_bytes, filename):
        raise AppError(
            code="invalid_image",
            message=(
                "HEIC/HEIF photos are not supported directly. "
                "Please export or save the photo as JPEG, PNG, or WebP and upload again."
            ),
            status_code=400,
            retryable=False,
            next_action="convert_heic_to_jpeg",
        )

    old_max_pixels = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = cfg.MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                img = Image.open(io.BytesIO(raw_bytes))
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise AppError(
                    code="invalid_image",
                    message=f"Image dimensions exceed the maximum safe limit of {cfg.MAX_IMAGE_PIXELS:,} pixels.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_smaller_image",
                ) from exc
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise AppError(
                    code="invalid_image",
                    message="File is not a valid supported image. Upload a JPEG, PNG, or WebP photo.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_valid_image",
                ) from exc

            true_format = (img.format or "").upper()
            if true_format not in ALLOWED_FORMATS:
                raise AppError(
                    code="invalid_image",
                    message=f"Unsupported image format '{true_format or 'unknown'}'. Only JPEG, PNG, and WebP still photos are accepted.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_valid_image",
                )

            if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
                raise AppError(
                    code="invalid_image",
                    message="Animated or multi-frame images are not supported. Upload a single still room photo.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_still_image",
                )

            source_width, source_height = img.size
            if source_width * source_height > cfg.MAX_IMAGE_PIXELS:
                raise AppError(
                    code="invalid_image",
                    message=f"Image dimensions ({source_width}x{source_height}) exceed the {cfg.MAX_IMAGE_PIXELS:,} pixel limit.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_smaller_image",
                )
            if source_width < 32 or source_height < 32:
                raise AppError(
                    code="invalid_image",
                    message="Image dimensions are too small. Upload a room photo at least 32x32 pixels.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_larger_image",
                )

            img.load()

            orientation_applied = False
            try:
                exif = img.getexif()
                orientation_tag = exif.get(0x0112) if exif else None
                if orientation_tag is not None and orientation_tag != 1:
                    orientation_applied = True
            except Exception:
                orientation_tag = None

            if orientation_applied:
                img = ImageOps.exif_transpose(img)

            oriented_width, oriented_height = img.size

            alpha_flattened = False
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (*NEUTRAL_BG_RGB, 255))
                composited = Image.alpha_composite(background, rgba)
                rgb_source = composited.convert("RGB")
                alpha_flattened = True
            else:
                rgb_source = img.convert("RGB")

            resized = False
            target_w, target_h = rgb_source.size
            max_edge = max(target_w, target_h)
            if max_edge > MAX_NORMALIZED_EDGE:
                scale = MAX_NORMALIZED_EDGE / float(max_edge)
                target_w = max(1, int(round(target_w * scale)))
                target_h = max(1, int(round(target_h * scale)))
                rgb_source = rgb_source.resize((target_w, target_h), Image.Resampling.LANCZOS)
                resized = True

            # Strip all EXIF, GPS, XMP, ICC, and embedded thumbnail metadata by copying raw pixels into a fresh RGB canvas
            clean_img = Image.new("RGB", rgb_source.size)
            clean_img.paste(rgb_source)

            blur_advisory, advisory_message = _assess_blur_and_aspect(clean_img)

            out_buf = io.BytesIO()
            clean_img.save(out_buf, format="JPEG", quality=92, optimize=True)
            normalized_bytes = out_buf.getvalue()

            thumb_img = clean_img.copy()
            thumb_img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE), Image.Resampling.LANCZOS)
            thumb_buf = io.BytesIO()
            thumb_img.save(thumb_buf, format="JPEG", quality=85, optimize=True)
            thumb_bytes = thumb_buf.getvalue()

            sha256_hex = hashlib.sha256(normalized_bytes).hexdigest()

            return {
                "normalized_bytes": normalized_bytes,
                "thumb_bytes": thumb_bytes,
                "mime_type": "image/jpeg",
                "bytes_size": len(normalized_bytes),
                "sha256": sha256_hex,
                "source_width": oriented_width if orientation_applied else source_width,
                "source_height": oriented_height if orientation_applied else source_height,
                "raw_width": source_width,
                "raw_height": source_height,
                "width": clean_img.width,
                "height": clean_img.height,
                "orientation_applied": orientation_applied,
                "alpha_flattened": alpha_flattened,
                "resized": resized,
                "true_source_format": true_format,
                "blur_advisory": blur_advisory,
                "advisory_message": advisory_message,
            }
    finally:
        Image.MAX_IMAGE_PIXELS = old_max_pixels


class AssetService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.project_repo = ProjectRepository(self.settings)

    def _format_asset(self, row: dict[str, Any], owner_id_hash: str) -> AssetMetadataResponse:
        norm = row.get("normalization_transform_json") or {}
        if isinstance(norm, str):
            norm = json.loads(norm)
        annotations_raw = row.get("annotations_json") or []
        if isinstance(annotations_raw, str):
            annotations_raw = json.loads(annotations_raw)
        annotations = [RoomAnnotation(**a) for a in annotations_raw if isinstance(a, dict)]
        created_at = row["created_at"]
        created_str = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
        return AssetMetadataResponse(
            id=row["id"],
            room_id=row.get("room_id"),
            project_id=row["project_id"],
            role=row["role"],
            mime_type=row["mime_type"],
            bytes_size=int(row["bytes_size"]),
            source_width=row.get("source_width"),
            source_height=row.get("source_height"),
            width=int(row.get("width") or 0),
            height=int(row.get("height") or 0),
            duration_seconds=float(row["duration_seconds"]) if row.get("duration_seconds") is not None else None,
            orientation_applied=bool(row.get("orientation_applied", False)),
            alpha_flattened=bool(row.get("alpha_flattened", False)),
            blur_advisory=bool(row.get("blur_advisory", False)),
            advisory_message=norm.get("advisory_message"),
            thumbnail_url=sign_asset_url(row["id"], owner_id_hash, self.settings, variant="thumb"),
            download_url=sign_asset_url(row["id"], owner_id_hash, self.settings, variant="full"),
            annotations=annotations,
            created_at=created_str,
        )

    def upload_room_photo(
        self,
        owner_id_hash: str,
        room_id: str,
        raw_bytes: bytes,
        filename: str | None = None,
        annotations: list[RoomAnnotation] | None = None,
    ) -> AssetMetadataResponse:
        room = self.project_repo.get_room_owned(owner_id_hash=owner_id_hash, room_id=room_id)
        project_id = room["project_id"]

        norm_result = normalize_photo_bytes(raw_bytes=raw_bytes, filename=filename, settings=self.settings)

        asset_id = f"ast_{secrets.token_hex(8)}"
        random_token = secrets.token_hex(16)
        owner_prefix = owner_id_hash[:12]
        storage_key = f"private/assets/{owner_prefix}/{random_token}.jpg"
        thumb_key = f"private/thumbs/{owner_prefix}/{random_token}_thumb.jpg"

        full_path = (self.settings.storage_path / storage_key).resolve()
        thumb_path = (self.settings.storage_path / thumb_key).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)

        full_path.write_bytes(norm_result["normalized_bytes"])
        thumb_path.write_bytes(norm_result["thumb_bytes"])

        normalization_meta = {
            "true_source_format": norm_result["true_source_format"],
            "raw_width": norm_result["raw_width"],
            "raw_height": norm_result["raw_height"],
            "resized": norm_result["resized"],
            "advisory_message": norm_result["advisory_message"],
            "thumbnail_key": thumb_key,
        }
        annotations_list = [a.model_dump() for a in (annotations or [])]
        now = datetime.now(timezone.utc)

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO assets (
                        id, project_id, room_id, owner_id_hash, role, storage_key,
                        mime_type, bytes_size, sha256, source_width, source_height, width, height,
                        orientation_applied, alpha_flattened, blur_advisory,
                        annotations_json, normalization_transform_json, created_at
                    )
                    VALUES (%s, %s, %s, %s, 'original_photo', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        asset_id,
                        project_id,
                        room_id,
                        owner_id_hash,
                        storage_key,
                        norm_result["mime_type"],
                        norm_result["bytes_size"],
                        norm_result["sha256"],
                        norm_result["source_width"],
                        norm_result["source_height"],
                        norm_result["width"],
                        norm_result["height"],
                        norm_result["orientation_applied"],
                        norm_result["alpha_flattened"],
                        norm_result["blur_advisory"],
                        json.dumps(annotations_list),
                        json.dumps(normalization_meta),
                        now,
                    ),
                )
                asset_row = dict(cur.fetchone())
                # Update room's primary_asset_id while leaving historical brief_revisions.source_asset_id intact
                cur.execute(
                    """
                    UPDATE rooms
                    SET primary_asset_id = %s
                    WHERE id = %s
                    """,
                    (asset_id, room_id),
                )
                cur.execute(
                    "UPDATE projects SET updated_at = %s WHERE id = %s",
                    (now, project_id),
                )

        return self._format_asset(asset_row, owner_id_hash)

    def get_asset_owned(self, owner_id_hash: str, asset_id: str) -> dict[str, Any]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.*
                    FROM assets a
                    JOIN projects p ON p.id = a.project_id
                    WHERE a.id = %s AND a.owner_id_hash = %s
                      AND a.deleted_at IS NULL AND p.deleted_at IS NULL
                    """,
                    (asset_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Asset not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                return dict(row)

    def get_asset_metadata(self, owner_id_hash: str, asset_id: str) -> AssetMetadataResponse:
        row = self.get_asset_owned(owner_id_hash, asset_id)
        return self._format_asset(row, owner_id_hash)

    def update_annotations(
        self,
        owner_id_hash: str,
        asset_id: str,
        annotations: list[RoomAnnotation],
    ) -> AssetMetadataResponse:
        self.get_asset_owned(owner_id_hash, asset_id)
        annotations_list = [a.model_dump() for a in annotations]
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE assets
                    SET annotations_json = %s
                    WHERE id = %s AND owner_id_hash = %s
                    RETURNING *
                    """,
                    (json.dumps(annotations_list), asset_id, owner_id_hash),
                )
                updated = dict(cur.fetchone())
        return self._format_asset(updated, owner_id_hash)

    def resolve_download_path(
        self,
        owner_id_hash: str,
        asset_id: str,
        variant: str,
        exp: int,
        sig: str,
    ) -> tuple[Path, str]:
        verify_signed_asset_url(
            asset_id=asset_id,
            owner_id_hash=owner_id_hash,
            variant=variant,
            exp=exp,
            sig=sig,
            settings=self.settings,
        )
        row = self.get_asset_owned(owner_id_hash=owner_id_hash, asset_id=asset_id)
        norm = row.get("normalization_transform_json") or {}
        if isinstance(norm, str):
            norm = json.loads(norm)
        thumb_key = norm.get("thumbnail_key")
        storage_key = thumb_key if (variant == "thumb" and thumb_key) else row["storage_key"]
        mime_type = "image/jpeg" if variant == "thumb" else row["mime_type"]

        root = self.settings.storage_path.resolve()
        target = (root / storage_key).resolve()
        if not str(target).startswith(str(root)) or not target.exists() or not target.is_file():
            raise AppError(
                code="not_found",
                message="Asset file is not available.",
                status_code=404,
                retryable=False,
                next_action="none",
            )
        return target, mime_type
