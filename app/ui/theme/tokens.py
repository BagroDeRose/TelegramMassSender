"""Design tokens: the only module where raw colours, sizes and font names
live. Everything else -- the generated QSS, the QPalette, the SVG icon
tint, rich-text HTML in the message preview -- reads from here, so the
dark and light themes are two value sets of one structure and can't drift
apart.

"Quiet console": an almost monochrome base; colour only carries meaning
(status, progress, the single primary action). Contrast choices that
departed from the brief's starting values are recorded in docs/design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.config.settings import DEFAULT_THEME

THEME_LIGHT = "light"
THEME_DARK = "dark"
VALID_THEMES = (THEME_DARK, THEME_LIGHT)

# ---- scale (identical in both themes) ----------------------------------------

FONT_FAMILY = "Inter"
FONT_FAMILY_FALLBACK = "Segoe UI"
FONT_FAMILY_MONO = "Cascadia Mono"
FONT_FAMILY_MONO_FALLBACK = "Consolas"

# Spacing: multiples of 4 only.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32
SPACE_XXXL = 32  # kept for callers of the old 7-step scale; same as XXL

RADIUS_SM = 6  # fields, buttons
RADIUS_MD = 10  # cards
RADIUS_LG = 14  # dialogs, chat bubble
RADIUS_PILL = 999

# Type scale 12 / 13 / 15 / 20 / 26, weights 400 / 500 / 600.
FONT_SIZE_CAPTION = 12
FONT_SIZE_HELPER = 12
FONT_SIZE_BODY = 13
FONT_SIZE_CARD_TITLE = 15
FONT_SIZE_PAGE_TITLE = 20
FONT_SIZE_STAT_VALUE = 26
FONT_WEIGHT_REGULAR = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600

# Layout metrics.
SIDEBAR_WIDTH = 220
SIDEBAR_COLLAPSED_WIDTH = 64
SIDEBAR_ACTIVE_BAR = 3
JOURNAL_WIDTH = 320
CONTROL_HEIGHT = 32
CONTROL_WIDTH = 280  # the one width settings controls share
ICON_SIZE_SM = 14
ICON_SIZE = 16
ICON_SIZE_NAV = 18
ICON_SIZE_EMPTY = 32
AVATAR_SIZE = 32
AVATAR_SIZE_LG = 40
STATUS_DOT = 8
FOCUS_RING = 2
LAUNCH_PANEL_WIDTH = 380
TWO_COLUMN_MIN_WIDTH = 1100
TOAST_WIDTH = 340
ACCOUNT_CARD_MAX_WIDTH = 760
CONTENT_MAX_WIDTH = 1120
PREVIEW_BUBBLE_MAX_WIDTH = 340
PREVIEW_BUBBLE_PADDING = 12
PREVIEW_TAIL = 8
PREVIEW_ALBUM_GAP = 2
PREVIEW_MIN_HEIGHT = 220

# Motion: short ease-out only, nothing that loops.
MOTION_FAST_MS = 120
MOTION_MS = 160
MOTION_SLOW_MS = 180
TOAST_DURATION_MS = 3000


# ---- colour helpers -----------------------------------------------------------


def _rgb(hex_color: str):
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def mix(color_a: str, color_b: str, amount: float) -> str:
    """color_a moved `amount` (0..1) of the way towards color_b."""
    a, b = _rgb(color_a), _rgb(color_b)
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def alpha(color: str, opacity: float) -> str:
    r, g, b = _rgb(color)
    return f"rgba({r}, {g}, {b}, {opacity:.2f})"


@dataclass(frozen=True)
class Tokens:
    # Surfaces.
    bg: str
    surface: str
    surface_elevated: str
    sidebar: str
    border: str
    border_subtle: str
    # Text.
    text_primary: str
    text_secondary: str
    text_muted: str
    # Accent (the one primary action, focus, selection, progress).
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    on_accent: str
    # Status.
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    error: str
    error_soft: str
    info: str
    info_soft: str
    # Controls.
    input_bg: str
    hover: str
    pressed: str
    disabled_bg: str
    disabled_text: str
    focus_ring: str
    overlay: str
    # Message preview ("chat" look) -- only place allowed some expression.
    chat_bg: str
    bubble: str
    bubble_text: str
    bubble_meta: str
    # Rich text that QSS can't reach (QTextCharFormat / inline HTML).
    link: str
    spoiler_bg: str
    spoiler_preview: str
    code_bg: str
    placeholder: str
    # Letterboxing behind image thumbnails.
    thumbnail_bg: str
    favorite: str
    selected_account: str
    # Scrollbars / spin boxes (QSS sub-controls).
    scrollbar_track: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    scrollbar_handle_pressed: str
    spinbox_button: str
    spinbox_button_hover: str
    spinbox_button_pressed: str
    spinbox_arrow: str
    # Is this the dark theme (title bar, palette base choices)?
    is_dark: bool


def _make(
    *,
    is_dark: bool,
    bg: str,
    surface: str,
    elevated: str,
    border: str,
    text: str,
    text_secondary: str,
    text_muted: str,
    accent: str,
    on_accent: str,
    success: str,
    warning: str,
    error: str,
    input_bg: str,
    chat_bg: str,
    bubble: str,
) -> Tokens:
    toward = "#ffffff" if is_dark else "#000000"
    hover = mix(surface, text, 0.06)
    pressed = mix(surface, text, 0.10)
    return Tokens(
        bg=bg,
        surface=surface,
        surface_elevated=elevated,
        sidebar=surface,
        border=border,
        border_subtle=mix(border, surface, 0.45),
        text_primary=text,
        text_secondary=text_secondary,
        text_muted=text_muted,
        accent=accent,
        accent_hover=mix(accent, toward, 0.12),
        accent_pressed=mix(accent, toward, 0.22) if not is_dark else mix(accent, "#000000", 0.14),
        accent_soft=alpha(accent, 0.14),
        on_accent=on_accent,
        success=success,
        success_soft=alpha(success, 0.12),
        warning=warning,
        warning_soft=alpha(warning, 0.12),
        error=error,
        error_soft=alpha(error, 0.12),
        info=accent,
        info_soft=alpha(accent, 0.12),
        input_bg=input_bg,
        hover=hover,
        pressed=pressed,
        disabled_bg=mix(surface, bg, 0.5),
        disabled_text=mix(text_muted, surface, 0.35),
        focus_ring=accent,
        overlay=alpha("#000000", 0.45 if is_dark else 0.25),
        chat_bg=chat_bg,
        bubble=bubble,
        bubble_text=text,
        bubble_meta=text_muted,
        link=mix(accent, "#ffffff", 0.18) if is_dark else accent,
        spoiler_bg=mix(surface, text, 0.28),
        spoiler_preview=mix(bubble, text, 0.32),
        code_bg=mix(bubble, text, 0.08),
        placeholder=text_muted,
        thumbnail_bg=mix(bg, "#000000", 0.25) if is_dark else mix(bg, text, 0.04),
        favorite=warning,
        selected_account=alpha(accent, 0.10),
        scrollbar_track="transparent",
        scrollbar_handle=mix(surface, text, 0.18),
        scrollbar_handle_hover=mix(surface, text, 0.28),
        scrollbar_handle_pressed=mix(surface, text, 0.38),
        spinbox_button="transparent",
        spinbox_button_hover=hover,
        spinbox_button_pressed=pressed,
        spinbox_arrow=text_secondary,
        is_dark=is_dark,
    )


_DARK = _make(
    is_dark=True,
    bg="#0f1115",
    surface="#16191f",
    elevated="#1c2028",
    border="#262b34",
    text="#e6e8ec",
    text_secondary="#9aa3af",
    # #6b7280 (the brief's value) is 3.9:1 on #0f1115 but only 3.6:1 on
    # the #16191f card surface where most helper text sits; nudged up so
    # both stay comfortably above the 3:1 de-emphasis floor.
    text_muted="#767e8b",
    accent="#5b8cff",
    # White on #5b8cff is 3.2:1 -- below AA for 13 px button text. Dark
    # text on the light-blue accent is 6.0:1 and stays quiet.
    on_accent="#0b0d12",
    success="#3fb950",
    warning="#d29922",
    error="#f85149",
    input_bg="#0f1115",
    chat_bg="#12151b",
    bubble="#1f2d4a",
)

_LIGHT = _make(
    is_dark=False,
    bg="#f6f7f9",
    surface="#ffffff",
    elevated="#ffffff",
    border="#e3e6eb",
    text="#14171c",
    text_secondary="#5b6472",
    # #8a93a0 is 3.0:1 on #f6f7f9 -- exactly at the floor; one step darker
    # so helper text isn't borderline.
    text_muted="#7a8391",
    # #3a6ff0 gives white text 4.46:1 -- a hair under AA; #3366e6 is 4.9:1.
    accent="#3366e6",
    on_accent="#ffffff",
    success="#1a7f37",
    warning="#9a6700",
    error="#cf222e",
    input_bg="#ffffff",
    chat_bg="#eef1f5",
    bubble="#ffffff",
)

_TOKENS: Dict[str, Tokens] = {THEME_DARK: _DARK, THEME_LIGHT: _LIGHT}


def normalize(theme: str) -> str:
    return theme if theme in VALID_THEMES else DEFAULT_THEME


def tokens_for(theme: str) -> Tokens:
    return _TOKENS[normalize(theme)]
