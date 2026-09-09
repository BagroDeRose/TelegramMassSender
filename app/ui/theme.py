"""Centralized design system: semantic color tokens, spacing/radius scale,
and the single QSS template both themes are generated from.

This is the one place raw hex colors are allowed to live. Every widget
that needs a color reads it from here (via a token, an accessor function,
or an objectName targeted by the generated stylesheet) -- never a literal
hex string scattered in widget code. Light and dark are two token sets
rendered through the *same* template, so they can never structurally
drift apart the way two hand-maintained .qss files could.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template
from typing import Dict

from PySide6.QtWidgets import QApplication

from app.config.paths import get_theme_assets_dir
from app.config.settings import DEFAULT_THEME
from app.ui import icons

THEME_LIGHT = "light"
THEME_DARK = "dark"
VALID_THEMES = (THEME_DARK, THEME_LIGHT)

THEME_LABELS: Dict[str, str] = {
    THEME_DARK: "Тёмная",
    THEME_LIGHT: "Светлая",
}

# ---- shared scale (identical in both themes) -------------------------------

FONT_FAMILY = "Segoe UI"

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 20
SPACE_XXL = 24
SPACE_XXXL = 32

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14

FONT_SIZE_PAGE_TITLE = 20
FONT_SIZE_CARD_TITLE = 14
FONT_SIZE_BODY = 13
FONT_SIZE_HELPER = 12
FONT_SIZE_CAPTION = 11
FONT_SIZE_STAT_VALUE = 26


@dataclass(frozen=True)
class Tokens:
    bg: str
    surface: str
    surface_elevated: str
    sidebar: str
    border: str
    border_subtle: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    on_accent: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    error: str
    error_soft: str
    input_bg: str
    hover: str
    pressed: str
    disabled_bg: str
    disabled_text: str
    focus_ring: str
    # Fine-grained tokens for hand-built rich text (message_editor/preview),
    # which QSS itself cannot reach (QTextCharFormat / inline HTML).
    link: str
    spoiler_bg: str
    spoiler_preview: str
    code_bg: str
    placeholder: str
    # Letterboxing behind image attachment thumbnails (app.ui.thumbnails).
    thumbnail_bg: str
    # Saved-report "favorite" star -- deliberately its own token rather than
    # reusing `warning`, since a favorite isn't a warning state.
    favorite: str
    # The active-account card's highlight (app.ui.account_widget) -- a
    # named token rather than an inline reuse of accent_soft, so the
    # "this is the selected/active account" meaning is explicit even
    # though the two currently share a value.
    selected_account: str
    # Custom scrollbar (QScrollBar is otherwise unstyled -> native OS
    # look). Track intentionally the literal "transparent" in both
    # themes -- it should blend with whatever surface it's drawn over,
    # which varies by context (page background vs. a card), so "match
    # the surface" means "don't paint one at all," not a fixed color.
    scrollbar_track: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    scrollbar_handle_pressed: str
    # QSpinBox up/down button box + the arrow glyph drawn onto a generated
    # PNG at stylesheet-build time (see stylesheet_for) -- see the QSS
    # spin-box section for why the arrow can't just be a QSS color.
    spinbox_button: str
    spinbox_button_hover: str
    spinbox_button_pressed: str
    spinbox_arrow: str


_DARK = Tokens(
    bg="#16171a",
    surface="#1e1f24",
    surface_elevated="#232429",
    sidebar="#1a1b1e",
    border="#2c2d33",
    border_subtle="#24252a",
    text_primary="#eef0f2",
    text_secondary="#b7bac0",
    text_muted="#7d818a",
    accent="#4ea1f7",
    accent_hover="#6bb3ff",
    accent_pressed="#3a86dd",
    accent_soft="rgba(78, 161, 247, 0.16)",
    on_accent="#ffffff",
    success="#3fb87f",
    success_soft="rgba(63, 184, 127, 0.15)",
    warning="#e0a94e",
    warning_soft="rgba(224, 169, 78, 0.15)",
    error="#ef5350",
    error_soft="rgba(239, 83, 80, 0.15)",
    input_bg="#202124",
    hover="#2a2c30",
    pressed="#232427",
    disabled_bg="#212226",
    disabled_text="#63656b",
    focus_ring="#4ea1f7",
    link="#4ea1f7",
    spoiler_bg="#4a4a4a",
    spoiler_preview="#54565c",
    code_bg="#2b2d31",
    placeholder="#7d7f85",
    thumbnail_bg="#0f1012",
    favorite="#f5c518",
    selected_account="rgba(78, 161, 247, 0.16)",
    scrollbar_track="transparent",
    scrollbar_handle="#3a3d45",
    scrollbar_handle_hover="#4a4e57",
    scrollbar_handle_pressed="#5a5f69",
    spinbox_button="transparent",
    spinbox_button_hover="#2a2c30",
    spinbox_button_pressed="#232427",
    spinbox_arrow="#eef0f2",
)

_LIGHT = Tokens(
    bg="#f4f5f7",
    surface="#ffffff",
    surface_elevated="#ffffff",
    sidebar="#eef0f3",
    border="#dfe1e6",
    border_subtle="#e8e9ec",
    text_primary="#16181c",
    text_secondary="#4b4e54",
    text_muted="#8a8d93",
    accent="#1a6fc4",
    accent_hover="#1660ad",
    accent_pressed="#144f8e",
    accent_soft="rgba(26, 111, 196, 0.10)",
    on_accent="#ffffff",
    success="#1e8a5f",
    success_soft="rgba(30, 138, 95, 0.12)",
    warning="#9a6400",
    warning_soft="rgba(154, 100, 0, 0.12)",
    error="#c0392b",
    error_soft="rgba(192, 57, 43, 0.10)",
    input_bg="#ffffff",
    hover="#eef0f3",
    pressed="#e2e4e8",
    disabled_bg="#f0f1f3",
    disabled_text="#a7a9ae",
    focus_ring="#1a6fc4",
    link="#1a6fc4",
    spoiler_bg="#c9c9c9",
    spoiler_preview="#b7b9be",
    code_bg="#e7e8ea",
    placeholder="#8a8d93",
    thumbnail_bg="#e8e9ec",
    favorite="#a9790a",
    selected_account="rgba(26, 111, 196, 0.10)",
    scrollbar_track="transparent",
    scrollbar_handle="#c7c9ce",
    scrollbar_handle_hover="#b3b6bc",
    scrollbar_handle_pressed="#9fa2a9",
    spinbox_button="transparent",
    spinbox_button_hover="#eef0f3",
    spinbox_button_pressed="#e2e4e8",
    spinbox_arrow="#16181c",
)

_TOKENS: Dict[str, Tokens] = {THEME_DARK: _DARK, THEME_LIGHT: _LIGHT}

_active_theme = DEFAULT_THEME


def _normalize(theme: str) -> str:
    return theme if theme in VALID_THEMES else DEFAULT_THEME


def tokens_for(theme: str) -> Tokens:
    return _TOKENS[_normalize(theme)]


def set_active_theme(theme: str) -> None:
    global _active_theme
    _active_theme = _normalize(theme)


def get_active_theme() -> str:
    return _active_theme


def current_tokens() -> Tokens:
    return _TOKENS[_active_theme]


# ---- rich-text color accessors (message_editor.py / message_preview.py) ---
# QSS cannot style QTextCharFormat or inline HTML, so these call sites read
# colors directly instead of relying on a stylesheet selector.


def link_color() -> str:
    return current_tokens().link


def spoiler_background() -> str:
    return current_tokens().spoiler_bg


def spoiler_preview_color() -> str:
    return current_tokens().spoiler_preview


def code_background() -> str:
    return current_tokens().code_bg


def placeholder_text_color() -> str:
    return current_tokens().placeholder


# ---- stylesheet generation --------------------------------------------------

_QSS_TEMPLATE = Template(
    """
