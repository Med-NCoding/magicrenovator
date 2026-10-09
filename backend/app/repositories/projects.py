from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.settings import Settings, get_settings


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class ProjectRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def create_project(self, owner_id_hash: str, name: str) -> dict[str, Any]:
        project_id = _gen_id("prj")
        now = datetime.now(timezone.utc)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projects (id, owner_id_hash, name, is_mock_seed, created_at, updated_at)
                    VALUES (%s, %s, %s, FALSE, %s, %s)
                    RETURNING *
                    """,
                    (project_id, owner_id_hash, name.strip(), now, now),
                )
                row = dict(cur.fetchone())
                row["rooms"] = []
                return row

    def list_projects(self, owner_id_hash: str, cursor: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM projects
                    WHERE owner_id_hash = %s AND deleted_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (owner_id_hash, limit),
                )
                projects = [dict(r) for r in cur.fetchall()]
                for proj in projects:
                    cur.execute(
                        """
                        SELECT * FROM rooms
                        WHERE project_id = %s AND deleted_at IS NULL
                        ORDER BY sort_order ASC, created_at ASC
                        """,
                        (proj["id"],),
                    )
                    rooms = [dict(rm) for rm in cur.fetchall()]
                    for rm in rooms:
                        cur.execute(
                            """
                            SELECT id FROM generations
                            WHERE room_id = %s AND owner_id_hash = %s
                            ORDER BY created_at DESC LIMIT 1
                            """,
                            (rm["id"], owner_id_hash),
                        )
                        latest_job = cur.fetchone()
                        rm["latest_job_id"] = latest_job["id"] if latest_job else None
                    proj["rooms"] = rooms
                return projects

    def get_project(self, owner_id_hash: str, project_id: str) -> dict[str, Any]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM projects
                    WHERE id = %s AND owner_id_hash = %s AND deleted_at IS NULL
                    """,
                    (project_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Project not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                proj = dict(row)
                cur.execute(
                    """
                    SELECT * FROM rooms
                    WHERE project_id = %s AND deleted_at IS NULL
                    ORDER BY sort_order ASC, created_at ASC
                    """,
                    (project_id,),
                )
                rooms = [dict(rm) for rm in cur.fetchall()]
                for rm in rooms:
                    cur.execute(
                        """
                        SELECT id FROM generations
                        WHERE room_id = %s AND owner_id_hash = %s
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (rm["id"], owner_id_hash),
                    )
                    latest_job = cur.fetchone()
                    rm["latest_job_id"] = latest_job["id"] if latest_job else None
                proj["rooms"] = rooms
                return proj

    def tombstone_project(self, owner_id_hash: str, project_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE projects
                    SET deleted_at = %s, updated_at = %s, cleanup_status = 'pending_cleanup'
                    WHERE id = %s AND owner_id_hash = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (now, now, project_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Project not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                cur.execute(
                    "UPDATE rooms SET deleted_at = %s WHERE project_id = %s AND deleted_at IS NULL",
                    (now, project_id),
                )
                cur.execute(
                    "UPDATE assets SET deleted_at = %s WHERE project_id = %s AND owner_id_hash = %s AND deleted_at IS NULL",
                    (now, project_id, owner_id_hash),
                )
                cur.execute(
                    """
                    UPDATE generations
                    SET state = 'stopped', updated_at = %s
                    WHERE project_id = %s AND owner_id_hash = %s
                      AND state NOT IN ('accepted', 'rejected', 'failed', 'stopped')
                    """,
                    (now, project_id, owner_id_hash),
                )
                return dict(row)

    def create_room(
        self,
        owner_id_hash: str,
        project_id: str,
        name: str,
        room_type: str,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM projects WHERE id = %s AND owner_id_hash = %s AND deleted_at IS NULL",
                    (project_id, owner_id_hash),
                )
                if not cur.fetchone():
                    raise AppError(
                        code="not_found",
                        message="Project not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM rooms WHERE project_id = %s AND deleted_at IS NULL",
                    (project_id,),
                )
                cnt = int(cur.fetchone()["cnt"])
                if cnt >= self.settings.MAX_ROOMS_PER_PROJECT:
                    raise AppError(
                        code="room_limit_reached",
                        message=f"Launch projects support up to {self.settings.MAX_ROOMS_PER_PROJECT} rooms.",
                        status_code=400,
                        retryable=False,
                        next_action="none",
                    )
                order_val = sort_order if sort_order is not None else cnt
                room_id = _gen_id("rm")
                now = datetime.now(timezone.utc)
                cur.execute(
                    """
                    INSERT INTO rooms (id, project_id, room_type, name, sort_order, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (room_id, project_id, room_type.strip(), name.strip(), order_val, now),
                )
                room_row = dict(cur.fetchone())
                cur.execute("UPDATE projects SET updated_at = %s WHERE id = %s", (now, project_id))
                return room_row

    def get_room_owned(self, owner_id_hash: str, room_id: str) -> dict[str, Any]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.*, p.owner_id_hash, p.name AS project_name
                    FROM rooms r
                    JOIN projects p ON p.id = r.project_id
                    WHERE r.id = %s AND r.deleted_at IS NULL
                      AND p.owner_id_hash = %s AND p.deleted_at IS NULL
                    """,
                    (room_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Room not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                return dict(row)

    def update_room(
        self,
        owner_id_hash: str,
        room_id: str,
        name: str | None = None,
        room_type: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        room = self.get_room_owned(owner_id_hash, room_id)
        new_name = name.strip() if name is not None else room["name"]
        new_type = room_type.strip() if room_type is not None else room["room_type"]
        new_order = sort_order if sort_order is not None else room["sort_order"]
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE rooms
                    SET name = %s, room_type = %s, sort_order = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (new_name, new_type, new_order, room_id),
                )
                return dict(cur.fetchone())
