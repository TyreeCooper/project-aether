"""Explicit bot-state transitions."""

from __future__ import annotations

from enum import Enum


class BotState(str, Enum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    IN_POSITION = "IN_POSITION"
    FAULT = "FAULT"


_ALLOWED: dict[BotState, set[BotState]] = {
    BotState.OFFLINE: {BotState.IDLE, BotState.IN_POSITION, BotState.FAULT},
    BotState.IDLE: {BotState.OFFLINE, BotState.IN_POSITION, BotState.FAULT},
    BotState.IN_POSITION: {BotState.OFFLINE, BotState.IDLE, BotState.FAULT},
    BotState.FAULT: {BotState.OFFLINE},
}


class IllegalStateTransition(ValueError):
    pass


def transition(current: BotState | str, target: BotState | str) -> BotState:
    current_state = BotState(current)
    target_state = BotState(target)
    if target_state == current_state:
        return current_state
    if target_state not in _ALLOWED[current_state]:
        raise IllegalStateTransition(
            f"illegal state transition: {current_state.value} -> {target_state.value}"
        )
    return target_state