* {
    color: $text_primary;
    font-family: "$font_family", sans-serif;
    font-size: ${font_body}px;
}

QMainWindow {
    background-color: $bg;
}

/* Deliberately NOT "QMainWindow, QWidget { background-color: $bg; }" --
   QWidget is the base class of QLabel and every plain layout-container
   QWidget() used throughout the app, so a blanket rule there paints an
   opaque $bg patch behind every label and content wrapper, including ones
   sitting on top of a QFrame#card's $surface -- exactly the "gray
   rectangle behind text" bug reported after the first redesign pass. An
   unstyled QWidget has no background fill by default and lets whatever
   its parent already painted show through, which is what we want: cards
   show $surface, everything unstyled on a card shows that same $surface
   through, not a mismatched $bg patch. */

/* QMenu (e.g. the message editor's emoji picker, a saved report's "..."
   overflow menu) is a top-level popup like QComboBox's dropdown and is
   equally unstyled by default -- same fix, same reason. */
QMenu {
    background-color: $surface_elevated;
    color: $text_primary;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 12px;
    border-radius: ${radius_sm}px;
}

QMenu::item:selected {
    background-color: $accent_soft;
    color: $accent;
}

QMenu::item:disabled {
    color: $disabled_text;
}

QMenu::separator {
    height: 1px;
    background: $border_subtle;
    margin: 4px 6px;
}

