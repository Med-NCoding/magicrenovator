# RenoPreview Evaluation Rubric (`reno-benchmark-v1`)

This rubric defines the release-readiness quality and safety criteria evaluated by `python benchmark/run.py --mode mock`.

## 1. Prompt Compilation & Structural Preservation
- **Preservation Locks Included**: Every compiled still-image prompt must explicitly include the room's active preservation constraints (`Room footprint`, `Windows`, `Doors`, `Island position`, etc.).
- **Zero Banned Embellishments**: Compiled prompts must never inject unrequested stylistic filler tokens (`8k`, `masterpiece`, `award-winning`, `trending on artstation`, `unreal engine`, `hyperrealistic`, `octane render`).
- **Camera Motion Separation**: Still-image compilation (`compile_brief`) must strip or exclude camera movement terms (`dolly`, `pan`, `zoom`, `push in`) so still geometry remains anchored to the user's photo viewpoint, while video compilation (`compile_video_motion_prompt`) applies conservative interior camera presets (`nearly_still`, `gentle_push`, `small_lateral`).

## 2. Conflict Detection Gate
- **Structural vs. Preservation Lock Conflict**: When a user's raw text requests removing or relocating a locked element (e.g., `"Remove the kitchen island"` while `"Island position"` is locked), the compiler must flag `has_unresolved_conflicts = True` and block quote creation (`quote_eligible = False`) until the conflict is resolved.

## 3. Credit Quote & Human Verification Gate
- **Pre-Spend Quote Accuracy**: Every image and video generation must be preceded by a deterministic credit quote matching `config/model-catalog.json`.
- **Mandatory Still Review Gate**: Video quotes (`kind="video"`) must be rejected with `409 Conflict` (`next_action="accept_still_image"`) until the room's generated still concept has been explicitly accepted via human review (`POST /api/assets/{id}/reviews`).

## 4. Local FFmpeg Presentation Assembly & Zero Provider Spend
- **Normalized H.264 Output**: Assembled house presentations must be rendered locally via FFmpeg to `1280x720@30fps` H.264 (`yuv420p`) MP4 with sanitized label overlays and accompanied by a Markdown renovator handoff brief containing the concept limitation notice.
- **Zero Provider Calls During Assembly**: Local presentation assembly must never invoke paid Magic Hour endpoints.
