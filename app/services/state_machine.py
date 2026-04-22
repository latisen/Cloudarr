"""Job state machine transitions and validation."""

from app.models.enums import JobState


ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.RECEIVED_FROM_SONARR: {JobState.VALIDATING, JobState.FAILED},
    JobState.VALIDATING: {JobState.SUBMITTED_TO_TORBOX, JobState.FAILED},
    JobState.SUBMITTED_TO_TORBOX: {JobState.WAITING_FOR_TORBOX, JobState.FAILED},
    JobState.WAITING_FOR_TORBOX: {JobState.TORBOX_READY, JobState.FAILED, JobState.NEEDS_ATTENTION},
    JobState.TORBOX_READY: {JobState.REFRESHING_WEBDAV, JobState.FAILED},
    JobState.REFRESHING_WEBDAV: {JobState.WEBDAV_VISIBLE, JobState.NEEDS_ATTENTION, JobState.FAILED},
    JobState.WEBDAV_VISIBLE: {JobState.CREATING_SYMLINKS, JobState.FAILED},
    JobState.CREATING_SYMLINKS: {JobState.READY_FOR_IMPORT, JobState.FAILED},
    JobState.READY_FOR_IMPORT: {JobState.IMPORTED_OPTIONAL_DETECTED},
    JobState.IMPORTED_OPTIONAL_DETECTED: set(),
    JobState.NEEDS_ATTENTION: {JobState.REFRESHING_WEBDAV, JobState.FAILED},
    JobState.FAILED: set(),
}


def can_transition(current: JobState, nxt: JobState) -> bool:
    """Return True when transition is legal."""

    return nxt in ALLOWED_TRANSITIONS[current]