QToolTip {
    background-color: $surface_elevated;
    color: $text_primary;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 4px 8px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* ---- application shell: sidebar + status bar ---------------------------- */

QFrame#sidebar {
    background-color: $sidebar;
    border-right: 1px solid $border;
}

QLabel#sidebarBrandTitle {
    color: $text_primary;
    font-size: 15px;
    font-weight: 600;
}

QLabel#sidebarBrandSubtitle {
    color: $text_muted;
    font-size: ${font_caption}px;
}

QFrame#sidebarDivider {
    background-color: $border_subtle;
    border: none;
}

QToolButton#navButton {
    background-color: transparent;
    border: none;
    border-radius: ${radius_md}px;
    padding: 9px ${space_md}px;
    text-align: left;
    color: $text_secondary;
    font-size: ${font_body}px;
    font-weight: 500;
}

QToolButton#navButton:hover {
    background-color: $hover;
    color: $text_primary;
}

QToolButton#navButton:checked {
    background-color: $accent_soft;
    color: $accent;
    font-weight: 600;
}

QStatusBar {
    background-color: $sidebar;
    color: $text_muted;
    border-top: 1px solid $border;
}

QLabel#connectionStatusLabel {
    color: $text_secondary;
    font-size: ${font_caption}px;
    padding: 0 4px;
}

/* ---- page chrome --------------------------------------------------------- */

QLabel#pageTitle {
    color: $text_primary;
    font-size: ${font_page_title}px;
    font-weight: 700;
}

QLabel#pageSubtitle {
    color: $text_secondary;
    font-size: ${font_body}px;
}

QLabel#settingsSectionTitle {
    color: $text_muted;
    font-size: ${font_caption}px;
    font-weight: 700;
}

/* ---- cards ---------------------------------------------------------------- */

QFrame#card {
    background-color: $surface;
    border-radius: ${radius_md}px;
}

QLabel#cardTitle {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QLabel#cardCount {
    color: $accent;
    font-size: ${font_helper}px;
    font-weight: 600;
    background-color: $accent_soft;
    border-radius: ${radius_sm}px;
    padding: 2px 8px;
}

QLabel#helperText {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QLabel#emptyStateTitle {
    color: $text_secondary;
    font-size: ${font_body}px;
    font-weight: 600;
}

QLabel#emptyStateBody {
    color: $text_muted;
    font-size: ${font_helper}px;
}

/* ---- buttons --------------------------------------------------------------- */

QPushButton, QToolButton {
    background-color: $surface_elevated;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 7px 14px;
    color: $text_primary;
}

QPushButton:hover, QToolButton:hover {
    background-color: $hover;
    border-color: $border;
}

QPushButton:pressed, QToolButton:pressed {
    background-color: $pressed;
}

QPushButton:disabled, QToolButton:disabled {
    color: $disabled_text;
    background-color: $disabled_bg;
    border-color: $border_subtle;
}

QToolButton:checkable:checked {
    background-color: $accent_soft;
    border-color: $accent;
    color: $accent;
}

QPushButton#primaryButton {
    background-color: $accent;
    border-color: $accent;
    color: $on_accent;
    font-weight: 600;
    padding: 9px 18px;
}

QPushButton#primaryButton:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}

QPushButton#primaryButton:pressed {
    background-color: $accent_pressed;
    border-color: $accent_pressed;
}

QPushButton#primaryButton:disabled {
    background-color: $disabled_bg;
    border-color: $border_subtle;
    color: $disabled_text;
}

