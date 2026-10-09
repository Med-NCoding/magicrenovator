from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.domain.schemas import (
    BriefRevisionResponse,
    Change,
    CreateBriefRequest,
    RenovationBrief,
    RoomAnnotation,
)
from app.repositories.projects import ProjectRepository
from app.settings import Settings, get_settings

COMPILER_VERSION = "reno-brief-v1"

DEFAULT_PRESERVE_ITEMS = [
    "Room footprint",
    "Windows",
    "Doors",
    "Island position",
    "Appliance positions",
    "Ceiling height",
]

CAMERA_MOTION_PATTERNS = re.compile(
    r"\b(camera\s+(?:pan|push|pull|zoom|tilt|glide|move|movement|orbit|track)|"
    r"pan\s+across|zoom\s+in|zoom\s+out|dolly\s+shot|walkthrough\s+video|animate\s+camera)\b",
    re.IGNORECASE,
)

TARGET_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Cabinets", ["cabinet", "cabinets", "cabinetry", "cupboard", "vanity"]),
    ("Countertops", ["countertop", "countertops", "counters", "worktop"]),
    ("Backsplash", ["backsplash", "splashback", "wall tile"]),
    ("Flooring", ["floor", "flooring", "floors", "hardwood", "tile floor", "carpet", "rug"]),
    ("Walls", ["wall color", "wall colour", "walls", "paint", "wall finish", "accent wall"]),
    ("Hardware", ["hardware", "handles", "pulls", "knobs", "faucet", "tap", "fixtures"]),
    ("Lighting", ["lighting", "pendant", "pendants", "sconce", "chandelier", "light fixture", "recessed lights", "brighter", "tint"]),
    ("Closet", ["closet", "wardrobe"]),
    ("Furniture", ["bed", "headrest", "headboard", "mattress", "nightstand", "sofa", "couch", "dresser"]),
    ("Island", ["island"]),
    ("Appliances", ["appliance", "appliances", "stove", "range", "fridge", "refrigerator", "dishwasher", "oven", "sink"]),
    ("Windows", ["window", "windows", "window frame"]),
    ("Doors", ["door", "doors", "doorway"]),
    ("Ceiling", ["ceiling", "beams"]),
]

PRESERVE_CONFLICT_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "Island position",
        re.compile(
            r"\b(?:move|relocate|remove|delete|demolish|shift|eliminate|get\s+rid\s+of)\b[^.;,]{0,40}\bisland\b|"
            r"\bisland\b[^.;,]{0,40}\b(?:moved|relocated|removed|deleted|eliminated)\b",
            re.IGNORECASE,
        ),
        "Conflict on 'Island position': requested changes move or remove the island while 'Island position' is locked in Preserve.",
    ),
    (
        "Windows",
        re.compile(
            r"\b(?:move|relocate|remove|delete|brick\s+up|close\s+off|eliminate)\b[^.;,]{0,40}\bwindows?\b|"
            r"\bwindows?\b[^.;,]{0,40}\b(?:moved|relocated|removed|deleted|bricked)\b",
            re.IGNORECASE,
        ),
        "Conflict on 'Windows': requested changes move or remove windows while 'Windows' is locked in Preserve.",
    ),
    (
        "Doors",
        re.compile(
            r"\b(?:move|relocate|remove|delete|wall\s+off|close\s+off|eliminate)\b[^.;,]{0,40}\bdoors?(?:way)?\b|"
            r"\bdoors?(?:way)?\b[^.;,]{0,40}\b(?:moved|relocated|removed|deleted)\b",
            re.IGNORECASE,
        ),
        "Conflict on 'Doors': requested changes move or remove a door while 'Doors' is locked in Preserve.",
    ),
    (
        "Appliance positions",
        re.compile(
            r"\b(?:move|relocate|shift|remove)\b[^.;,]{0,40}\b(?:appliances?|stove|range|fridge|refrigerator|sink|dishwasher|oven)\b",
            re.IGNORECASE,
        ),
        "Conflict on 'Appliance positions': requested changes relocate or remove appliances while 'Appliance positions' is locked in Preserve.",
    ),
    (
        "Room footprint",
        re.compile(
            r"\b(?:knock\s+down|tear\s+down|demolish|remove|move|expand|extend)\b[^.;,]{0,40}\b(?:walls?|footprint|structural|layout)\b",
            re.IGNORECASE,
        ),
        "Conflict on 'Room footprint': requested changes alter structural walls or room footprint while 'Room footprint' is locked in Preserve.",
    ),
    (
        "Ceiling height",
        re.compile(
            r"\b(?:raise|lower|drop|vault|alter|change)\b[^.;,]{0,30}\bceiling(?:\s+height)?\b",
            re.IGNORECASE,
        ),
        "Conflict on 'Ceiling height': requested changes alter the ceiling height while 'Ceiling height' is locked in Preserve.",
    ),
]

