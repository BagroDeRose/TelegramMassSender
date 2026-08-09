"""Campaign state machine (spec item 24-26).

Explicit, validated transitions -- nothing in the campaign engine is
allowed to jump between states arbitrarily (e.g. two campaigns can't
both claim RUNNING on the same runtime; a paused campaign can't silently
resume without going through resume()).
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Set


class CampaignStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"
    WAITING_FOR_FLOOD = "waiting_for_flood"


_ALLOWED_TRANSITIONS: Dict[CampaignStatus, Set[CampaignStatus]] = {
    CampaignStatus.IDLE: {CampaignStatus.RUNNING},
    CampaignStatus.RUNNING: {
        CampaignStatus.PAUSED,
        CampaignStatus.STOPPING,
        CampaignStatus.COMPLETED,
        CampaignStatus.WAITING_FOR_FLOOD,
        CampaignStatus.ERROR,
    },
    CampaignStatus.PAUSED: {CampaignStatus.RUNNING, CampaignStatus.STOPPING},
    CampaignStatus.WAITING_FOR_FLOOD: {CampaignStatus.PAUSED, CampaignStatus.STOPPING},
    CampaignStatus.STOPPING: {CampaignStatus.STOPPED},
    CampaignStatus.STOPPED: set(),
    CampaignStatus.COMPLETED: set(),
    CampaignStatus.ERROR: set(),
}

TERMINAL_STATES = {CampaignStatus.STOPPED, CampaignStatus.COMPLETED, CampaignStatus.ERROR}


class InvalidStateTransitionError(Exception):
    pass


class CampaignStateMachine:
    def __init__(self, initial: CampaignStatus = CampaignStatus.IDLE) -> None:
        self.status = initial

    def can_transition(self, target: CampaignStatus) -> bool:
        return target in _ALLOWED_TRANSITIONS.get(self.status, set())

    def transition(self, target: CampaignStatus) -> None:
        if not self.can_transition(target):
            raise InvalidStateTransitionError(
                f"Недопустимый переход состояния кампании: {self.status.value} -> {target.value}"
            )
        self.status = target

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def is_active(self) -> bool:
        """True while a campaign occupies this account (blocks switching
        accounts and starting a second campaign) -- spec items 51-52."""
        return self.status in {
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSED,
            CampaignStatus.WAITING_FOR_FLOOD,
            CampaignStatus.STOPPING,
        }