QPushButton#dangerButton {
    background-color: $surface_elevated;
    border-color: $error;
    color: $error;
}

QPushButton#dangerButton:hover {
    background-color: $error_soft;
}

QPushButton#dangerButton:disabled {
    color: $disabled_text;
    border-color: $border_subtle;
    background-color: $disabled_bg;
}

QPushButton#ghostButton {
    background-color: transparent;
    border: 1px solid transparent;
    color: $text_secondary;
}

QPushButton#ghostButton:hover {
    background-color: $hover;
    border-color: transparent;
    color: $text_primary;
}

QPushButton#ghostButton:pressed {
    background-color: $pressed;
}

QPushButton#ghostButton:disabled {
    color: $disabled_text;
    background-color: transparent;
}

QToolButton#chipRemoveButton {
    background-color: transparent;
    border: none;
    border-radius: ${radius_sm}px;
    padding: 2px;
    color: $text_muted;
    font-weight: 700;
}

QToolButton#chipRemoveButton:hover {
    background-color: $error_soft;
    color: $error;
}

QToolButton#toolbarButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: ${radius_sm}px;
    padding: 5px 9px;
    color: $text_secondary;
}

QToolButton#toolbarButton:hover {
    background-color: $hover;
    color: $text_primary;
}

QToolButton#toolbarButton:checked {
    background-color: $accent_soft;
    border-color: $accent;
    color: $accent;
}

/* ---- inputs ------------------------------------------------------------ */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QListWidget, QTextBrowser {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 6px 8px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: $focus_ring;
}

QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    color: $disabled_text;
    background-color: $disabled_bg;
    border-color: $border_subtle;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

/* QComboBox's closed box already inherits the input rule above, but its
   dropdown is a *separate* top-level popup (internally a QAbstractItemView)
   that Qt does NOT theme via the QComboBox selector -- left unstyled, it
   falls back to the native OS palette (light) regardless of the app's
   active theme, so in Dark mode the popup rendered as a white box with
   barely-readable text. This is the fix: style the popup explicitly. */
QComboBox QAbstractItemView {
    background-color: $surface_elevated;
    color: $text_primary;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 4px;
    outline: none;
    selection-background-color: $accent_soft;
    selection-color: $accent;
}

QComboBox QAbstractItemView::item {
    padding: 6px 8px;
    border-radius: ${radius_sm}px;
    min-height: 20px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: $hover;
}

QComboBox QAbstractItemView::item:selected {
    background-color: $accent_soft;
    color: $accent;
}

/* ---- checkboxes ------------------------------------------------------------ */

QCheckBox {
    spacing: ${space_sm}px;
    color: $text_secondary;
    background: transparent;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $border;
    border-radius: 4px;
    background-color: $input_bg;
}

QCheckBox::indicator:hover {
    border-color: $accent;
}

QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
}

QCheckBox::indicator:checked:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}

QCheckBox::indicator:disabled {
    background-color: $disabled_bg;
    border-color: $border_subtle;
}

QCheckBox:disabled {
    color: $disabled_text;
}

/* ---- spin boxes -------------------------------------------------------------- */
/* Once ::up-button/::down-button carry ANY QSS (background/border below),
   Qt stops painting its native arrow glyph inside them -- confirmed by
   direct rendering, not assumed -- so the arrows MUST come from an
   explicit `image:`. app.ui.theme regenerates two small PNGs (one per
   direction) matching $spinbox_arrow every time a stylesheet is built and
   substitutes their file:// paths in here as $spinbox_up_arrow_url /
   $spinbox_down_arrow_url. */

QSpinBox {
    padding-right: 20px;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: $spinbox_button;
    border: none;
    border-left: 1px solid $border;
    width: 18px;
}

QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: ${radius_sm}px;
}

QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: ${radius_sm}px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: $spinbox_button_hover;
}

QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
    background-color: $spinbox_button_pressed;
}

QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {
    background-color: $disabled_bg;
}

QSpinBox::up-arrow {
    image: url($spinbox_up_arrow_url);
    width: 8px;
    height: 8px;
}

QSpinBox::down-arrow {
    image: url($spinbox_down_arrow_url);
    width: 8px;
    height: 8px;
}

