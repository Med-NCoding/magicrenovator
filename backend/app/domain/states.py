from __future__ import annotations

from typing import Literal

JobState = Literal[
    "admitted",
    "preparing",
    "waiting_for_key",
    "blocked_credits",
    "submitting",
    "submission_unknown",
    "queued",
    "rendering",
    "saving_output",
    "ready_for_review",
    "accepted",
    "rejected",
    "failed",
    "stopped",
]

ALL_JOB_STATES: set[str] = {
    "admitted",
    "preparing",
    "waiting_for_key",
    "blocked_credits",
    "submitting",
    "submission_unknown",
    "queued",
    "rendering",
    "saving_output",
    "ready_for_review",
    "accepted",
    "rejected",
    "failed",
    "stopped",
}

TERMINAL_JOB_STATES: set[str] = {
    "accepted",
    "rejected",
    "failed",
    "stopped",
}

ACTIVE_PROVIDER_STATES: set[str] = {
    "admitted",
    "preparing",
    "submitting",
    "submission_unknown",
    "queued",
    "rendering",
    "saving_output",
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "admitted": {"preparing", "waiting_for_key", "blocked_credits", "failed", "stopped"},
    "preparing": {"submitting", "waiting_for_key", "blocked_credits", "failed", "stopped"},
    "waiting_for_key": {"preparing", "queued", "rendering", "saving_output", "stopped", "failed"},
    "blocked_credits": {"admitted", "preparing", "stopped", "failed"},
    "submitting": {"queued", "rendering", "submission_unknown", "blocked_credits", "waiting_for_key", "failed", "stopped"},
    "submission_unknown": {"queued", "rendering", "failed", "stopped"},
    "queued": {"rendering", "saving_output", "waiting_for_key", "failed", "stopped"},
    "rendering": {"saving_output", "waiting_for_key", "failed", "stopped"},
    "saving_output": {"ready_for_review", "saving_output", "waiting_for_key", "failed", "stopped"},
    "ready_for_review": {"accepted", "rejected", "stopped"},
    "accepted": set(),
    "rejected": set(),
    "failed": {"saving_output", "preparing"},
    "stopped": set(),
}

PERMITTED_NEXT_ACTIONS: dict[str, str] = {
    "admitted": "claim_worker_lease",
    "preparing": "submit_or_fail_input",
    "waiting_for_key": "reconnect_and_continue",
    "blocked_credits": "refresh_and_requote",
    "submitting": "persist_response_or_unknown",
    "submission_unknown": "reconcile_without_paid_replay",
    "queued": "poll_known_id",
    "rendering": "poll_known_id",
    "saving_output": "retry_download_only",
    "ready_for_review": "accept_reject_revise",
    "accepted": "new_stage_with_quote",
    "rejected": "new_revision_with_quote",
    "failed": "safe_recovery_by_failure_type",
    "stopped": "inspect_existing_provider_job",
}


class InvalidStateTransitionError(ValueError):
    pass


def validate_state_transition(current_state: str, next_state: str, has_provider_id: bool = False) -> None:
    if current_state not in ALL_JOB_STATES or next_state not in ALL_JOB_STATES:
        raise InvalidStateTransitionError(f"Unknown state transition: {current_state} -> {next_state}")
    if current_state == next_state:
        return
    allowed = ALLOWED_TRANSITIONS.get(current_state, set())
    if next_state not in allowed:
        raise InvalidStateTransitionError(f"Illegal state transition from {current_state} to {next_state}")
    if has_provider_id and next_state in {"admitted", "preparing", "submitting"}:
        raise InvalidStateTransitionError(
            f"Cannot transition back to pre-submission state {next_state} once provider_id is known"
        )
