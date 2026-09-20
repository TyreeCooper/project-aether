import pytest

from app.state import BotState, IllegalStateTransition, transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (BotState.OFFLINE, BotState.IDLE),
        (BotState.OFFLINE, BotState.IN_POSITION),
        (BotState.IDLE, BotState.IN_POSITION),
        (BotState.IN_POSITION, BotState.IDLE),
        (BotState.IDLE, BotState.FAULT),
        (BotState.IN_POSITION, BotState.FAULT),
        (BotState.FAULT, BotState.OFFLINE),
    ],
)
def test_documented_transitions_are_allowed(current, target):
    assert transition(current, target) is target


def test_same_state_is_idempotent():
    assert transition(BotState.OFFLINE, BotState.OFFLINE) is BotState.OFFLINE


def test_fault_cannot_rearm_directly():
    with pytest.raises(IllegalStateTransition):
        transition(BotState.FAULT, BotState.IDLE)


def test_unknown_state_raises():
    with pytest.raises(ValueError):
        transition("BOGUS", BotState.IDLE)
