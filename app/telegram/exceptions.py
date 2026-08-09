"""Domain-specific exceptions for the Telegram integration layer.

Telethon's own exceptions (FloodWaitError, UsernameNotOccupiedError,
UserIsBlockedError, PeerIdInvalidError, ChatWriteForbiddenError,
UserPrivacyRestrictedError, PhoneCodeInvalidError, SessionPasswordNeededError,
etc.) are used directly where they already model the situation precisely --
they are not re-wrapped here. This module only adds the handful of error
conditions that are specific to this application's own rules and have no
Telethon equivalent.
"""
from __future__ import annotations


class TelegramMassSenderError(Exception):
    """Base class for all domain-specific errors in this application."""


class AccountSwitchBlockedError(TelegramMassSenderError):
    """Raised when trying to switch the active account during a campaign."""


class CampaignAlreadyRunningError(TelegramMassSenderError):
    """Raised when trying to start a second campaign on the same account."""


class InvalidRecipientError(TelegramMassSenderError):
    """Raised when a recipient identifier cannot be parsed."""


class RecipientNotFoundError(TelegramMassSenderError):
    """Raised when Telegram cannot resolve the recipient to any entity."""


class RecipientNotAUserError(TelegramMassSenderError):
    """Raised when the resolved entity is a group/channel/bot, not a user."""


class AttachmentNotFoundError(TelegramMassSenderError):
    """Raised when a configured attachment file no longer exists on disk."""
