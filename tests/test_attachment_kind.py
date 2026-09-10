"""Tests for app.telegram.media_sender's AttachmentKind classification --
the single source of truth both the send-side album decision and
app.ui.thumbnails' thumbnail decision now read from, replacing two
independently-maintained extension lists that had silently drifted apart
(a .gif got a real thumbnail but was never album-eligible, with nothing
enforcing that the two lists agreed on why).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.telegram.media_sender import (
    Attachment,
    AttachmentCategory,
    AttachmentKind,
    THUMBNAILABLE_KINDS,
    kind_for_path,
)
from app.ui.thumbnails import is_image


@pytest.mark.parametrize(
    "filename,expected_kind",
    [
        ("photo.jpg", AttachmentKind.PHOTO),
        ("photo.JPG", AttachmentKind.PHOTO),  # case-insensitive
        ("photo.jpeg", AttachmentKind.PHOTO),
        ("photo.png", AttachmentKind.PHOTO),
        ("photo.webp", AttachmentKind.PHOTO),
        ("video.mp4", AttachmentKind.VIDEO),
        ("video.mov", AttachmentKind.VIDEO),
        ("video.avi", AttachmentKind.VIDEO),
        ("clip.gif", AttachmentKind.ANIMATION),
        ("scan.bmp", AttachmentKind.IMAGE_OTHER),
        ("report.pdf", AttachmentKind.DOCUMENT),
        ("data.xlsx", AttachmentKind.DOCUMENT),
        ("archive.zip", AttachmentKind.DOCUMENT),
        ("notes.txt", AttachmentKind.DOCUMENT),
        ("weird.xyz123", AttachmentKind.DOCUMENT),  # unknown extension -> document, never rejected
        ("no_extension_at_all", AttachmentKind.DOCUMENT),
    ],
)
def test_kind_for_path_classifies_every_known_and_unknown_extension(filename, expected_kind):
    assert kind_for_path(Path(filename)) == expected_kind


def test_attachment_kind_property_matches_kind_for_path():
    attachment = Attachment(path=Path("photo.jpg"))
    assert attachment.kind == AttachmentKind.PHOTO


@pytest.mark.parametrize(
    "filename,expected_category",
    [
        ("photo.jpg", AttachmentCategory.ALBUM_ELIGIBLE),
        ("photo.png", AttachmentCategory.ALBUM_ELIGIBLE),
        ("video.mp4", AttachmentCategory.ALBUM_ELIGIBLE),
        ("video.mov", AttachmentCategory.ALBUM_ELIGIBLE),
        # Regression guard: existing behavior before this refactor -- gif and
        # bmp already got a real thumbnail (see test_gif/bmp_is_thumbnailable
        # below) but were never album-eligible, and must stay that way.
        ("clip.gif", AttachmentCategory.SINGLE),
        ("scan.bmp", AttachmentCategory.SINGLE),
        ("report.pdf", AttachmentCategory.SINGLE),
        ("archive.zip", AttachmentCategory.SINGLE),
        ("weird.xyz123", AttachmentCategory.SINGLE),
    ],
)
def test_attachment_category_unchanged_from_pre_refactor_behavior(filename, expected_category):
    assert Attachment(path=Path(filename)).category == expected_category


def test_gif_is_thumbnailable_but_not_album_eligible():
    # This is exactly the discrepancy this refactor documents rather than
    # silently "fixes" by changing behavior: a gif gets a real thumbnail
    # (is_image() True) but is sent as a document, not grouped into an
    # album (category SINGLE) -- both facts below must hold simultaneously.
    path = Path("clip.gif")
    assert is_image(path) is True
    assert Attachment(path=path).category == AttachmentCategory.SINGLE


def test_bmp_is_thumbnailable_but_never_treated_as_telegram_photo():
    # BMP is deliberately excluded from AttachmentKind.PHOTO -- Telegram's
    # own photo pipeline does not reliably accept BMP the way it does
    # JPEG/PNG/WEBP, so it must never become album-eligible even though Qt
    # can decode a local thumbnail for it fine.
    path = Path("scan.bmp")
    assert is_image(path) is True
    assert Attachment(path=path).kind != AttachmentKind.PHOTO
    assert Attachment(path=path).category == AttachmentCategory.SINGLE


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("photo.jpg", True),
        ("photo.png", True),
        ("clip.gif", True),
        ("scan.bmp", True),
        ("video.mp4", False),  # never had a thumbnail before this refactor either
        ("report.pdf", False),
        ("weird.xyz123", False),
    ],
)
def test_is_image_matches_pre_refactor_image_extensions_exactly(filename, expected):
    assert is_image(Path(filename)) is expected


def test_thumbnailable_kinds_and_album_eligible_kinds_are_deliberately_different_questions():
    # PHOTO is the only kind that answers "yes" to both -- everything else
    # in THUMBNAILABLE_KINDS is intentionally NOT album-eligible.
    non_photo_thumbnailable = THUMBNAILABLE_KINDS - {AttachmentKind.PHOTO}
    assert non_photo_thumbnailable == {AttachmentKind.ANIMATION, AttachmentKind.IMAGE_OTHER}