MOTION_PRESET_PROMPTS: dict[str, str] = {
    "nearly_still": (
        "Maintain a nearly still tripod camera with subtle natural room light; "
        "keep all walls, cabinets, windows, doors, and straight architectural lines completely stable."
    ),
    "gentle_push": (
        "Slow, steady, gentle forward camera push into the renovated room; "
        "keep all walls, cabinets, windows, doors, and straight architectural lines completely stable without warping."
    ),
    "small_lateral": (
        "Slow, subtle lateral camera glide across the renovated room; "
        "keep all walls, cabinets, windows, doors, and straight architectural lines completely stable without warping."
    ),
}


def _sanitize_text(text: str, max_len: int = 2000) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    # Neutralize prompt/config injection tokens attempting to masquerade as key=value or system directives
    cleaned = re.sub(r"(?i)\b(?:ignore\s+previous\s+instructions|system\s+prompt|override\s+gateway)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len]


def _infer_target(clause: str) -> str:
    lower = clause.lower()
    for label, keywords in TARGET_KEYWORDS:
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                return label
    return "Room finish"


def extract_changes_from_text(
    raw_text: str,
    annotations: list[RoomAnnotation] | None = None,
) -> list[Change]:
    sanitized = _sanitize_text(raw_text, max_len=2000)
    action_verbs = r"(?:change|replace|repaint|update|swap|paint|install|refinish|improve|remove|add|make|brighten|darken|upgrade|keep|preserve)"
    raw_clauses = re.split(
        rf"(?:[.;\n]+|,\s*(?:and\s+)?(?={action_verbs}\b)|\band\s+(?={action_verbs}\b))",
        sanitized,
        flags=re.IGNORECASE,
    )
    changes: list[Change] = []

    for clause in raw_clauses:
        c = clause.strip(" ,;:-")
        if not c:
            continue
        # Skip pure preserve clauses since they belong in preserve list
        if re.match(r"^(?:keep|preserve|maintain|do\s+not\s+change|don't\s+change)\b", c, re.IGNORECASE):
            continue
        # Strip camera movement instructions from still image change list
        c_no_cam = CAMERA_MOTION_PATTERNS.sub("", c).strip(" ,;:-")
        if not c_no_cam or len(c_no_cam) < 3:
            continue
        target = _infer_target(c_no_cam)
        changes.append(
            Change(
                target=target[:80],
                description=c_no_cam[:400],
                source="user_text",
            )
        )
        if len(changes) >= 18:
            break

    if annotations:
        for ann in annotations[:2]:
            label_clean = _sanitize_text(ann.label, max_len=60)
            if label_clean:
                changes.append(
                    Change(
                        target=label_clean,
                        description=f"Annotated focus area at ({ann.x:.2f}, {ann.y:.2f}): {label_clean}",
                        source="user_control",
                    )
                )

    if not changes and sanitized:
        fallback_desc = CAMERA_MOTION_PATTERNS.sub("", sanitized).strip(" ,;:-") or "Refresh room finishes realistically"
        changes.append(
            Change(
                target="Room finish",
                description=fallback_desc[:400],
                source="user_text",
            )
        )
    return changes[:20]


def detect_brief_conflicts(
    raw_text: str,
    changes: list[Change],
    preserve: list[str],
    layout_mode: str,
    resolve_conflicts: list[str] | None = None,
) -> list[str]:
    resolved_set = {r.strip().lower() for r in (resolve_conflicts or []) if r.strip()}
    preserve_lower = {p.strip().lower(): p.strip() for p in preserve if p.strip()}
    combined_text = " ; ".join([raw_text, *[f"{c.target}: {c.description}" for c in changes]])

    conflicts: list[str] = []
    for preserve_label, pattern, message in PRESERVE_CONFLICT_RULES:
        key_lower = preserve_label.lower()
        is_locked = key_lower in preserve_lower or (
            preserve_label == "Room footprint" and layout_mode == "preserve"
        )
        if is_locked and key_lower not in resolved_set and message.lower() not in resolved_set:
            if pattern.search(combined_text):
                conflicts.append(message)

    # Check contradictory descriptions on the same target (e.g. white vs black/dark walnut on same target)
    by_target: dict[str, list[str]] = {}
    for c in changes:
        by_target.setdefault(c.target.lower(), []).append(c.description.lower())

    opposing_pairs = [
        ("white", "black"),
        ("white", "dark walnut"),
        ("keep", "remove"),
        ("preserve", "demolish"),
    ]
    for target_key, descs in by_target.items():
        if len(descs) > 1 and target_key not in resolved_set:
            joined = " ".join(descs)
            for a, b in opposing_pairs:
                if re.search(rf"\b{re.escape(a)}\b", joined) and re.search(rf"\b{re.escape(b)}\b", joined):
                    msg = f"Conflict on '{target_key.title()}': contradictory finish instructions ('{a}' vs '{b}')."
                    if msg not in conflicts:
                        conflicts.append(msg)

    return conflicts[:10]


def _infer_room_type_from_text(raw_text: str, fallback_room_type: str) -> str:
    lower = raw_text.lower()
    if fallback_room_type == "kitchen" and not re.search(r"\b(?:kitchen|island|backsplash|countertop|stove|fridge|dishwasher)\b", lower):
        if re.search(r"\b(?:bedroom|bed|headrest|headboard|mattress|nightstand|closet|wardrobe)\b", lower):
            return "bedroom"
        if re.search(r"\b(?:bathroom|shower|bathtub|tub|toilet)\b", lower):
            return "bathroom"
        if re.search(r"\b(?:living\s+room|sofa|couch|fireplace)\b", lower):
            return "living_room"
    return fallback_room_type


def compile_image_prompt(brief: RenovationBrief) -> str:
    if brief.unresolved:
        raise ValueError("Resolve brief conflicts before compiling.")
    clean_user_request = CAMERA_MOTION_PATTERNS.sub("", _sanitize_text(brief.raw_request, 1500)).strip(" ,;:-.")
    filtered_changes: list[str] = []
    for c in brief.changes:
        clean_desc = CAMERA_MOTION_PATTERNS.sub("", c.description).strip(" ,;:-")
        if clean_desc:
            filtered_changes.append(f"{c.target}: {clean_desc}")
    changes_str = "; ".join(filtered_changes) if filtered_changes else "Update requested room surfaces realistically"
    preserve_str = ", ".join(brief.preserve) if brief.preserve else "Room footprint, Windows, Doors"
    layout = (
        "Keep camera viewpoint, room dimensions, walls, doors, windows, and major fixture positions."
        if brief.layout_mode == "preserve"
        else "Allow conceptual layout change only where explicitly requested; keep room camera viewpoint plausible."
    )
    style_clause = f" Style direction: {_sanitize_text(brief.style, 120)}." if brief.style else ""
    lead_clause = f"{clean_user_request}. " if clean_user_request else ""
    return (
        f"{lead_clause}Edit the provided {brief.room_type} photo into a realistic renovation concept. "
        f"{layout} Preserve: {preserve_str}. Requested changes: {changes_str}.{style_clause} "
        "Maintain natural interior lighting, realistic materials, straight vertical lines, and unwarped geometry."
    )


def compile_video_prompt(brief: RenovationBrief, motion_preset: str = "gentle_push") -> str:
    if brief.unresolved:
        raise ValueError("Resolve brief conflicts before compiling.")
    motion_instruction = MOTION_PRESET_PROMPTS.get(motion_preset, MOTION_PRESET_PROMPTS["gentle_push"])
    preserve_str = ", ".join(brief.preserve) if brief.preserve else "Room footprint, Windows, Doors"
    clean_req = CAMERA_MOTION_PATTERNS.sub("", _sanitize_text(brief.raw_request, 1000)).strip(" ,;:-.")
    req_clause = f"Renovated room details: {clean_req}. " if clean_req else ""
    return (
        f"Realistic interior renovation clip of the approved {brief.room_type} concept. "
        f"{req_clause}{motion_instruction} Preserve: {preserve_str}. "
        "No bending edges, no moving cabinets, and no unrequested structural changes."
    )


def compute_brief_source_hash(
    brief: RenovationBrief,
    source_asset_id: str | None,
    accepted_reference_asset_id: str | None = None,
) -> str:
    canonical = {
        "compiler_version": brief.compiler_version,
        "room_type": brief.room_type,
        "layout_mode": brief.layout_mode,
        "style": brief.style or "",
        "preserve": [p.strip() for p in brief.preserve],
        "changes": [{"target": c.target, "description": c.description, "source": c.source} for c in brief.changes],
        "source_asset_id": source_asset_id or "",
        "accepted_reference_asset_id": accepted_reference_asset_id or "",
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BriefService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.project_repo = ProjectRepository(self.settings)

    def _row_to_response(self, row: dict[str, Any]) -> BriefRevisionResponse:
        spec_data = row["spec_json"]
        if isinstance(spec_data, str):
            spec_data = json.loads(spec_data)
        brief = RenovationBrief(**spec_data)
        has_conflicts = bool(row.get("has_unresolved_conflicts") or len(brief.unresolved) > 0)
        created_at = row["created_at"]
        created_str = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
        return BriefRevisionResponse(
            id=row["id"],
            room_id=row["room_id"],
            parent_revision_id=row.get("parent_revision_id"),
            source_asset_id=row.get("source_asset_id"),
            accepted_reference_asset_id=row.get("accepted_reference_asset_id"),
            revision_number=int(row["revision_number"]),
            brief=brief,
            compiled_prompt=row["compiled_prompt"],
            source_hash=row["source_hash"],
            compiler_version=row["compiler_version"],
            has_unresolved_conflicts=has_conflicts,
            quote_eligible=(not has_conflicts and bool(row.get("source_asset_id"))),
            submitted=bool(row.get("submitted", False)),
            created_at=created_str,
        )

    def save_room_brief(
        self,
        owner_id_hash: str,
        room_id: str,
        body: CreateBriefRequest,
    ) -> BriefRevisionResponse:
        room = self.project_repo.get_room_owned(owner_id_hash=owner_id_hash, room_id=room_id)
        raw_clean = _sanitize_text(body.raw_text, max_len=2000)
        if not raw_clean:
            raise AppError(
                code="invalid_brief",
                message="Please enter a renovation description for this room.",
                status_code=400,
                retryable=False,
                next_action="edit_brief",
            )

        effective_room_type = _infer_room_type_from_text(raw_clean, room["room_type"])

        preserve_list = (
            [_sanitize_text(p, 80) for p in body.preserve if _sanitize_text(p, 80)]
            if body.preserve is not None
            else list(DEFAULT_PRESERVE_ITEMS)
        )
        # Strip kitchen-only default preserve items when room is not a kitchen
        if effective_room_type != "kitchen" and not re.search(r"\b(?:island|appliance)\b", raw_clean, re.IGNORECASE):
            preserve_list = [
                p for p in preserve_list if p.lower() not in {"island position", "appliance positions"}
            ]
        # If resolve_conflicts explicitly removes a preserve item, filter it out
        resolve_lower = {r.strip().lower() for r in body.resolve_conflicts if r.strip()}
        if resolve_lower:
            preserve_list = [p for p in preserve_list if p.lower() not in resolve_lower]

        if body.changes is not None and len(body.changes) > 0:
            changes = [
                Change(
                    target=_sanitize_text(c.target, 80) or "Room finish",
                    description=CAMERA_MOTION_PATTERNS.sub("", _sanitize_text(c.description, 400)).strip(" ,;:-")
                    or _sanitize_text(c.description, 400),
                    source=c.source,
                )
                for c in body.changes[:20]
            ]
        else:
            changes = extract_changes_from_text(raw_clean, annotations=body.annotations)

        unresolved = detect_brief_conflicts(
            raw_text=raw_clean,
            changes=changes,
            preserve=preserve_list,
            layout_mode=body.layout_mode,
            resolve_conflicts=body.resolve_conflicts,
        )

        brief = RenovationBrief(
            room_type=effective_room_type,
            raw_request=raw_clean,
            changes=changes,
            preserve=preserve_list[:20],
            layout_mode=body.layout_mode,
            style=_sanitize_text(body.style, 120) if body.style else None,
            unresolved=unresolved,
            compiler_version=COMPILER_VERSION,
        )

        if brief.unresolved:
            compiled_prompt = ""
        else:
            compiled_prompt = compile_image_prompt(brief)

        source_asset_id = room.get("primary_asset_id")
        accepted_ref_id = body.accepted_reference_asset_id or room.get("accepted_image_asset_id")
        source_hash = compute_brief_source_hash(
            brief=brief,
            source_asset_id=source_asset_id,
            accepted_reference_asset_id=accepted_ref_id,
        )

        brief_id = f"brf_{secrets.token_hex(8)}"
        now = datetime.now(timezone.utc)

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, revision_number FROM brief_revisions
                    WHERE room_id = %s
                    ORDER BY revision_number DESC
                    LIMIT 1
                    """,
                    (room_id,),
                )
                latest = cur.fetchone()
                next_rev_num = (int(latest["revision_number"]) + 1) if latest else 1
                parent_id = body.parent_revision_id or (latest["id"] if latest else None)

                cur.execute(
                    """
                    INSERT INTO brief_revisions (
                        id, room_id, parent_revision_id, source_asset_id, accepted_reference_asset_id,
                        revision_number, raw_text, spec_json, compiled_prompt, source_hash,
                        compiler_version, has_unresolved_conflicts, submitted, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                    RETURNING *
                    """,
                    (
                        brief_id,
                        room_id,
                        parent_id,
                        source_asset_id,
                        accepted_ref_id,
                        next_rev_num,
                        raw_clean,
                        json.dumps(brief.model_dump()),
                        compiled_prompt,
                        source_hash,
                        COMPILER_VERSION,
                        bool(brief.unresolved),
                        now,
                    ),
                )
                row = dict(cur.fetchone())
                cur.execute(
                    "UPDATE rooms SET active_brief_revision_id = %s WHERE id = %s",
                    (brief_id, room_id),
                )
                cur.execute(
                    "UPDATE projects SET updated_at = %s WHERE id = %s",
                    (now, room["project_id"]),
                )

        return self._row_to_response(row)

    def get_latest_room_brief(self, owner_id_hash: str, room_id: str) -> BriefRevisionResponse | None:
        self.project_repo.get_room_owned(owner_id_hash=owner_id_hash, room_id=room_id)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM brief_revisions
                    WHERE room_id = %s
                    ORDER BY revision_number DESC
                    LIMIT 1
                    """,
                    (room_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_response(dict(row))

    def get_brief_owned(self, owner_id_hash: str, brief_id: str) -> tuple[dict[str, Any], RenovationBrief, dict[str, Any]]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.*, r.project_id, r.room_type, r.name AS room_name,
                           r.primary_asset_id, r.accepted_image_asset_id, r.accepted_image_review_id
                    FROM brief_revisions b
                    JOIN rooms r ON r.id = b.room_id
                    JOIN projects p ON p.id = r.project_id
                    WHERE b.id = %s AND p.owner_id_hash = %s
                      AND r.deleted_at IS NULL AND p.deleted_at IS NULL
                    """,
                    (brief_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Renovation brief revision not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                row_dict = dict(row)
                spec_data = row_dict["spec_json"]
                if isinstance(spec_data, str):
                    spec_data = json.loads(spec_data)
                brief = RenovationBrief(**spec_data)
                return row_dict, brief, row_dict
