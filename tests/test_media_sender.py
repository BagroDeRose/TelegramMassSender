"""Tests for Attachment's file-validation logic (existence + readability)
in app/telegram/media_sender.py. Missing-file / build_media_send_plan
integration was previously only exercised indirectly through
AttachmentsWidget's missing_files() UI tests -- this covers the domain
logic itself directly, including the new unreadable-file distinction
(v1.4 stage 4: a file that exists but can't be opened for reading, e.g.
locked or permission-denied, is now reported separately from a missing
one).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.telegram.exceptions import AttachmentNotFoundError, AttachmentUnreadableError
from app.telegram.media_sender import Attachment, build_media_send_plan


def test_validate_exists_passes_for_a_real_file(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")
    Attachment(path=path).validate_exists()  # must not raise


def test_validate_exists_raises_for_a_missing_file(tmp_path):
    path = tmp_path / "gone.pdf"
    with pytest.raises(AttachmentNotFoundError):
        Attachment(path=path).validate_exists()


def test_is_readable_true_for_a_normal_file(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")
    assert Attachment(path=path).is_readable() is True


def test_is_readable_true_for_an_empty_file(tmp_path):
    # A zero-byte file is a healthy, valid attachment -- read(1) returning
    # b"" (not raising) must count as readable, not unreadable.
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    assert Attachment(path=path).is_readable() is True


def test_is_readable_false_when_open_raises_os_error(tmp_path):
    # A real permission-denied/locked-file condition is not reliably
    # reproducible cross-platform in a test (Windows file sharing
    # semantics in particular don't let a second open() in the same
    # process simulate a lock the way POSIX chmod does) -- patching
    # Path.open to raise OSError deterministically exercises the same
    # except-branch a real locked/permission-denied file would hit.
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"x")
    with patch.object(Path, "open", side_effect=PermissionError("Access is denied")):
        assert Attachment(path=path).is_readable() is False


def test_validate_readable_raises_attachment_unreadable_error(tmp_path):
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"x")
    with patch.object(Path, "open", side_effect=PermissionError("Access is denied")):
        with pytest.raises(AttachmentUnreadableError):
            Attachment(path=path).validate_readable()


def test_validate_readable_passes_for_a_healthy_file(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")
    Attachment(path=path).validate_readable()  # must not raise


def test_build_media_send_plan_raises_not_found_for_missing_attachment(tmp_path):
    missing = Attachment(path=tmp_path / "gone.pdf")
    with pytest.raises(AttachmentNotFoundError):
        build_media_send_plan([missing], "hello", [])


def test_build_media_send_plan_raises_unreadable_for_locked_attachment(tmp_path):
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"x")
    attachment = Attachment(path=path)
    with patch.object(Path, "open", side_effect=PermissionError("Access is denied")):
        with pytest.raises(AttachmentUnreadableError):
            build_media_send_plan([attachment], "hello", [])


def test_build_media_send_plan_checks_existence_before_readability(tmp_path):
    # A missing file must be reported as "not found", not misreported as
    # "unreadable" -- validate_exists() runs first in the plan-building loop.
    missing = Attachment(path=tmp_path / "gone.pdf")
    with pytest.raises(AttachmentNotFoundError):
        build_media_send_plan([missing], "hello", [])