QListWidget {
    padding: ${space_xs}px;
}

QListWidget::item {
    padding: 4px 3px;
    border-radius: ${radius_sm}px;
}

QListWidget::item:selected {
    background-color: $accent;
    color: $on_accent;
}

/* ---- attachment chips ---------------------------------------------------- */

QFrame#attachmentChip {
    background-color: $surface_elevated;
    border: 1px solid $border_subtle;
    border-radius: ${radius_sm}px;
}

QLabel#attachmentChipName {
    color: $text_primary;
    font-size: ${font_helper}px;
}

/* ---- progress / status ---------------------------------------------------- */

QProgressBar {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    text-align: center;
    min-height: 18px;
    color: $text_secondary;
}

QProgressBar::chunk {
    background-color: $accent;
    border-radius: ${radius_sm}px;
}

QLabel {
    color: $text_secondary;
}

QLabel#summaryLabel {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QLabel#statusLabel {
    color: $warning;
    font-weight: 600;
}

QLabel#charCountLabel {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QLabel#attachmentsPreviewLabel {
    color: $text_muted;
    font-size: ${font_helper}px;
}

/* ---- stat cards (Results page) -------------------------------------------- */

QFrame#statCard {
    background-color: $surface;
    border-radius: ${radius_md}px;
}

QLabel#statValue {
    color: $text_primary;
    font-size: ${font_stat_value}px;
    font-weight: 700;
}

QLabel#statValue[variant="success"] {
    color: $success;
}

QLabel#statValue[variant="error"] {
    color: $error;
}

QLabel#statValue[variant="warning"] {
    color: $warning;
}

QLabel#statLabel {
    color: $text_muted;
    font-size: ${font_caption}px;
    font-weight: 600;
}

/* ---- account cards ------------------------------------------------------- */

QFrame#accountCard {
    background-color: $surface;
    border: 1px solid transparent;
    border-radius: ${radius_md}px;
}

QFrame#accountCard[active="true"] {
    border: 1px solid $accent;
    background-color: $selected_account;
}

QLabel#accountName {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QLabel#accountMeta {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QPushButton#accountUseButton {
    background-color: transparent;
    border: 1px solid $border;
}

QPushButton#accountUseButton[active="true"] {
    background-color: $accent;
    border-color: $accent;
    color: $on_accent;
    font-weight: 600;
}

/* ---- journal panel -------------------------------------------------------- */

QFrame#journalPanel {
    background-color: $sidebar;
    border-right: 1px solid $border;
}

QLabel#journalTitle {
    color: $text_primary;
    font-size: ${font_helper}px;
    font-weight: 600;
}

QToolButton#journalToggleButton {
    background-color: transparent;
    border: none;
    padding: 4px;
    color: $text_muted;
}

QToolButton#journalToggleButton:hover {
    background-color: $hover;
    color: $text_primary;
}

QListWidget#journalList {
    background-color: transparent;
    border: none;
}

QListWidget#journalList::item {
    padding: 5px 4px;
}

/* ---- attachment thumbnails -------------------------------------------------- */

QFrame#thumbnailTile {
    background-color: $thumbnail_bg;
    border-radius: ${radius_sm}px;
}

QLabel#thumbnailImage {
    background-color: $thumbnail_bg;
    border-radius: ${radius_sm}px;
}

QLabel#thumbnailName {
    color: $text_secondary;
    font-size: ${font_caption}px;
}

QLabel#thumbnailMeta {
    color: $text_muted;
    font-size: ${font_caption}px;
}

/* ---- saved report cards ----------------------------------------------------- */

QFrame#reportCard {
    background-color: $surface;
    border-radius: ${radius_md}px;
}

QFrame#reportCard:hover {
    background-color: $hover;
}

QLabel#reportName {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QLabel#reportMeta {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QToolButton#favoriteButton {
    background-color: transparent;
    border: none;
    padding: 2px;
    color: $text_muted;
    font-size: 15px;
}

QToolButton#favoriteButton:hover {
    background-color: $hover;
}

QToolButton#favoriteButton[active="true"] {
    color: $favorite;
}

/* ---- scrollbars ------------------------------------------------------------- */

QScrollBar:vertical {
    background: $scrollbar_track;
    width: 10px;
    margin: 2px 1px 2px 1px;
    border: none;
}

