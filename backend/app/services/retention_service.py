from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.dependencies import get_db_conn
from app.settings import Settings, get_settings


class RetentionService:
    """Handles tombstone file cleanup and anonymous retention sweeps."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _safe_unlink(self, storage_key: str | None) -> bool:
        if not storage_key:
            return False
        root = self.settings.storage_path.resolve()
        target = (root / storage_key).resolve()
        if not str(target).startswith(str(root)):
            return False
        if target.exists() and target.is_file():
            target.unlink(missing_ok=True)
            return True
        return False

    def cleanup_tombstoned_projects(self) -> dict[str, int]:
        removed_files = 0
        cleaned_projects = 0
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, owner_id_hash FROM projects
                    WHERE deleted_at IS NOT NULL AND cleanup_status = 'pending_cleanup'
                    """
                )
                projects = [dict(r) for r in cur.fetchall()]
                for proj in projects:
                    cur.execute(
                        """
                        SELECT id, storage_key, normalization_transform_json FROM assets
                        WHERE project_id = %s AND owner_id_hash = %s
                        """,
                        (proj["id"], proj["owner_id_hash"]),
                    )
                    assets = [dict(a) for a in cur.fetchall()]
                    for asset in assets:
                        if self._safe_unlink(asset.get("storage_key")):
                            removed_files += 1
                        norm = asset.get("normalization_transform_json") or {}
                        if isinstance(norm, str):
                            import json

                            norm = json.loads(norm)
                        if self._safe_unlink(norm.get("thumbnail_key")):
                            removed_files += 1
                    cur.execute(
                        """
                        UPDATE projects
                        SET cleanup_status = 'cleaned', updated_at = %s
                        WHERE id = %s
                        """,
                        (datetime.now(timezone.utc), proj["id"]),
                    )
                    cleaned_projects += 1
        return {"cleaned_projects": cleaned_projects, "removed_files": removed_files}

    def sweep_expired_anonymous_projects(self) -> dict[str, int]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.ANONYMOUS_RETENTION_DAYS)
        now = datetime.now(timezone.utc)
        tombstoned = 0
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE projects
                    SET deleted_at = %s, updated_at = %s, cleanup_status = 'pending_cleanup'
                    WHERE deleted_at IS NULL AND created_at < %s
                    RETURNING id, owner_id_hash
                    """,
                    (now, now, cutoff),
                )
                expired_rows = [dict(r) for r in cur.fetchall()]
                for row in expired_rows:
                    tombstoned += 1
                    cur.execute(
                        "UPDATE rooms SET deleted_at = %s WHERE project_id = %s AND deleted_at IS NULL",
                        (now, row["id"]),
                    )
                    cur.execute(
                        "UPDATE assets SET deleted_at = %s WHERE project_id = %s AND deleted_at IS NULL",
                        (now, row["id"]),
                    )
        cleanup_stats = self.cleanup_tombstoned_projects()
        return {
            "expired_projects_tombstoned": tombstoned,
            **cleanup_stats,
        }
