from app.models.enums import JobState
from app.services.state_machine import can_transition


def test_valid_transition_chain() -> None:
    assert can_transition(JobState.RECEIVED_FROM_SONARR, JobState.VALIDATING)
    assert can_transition(JobState.WAITING_FOR_TORBOX, JobState.TORBOX_READY)
    assert can_transition(JobState.CREATING_SYMLINKS, JobState.READY_FOR_IMPORT)


def test_invalid_transition_is_rejected() -> None:
    assert not can_transition(JobState.RECEIVED_FROM_SONARR, JobState.READY_FOR_IMPORT)