QScrollBar::handle:vertical {
    background: $scrollbar_handle;
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background: $scrollbar_handle_hover;
}

QScrollBar::handle:vertical:pressed {
    background: $scrollbar_handle_pressed;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    width: 0px;
    background: none;
    border: none;
}

QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
    width: 0px;
    height: 0px;
    background: none;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: $scrollbar_track;
    height: 10px;
    margin: 1px 2px 1px 2px;
    border: none;
}

QScrollBar::handle:horizontal {
    background: $scrollbar_handle;
    border-radius: 4px;
    min-width: 28px;
}

QScrollBar::handle:horizontal:hover {
    background: $scrollbar_handle_hover;
}

QScrollBar::handle:horizontal:pressed {
    background: $scrollbar_handle_pressed;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height: 0px;
    width: 0px;
    background: none;
    border: none;
}

QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {
    width: 0px;
    height: 0px;
    background: none;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* ---- dialogs -------------------------------------------------------------- */

QDialog {
    background-color: $bg;
}

QMessageBox QLabel {
    color: $text_primary;
}

QLabel#dialogErrorLabel {
    color: $error;
}
"""
)


_generated_arrow_cache: set = set()


def _spinbox_arrow_urls(theme_name: str, spinbox_arrow_color: str) -> Dict[str, str]:
    """Generate (or refresh) the up/down arrow PNGs QSS references via
    `image: url(...)` and return their paths in QSS-safe form (forward
    slashes, Windows absolute paths included -- Qt's url() accepts these).

    stylesheet_for() is a plain function historically safe to call without
    any GUI object existing yet (several existing tests do, and construct
    no QApplication), but QPixmap/QPainter are only well-defined once a
    QApplication exists -- constructing one before that is a documented Qt
    precondition violation that crashes the process outright, not a
    catchable Python exception. So drawing is skipped entirely (leaving
    whichever file was last written, or none) whenever no QApplication is
    currently running; the path is still substituted either way so the
    QSS template's placeholders are always satisfied. In the real app this
    is always called with a QApplication already up (theme.py is only
    ever applied from app.ui.main_window, itself a QWidget)."""
    directory = get_theme_assets_dir()
    urls = {}
    has_gui = QApplication.instance() is not None
    for direction in ("up", "down"):
        path = directory / f"spin_{direction}_{theme_name}.png"
        cache_key = (direction, theme_name, spinbox_arrow_color)
        # stylesheet_for() runs on every theme (re)application, which in
        # practice means every MainWindow construction -- once this
        # process has already written the correct (color-matching) file,
        # redo it only if the color actually changed, not on every call.
        if has_gui and (cache_key not in _generated_arrow_cache or not path.is_file()):
            try:
                icons.save_spinbox_arrow(direction, spinbox_arrow_color, path)
                _generated_arrow_cache.add(cache_key)
            except OSError:
                # Disposable cache data -- if it can't be written (read-only
                # install dir, disk full), the spin buttons just go back to
                # being blank rather than crashing the whole stylesheet.
                pass
        urls[f"spinbox_{direction}_arrow_url"] = str(path).replace("\\", "/")
    return urls


def stylesheet_for(theme: str) -> str:
    t = tokens_for(theme)
    values = {
        **asdict(t),
        "font_family": FONT_FAMILY,
        "font_page_title": FONT_SIZE_PAGE_TITLE,
        "font_card_title": FONT_SIZE_CARD_TITLE,
        "font_body": FONT_SIZE_BODY,
        "font_helper": FONT_SIZE_HELPER,
        "font_caption": FONT_SIZE_CAPTION,
        "font_stat_value": FONT_SIZE_STAT_VALUE,
        "space_xs": SPACE_XS,
        "space_sm": SPACE_SM,
        "space_md": SPACE_MD,
        "space_lg": SPACE_LG,
        "space_xl": SPACE_XL,
        "radius_sm": RADIUS_SM,
        "radius_md": RADIUS_MD,
        "radius_lg": RADIUS_LG,
        **_spinbox_arrow_urls(_normalize(theme), t.spinbox_arrow),
    }
    return _QSS_TEMPLATE.substitute(**{k: str(v) for k, v in values.items()})
