"""Theme system: tokens, the generated stylesheet, the QPalette, fonts,
the Windows title bar, and the single place a theme is applied.

Structure (one system, two value sets):
    tokens.py  -- every raw colour / size / font name (dark + light)
    qss.py     -- the one QSS template both themes render through
    __init__   -- this module: active-theme state, rendering, apply_theme()

The stored choice is unchanged from before the redesign: settings key
"theme" with values "dark" / "light" (app.config.settings). A user's old
"light" opens the new light theme with no migration.

apply_theme() is the only function that touches the QApplication: it sets
the palette (which native widgets -- message boxes, context menus, tooltips,
text selection -- draw from), loads the bundled Inter font once, calls
setStyleSheet exactly once, re-themes every open window's title bar, and
emits notifier.theme_changed for the few widgets that paint colours QSS
can't reach (rich-text previews, custom delegates). Never call
QApplication.setStyleSheet anywhere else, and never per widget.
"""
from __future__ import annotations

import ctypes
import sys
import warnings
from dataclasses import asdict
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QProxyStyle, QStyle, QWidget

from app.config.paths import get_resource_path, get_theme_assets_dir
from app.config.settings import DEFAULT_THEME
from app.i18n import tr
from app.ui import icons
from app.ui.theme.qss import QSS_TEMPLATE
from app.ui.theme.tokens import (  # noqa: F401 - re-exported public API
    ACCOUNT_CARD_MAX_WIDTH,
    CONTENT_MAX_WIDTH,
    AVATAR_SIZE,
    AVATAR_SIZE_LG,
    CONTROL_HEIGHT,
    CONTROL_WIDTH,
    FOCUS_RING,
    FONT_FAMILY,
    FONT_FAMILY_FALLBACK,
    FONT_FAMILY_MONO,
    FONT_FAMILY_MONO_FALLBACK,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_CARD_TITLE,
    FONT_SIZE_HELPER,
    FONT_SIZE_PAGE_TITLE,
    FONT_SIZE_STAT_VALUE,
    FONT_WEIGHT_MEDIUM,
    FONT_WEIGHT_REGULAR,
    FONT_WEIGHT_SEMIBOLD,
    ICON_SIZE,
    ICON_SIZE_EMPTY,
    ICON_SIZE_NAV,
    ICON_SIZE_SM,
    JOURNAL_WIDTH,
    LAUNCH_PANEL_WIDTH,
    MOTION_FAST_MS,
    PREVIEW_ALBUM_GAP,
    PREVIEW_BUBBLE_MAX_WIDTH,
    PREVIEW_BUBBLE_PADDING,
    PREVIEW_MIN_HEIGHT,
    PREVIEW_TAIL,
    MOTION_MS,
    MOTION_SLOW_MS,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    SIDEBAR_ACTIVE_BAR,
    SIDEBAR_COLLAPSED_WIDTH,
    SIDEBAR_LOGO,
    SIDEBAR_WIDTH,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    SPACE_XXXL,
    STATUS_DOT,
    THEME_DARK,
    THEME_LIGHT,
    TOAST_DURATION_MS,
    TOAST_WIDTH,
    TWO_COLUMN_MIN_WIDTH,
    CAMPAIGN_FOLD_WIDTH,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    COMBO_MIN_WIDTH,
    BORDER_WIDTH,
    SEGMENT_PADDING,
    PILL_TINT_ALPHA,
    HEADER_GAP,
    RESULTS_ROW_HEIGHT,
    RESULTS_COL_CHECK,
    RESULTS_COL_STATUS,
    RESULTS_COL_TYPE,
    RESULTS_COL_ID,
    RESULTS_COL_FLEX_MIN,
    RESULTS_FIXED_MIN_SCALE,
    RESULTS_LIST_MIN_HEIGHT,
    STAT_CARD_MIN_HEIGHT,
    ATTACHMENT_TILE,
    ATTACHMENT_THUMBNAIL,
    ATTACHMENT_THUMBNAIL_INSET,
    ATTACHMENT_TILE_PADDING,
    ATTACHMENT_REMOVE_ICON,
    ATTACHMENT_FILE_ICON,
    SETTINGS_LABEL_WIDTH,
    DIAGNOSTICS_MAX_HEIGHT,
    DIALOG_WIDTH,
    DIALOG_HEIGHT_SM,
    DIALOG_HEIGHT,
    DIALOG_PICKER_CHECK_COL,
    DIALOG_PICKER_DATE_WIDTH,
    DIALOG_PICKER_HEIGHT,
    DIALOG_PICKER_ROW_HEIGHT,
    DIALOG_PICKER_WIDTH,
    EDITOR_DIALOG_WIDTH,
    EDITOR_DIALOG_HEIGHT,
    WIZARD_WIDTH,
    WIZARD_HEIGHT,
    EDITOR_COMPACT_HEIGHT,
    PREVIEW_NAME_WIDTH,
    VALID_THEMES,
    Tokens,
    alpha,
    mix,
    normalize as _normalize,
    tokens_for,
)

_THEME_LABEL_KEYS: Dict[str, str] = {
    THEME_DARK: "theme.label.dark",
    THEME_LIGHT: "theme.label.light",
}


class _ThemeLabels:
    """Looked up fresh on every access so a language switch is reflected."""

    def __getitem__(self, theme_name: str) -> str:
        return tr(_THEME_LABEL_KEYS[theme_name])


THEME_LABELS = _ThemeLabels()

_active_theme = DEFAULT_THEME


def set_active_theme(theme: str) -> None:
    global _active_theme
    _active_theme = _normalize(theme)


def get_active_theme() -> str:
    return _active_theme


def current_tokens() -> Tokens:
    return tokens_for(_active_theme)


# ---- rich-text colour accessors (QSS can't style QTextCharFormat/HTML) --------


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


# ---- fonts ------------------------------------------------------------------------

_fonts_loaded: Optional[bool] = None
_INTER_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf")


def load_fonts() -> bool:
    """Register the bundled Inter (OFL) faces once. Returns whether Inter
    is available; if not, the QSS family list falls back to Segoe UI."""
    global _fonts_loaded
    if _fonts_loaded is not None:
        return _fonts_loaded
    if QGuiApplication.instance() is None:
        return False
    loaded = False
    for file_name in _INTER_FILES:
        path = get_resource_path("assets", "fonts", "inter", file_name)
        if path.is_file() and QFontDatabase.addApplicationFont(str(path)) != -1:
            loaded = True
    _fonts_loaded = loaded
    return loaded


def ui_font(size_px: int = FONT_SIZE_BODY, weight: int = FONT_WEIGHT_REGULAR) -> QFont:
    """A QFont for code that paints text itself (delegates)."""
    font = QFont()
    font.setFamilies([FONT_FAMILY, FONT_FAMILY_FALLBACK])
    font.setPixelSize(size_px)
    font.setWeight(QFont.Weight(weight))
    return font


def mono_font(size_px: int = FONT_SIZE_HELPER) -> QFont:
    font = QFont()
    font.setFamilies([FONT_FAMILY_MONO, FONT_FAMILY_MONO_FALLBACK])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(size_px)
    return font


# ---- palette ------------------------------------------------------------------------


def palette_for(theme: str) -> QPalette:
    """The QPalette matching the tokens. Native widgets the QSS doesn't
    reach (message-box text, context menus of text fields, tooltips' text,
    selection highlight, placeholder text) take their colours from here."""
    t = tokens_for(theme)
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text_primary,
        QPalette.ColorRole.Base: t.input_bg,
        QPalette.ColorRole.AlternateBase: t.surface,
        QPalette.ColorRole.ToolTipBase: t.surface_elevated,
        QPalette.ColorRole.ToolTipText: t.text_primary,
        QPalette.ColorRole.PlaceholderText: t.placeholder,
        QPalette.ColorRole.Text: t.text_primary,
        QPalette.ColorRole.Button: t.surface_elevated,
        QPalette.ColorRole.ButtonText: t.text_primary,
        QPalette.ColorRole.BrightText: t.error,
        QPalette.ColorRole.Light: t.surface_elevated,
        QPalette.ColorRole.Midlight: t.border_subtle,
        QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Dark: t.bg,
        QPalette.ColorRole.Shadow: t.bg,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.on_accent,
        QPalette.ColorRole.Link: t.link,
        QPalette.ColorRole.LinkVisited: t.link,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.disabled_text))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(t.disabled_bg))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(t.disabled_bg))
    return palette


# ---- stylesheet ----------------------------------------------------------------------

_generated_assets: set = set()
# QSS sub-controls that only accept an image: file name -> (lucide icon, token, size)
_QSS_IMAGES = {
    "spinbox_up_arrow_url": ("spin_up", "chevron_up", "spinbox_arrow", 10),
    "spinbox_down_arrow_url": ("spin_down", "chevron_down", "spinbox_arrow", 10),
    "chevron_down_url": ("chevron_down", "chevron_down", "text_secondary", 12),
    "check_url": ("check", "check", "on_accent", 14),
}


def _qss_image_urls(theme_name: str, t: Tokens) -> Dict[str, str]:
    """Generate (when a QApplication exists) and return the PNGs the QSS
    references. Without a QApplication drawing is skipped -- QPixmap before
    QApplication crashes the process -- but the paths are still returned so
    the template always renders."""
    directory = get_theme_assets_dir()
    has_gui = QApplication.instance() is not None
    urls = {}
    for key, (stem, icon_name, role, size) in _QSS_IMAGES.items():
        color = getattr(t, role)
        path = directory / f"{stem}_{theme_name}.png"
        cache_key = (stem, theme_name, color, size)
        if has_gui and (cache_key not in _generated_assets or not path.is_file()):
            try:
                icons.save_tinted_png(icon_name, color, path, size)
                _generated_assets.add(cache_key)
            except OSError:
                pass  # disposable cache; the control just loses its glyph
        urls[key] = str(path).replace("\\", "/")
    return urls


def stylesheet_for(theme: str) -> str:
    name = _normalize(theme)
    t = tokens_for(name)
    values = {
        **asdict(t),
        "font_family": FONT_FAMILY,
        "font_family_fallback": FONT_FAMILY_FALLBACK,
        "font_family_mono": FONT_FAMILY_MONO,
        "font_family_mono_fallback": FONT_FAMILY_MONO_FALLBACK,
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
        "focus_ring": FOCUS_RING,
        "sidebar_active_bar": SIDEBAR_ACTIVE_BAR,
        "status_dot": STATUS_DOT,
        "status_dot_radius": STATUS_DOT // 2,
        "avatar": AVATAR_SIZE,
        "avatar_radius": AVATAR_SIZE // 2,
        "avatar_lg": AVATAR_SIZE_LG,
        "avatar_lg_radius": AVATAR_SIZE_LG // 2,
        # Inner height: the control height minus the 2 x 6 px vertical padding
        # and the 1 px borders.
        "control_inner_height": CONTROL_HEIGHT - 2 * 6 - 2,
        **_qss_image_urls(name, t),
    }
    return QSS_TEMPLATE.substitute(**{k: str(v) for k, v in values.items()})


# ---- runtime: property helpers, notifier, filters, apply -------------------------------


def icon_qsize(size: int = ICON_SIZE) -> QSize:
    return QSize(size, size)


def repolish(widget: QWidget) -> None:
    """Re-evaluate QSS for one widget after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    # QWidget.update explicitly: item views overload update(index).
    QWidget.update(widget)


def set_property(widget: QWidget, name: str, value) -> None:
    """Set a styling property (variant/status/active/...) and re-polish just
    this widget -- the only supported way to change a variant at runtime."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    repolish(widget)


def set_variant(widget: QWidget, variant: str) -> None:
    set_property(widget, "variant", variant)


def set_status(widget: QWidget, status: Optional[str]) -> None:
    set_property(widget, "status", status or "")


class ThemeNotifier(QObject):
    """Emits after a theme was applied, for colours QSS can't reach."""

    theme_changed = Signal(str)


notifier = ThemeNotifier()


def on_theme_changed(receiver: QObject, callback) -> None:
    """Connect `callback` to theme changes for as long as `receiver` lives:
    the connection is dropped when the receiver is destroyed, so a theme
    switch never calls into a deleted widget."""
    notifier.theme_changed.connect(callback)

    def _disconnect(*_args, cb=callback) -> None:
        # During application teardown Qt may already have dropped the
        # connection; PySide reports that as a RuntimeWarning, not an error.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                notifier.theme_changed.disconnect(cb)
            except (RuntimeError, TypeError):
                pass

    receiver.destroyed.connect(_disconnect)


_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED


def set_dark_title_bar(window: QWidget, dark: bool) -> bool:
    """Ask Windows (10 1809+ / 11) to draw the window's title bar dark or
    light via DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE). Any
    failure -- other OS, offscreen platform, older Windows, API error -- is
    a silent no-op returning False."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return False
    try:
        hwnd = ctypes.c_void_p(int(window.winId()))
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        for attribute in (_DWMWA_USE_IMMERSIVE_DARK_MODE, _DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, ctypes.c_uint(attribute), ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FLAGS)
                return True
    except Exception:  # noqa: BLE001 - purely cosmetic; never fail over a title bar
        return False
    return False


_KEYBOARD_REASONS = (
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
)


class _AppEventFilter(QObject):
    """Application-wide: (1) keyboard-only focus ring -- QSS has no
    :focus-visible, so a FocusIn from Tab/Backtab/shortcut sets the
    `focusRing` property the QSS draws the 2 px accent ring from, and any
    other focus change clears it; (2) dark/light title bar for every
    top-level window as it is shown."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        try:
            self._handle(obj, event)
        except Exception:  # noqa: BLE001 - cosmetic; must never break event delivery
            pass
        return False

    def _handle(self, obj, event) -> None:
        event_type = event.type()
        if event_type == QEvent.Type.FocusIn and isinstance(obj, QWidget):
            set_property(obj, "focusRing", event.reason() in _KEYBOARD_REASONS)
        elif event_type == QEvent.Type.FocusOut and isinstance(obj, QWidget):
            if obj.property("focusRing"):
                set_property(obj, "focusRing", False)
        elif event_type == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            set_dark_title_bar(obj, current_tokens().is_dark)


_app_filter: Optional[_AppEventFilter] = None

_STANDARD_ICONS = {
    QStyle.StandardPixmap.SP_MessageBoxInformation: ("info", "accent"),
    QStyle.StandardPixmap.SP_MessageBoxQuestion: ("info", "accent"),
    QStyle.StandardPixmap.SP_MessageBoxWarning: ("warning", "warning"),
    QStyle.StandardPixmap.SP_MessageBoxCritical: ("error_circle", "error"),
}


class _ThemedStyle(QProxyStyle):
    """The platform style, except (1) message-box icons: themed Lucide line
    icons instead of the native ones (drawn for a light background), for
    every QMessageBox including static QMessageBox.warning() calls; and
    (2) dialog button order: primary action on the right."""

    def standardIcon(self, standard_icon, option=None, widget=None):  # noqa: N802 - Qt override
        mapped = _STANDARD_ICONS.get(standard_icon)
        if mapped is not None:
            return icons.themed(mapped[0], mapped[1], active_role=None)
        return super().standardIcon(standard_icon, option, widget)

    def styleHint(self, hint, option=None, widget=None, return_data=None):  # noqa: N802 - Qt override
        # Every dialog in the app puts its primary action last (rightmost);
        # make message boxes / button boxes agree instead of Windows' order.
        if hint == QStyle.StyleHint.SH_DialogButtonLayout:
            return QDialogButtonBox.ButtonLayout.GnomeLayout.value
        return super().styleHint(hint, option, widget, return_data)


_themed_style: Optional[_ThemedStyle] = None


def _install_app_filter(app: QApplication) -> None:
    global _app_filter, _themed_style
    if _themed_style is None:
        _themed_style = _ThemedStyle(app.style().name())
        app.setStyle(_themed_style)
    if _app_filter is None:
        _app_filter = _AppEventFilter(app)
        app.installEventFilter(_app_filter)


def apply_theme(app: Optional[QApplication], theme: str) -> None:
    """The one place a theme is applied. Safe to call again with the same
    theme (it re-applies; callers avoid that when nothing changed)."""
    set_active_theme(theme)
    if app is None:
        return
    name = get_active_theme()
    load_fonts()
    _install_app_filter(app)
    app.setPalette(palette_for(name))
    app.setStyleSheet(stylesheet_for(name))
    dark = tokens_for(name).is_dark
    for window in app.topLevelWidgets():
        if window.isVisible():
            set_dark_title_bar(window, dark)
    notifier.theme_changed.emit(name)


def top_level_windows() -> List[QWidget]:
    app = QApplication.instance()
    return [w for w in app.topLevelWidgets() if w.isVisible()] if app is not None else []


# Everything callers import from app.ui.theme (tokens re-exported here).
__all__ = [
    "ACCOUNT_CARD_MAX_WIDTH",
    "ATTACHMENT_FILE_ICON",
    "ATTACHMENT_REMOVE_ICON",
    "ATTACHMENT_THUMBNAIL",
    "ATTACHMENT_THUMBNAIL_INSET",
    "ATTACHMENT_TILE",
    "ATTACHMENT_TILE_PADDING",
    "AVATAR_SIZE",
    "AVATAR_SIZE_LG",
    "BORDER_WIDTH",
    "CAMPAIGN_FOLD_WIDTH",
    "COMBO_MIN_WIDTH",
    "CONTENT_MAX_WIDTH",
    "CONTROL_HEIGHT",
    "CONTROL_WIDTH",
    "DIAGNOSTICS_MAX_HEIGHT",
    "DIALOG_HEIGHT",
    "DIALOG_PICKER_CHECK_COL",
    "DIALOG_PICKER_DATE_WIDTH",
    "DIALOG_PICKER_HEIGHT",
    "DIALOG_PICKER_ROW_HEIGHT",
    "DIALOG_PICKER_WIDTH",
    "DIALOG_HEIGHT_SM",
    "DIALOG_WIDTH",
    "EDITOR_COMPACT_HEIGHT",
    "EDITOR_DIALOG_HEIGHT",
    "EDITOR_DIALOG_WIDTH",
    "FOCUS_RING",
    "FONT_FAMILY",
    "FONT_FAMILY_FALLBACK",
    "FONT_FAMILY_MONO",
    "FONT_FAMILY_MONO_FALLBACK",
    "FONT_SIZE_BODY",
    "FONT_SIZE_CAPTION",
    "FONT_SIZE_CARD_TITLE",
    "FONT_SIZE_HELPER",
    "FONT_SIZE_PAGE_TITLE",
    "FONT_SIZE_STAT_VALUE",
    "FONT_WEIGHT_MEDIUM",
    "FONT_WEIGHT_REGULAR",
    "FONT_WEIGHT_SEMIBOLD",
    "HEADER_GAP",
    "ICON_SIZE",
    "ICON_SIZE_EMPTY",
    "ICON_SIZE_NAV",
    "ICON_SIZE_SM",
    "JOURNAL_WIDTH",
    "LAUNCH_PANEL_WIDTH",
    "MOTION_FAST_MS",
    "MOTION_MS",
    "MOTION_SLOW_MS",
    "PILL_TINT_ALPHA",
    "PREVIEW_ALBUM_GAP",
    "PREVIEW_BUBBLE_MAX_WIDTH",
    "PREVIEW_BUBBLE_PADDING",
    "PREVIEW_MIN_HEIGHT",
    "PREVIEW_NAME_WIDTH",
    "PREVIEW_TAIL",
    "RADIUS_LG",
    "RADIUS_MD",
    "RADIUS_PILL",
    "RADIUS_SM",
    "RESULTS_COL_CHECK",
    "RESULTS_COL_FLEX_MIN",
    "RESULTS_COL_ID",
    "RESULTS_COL_STATUS",
    "RESULTS_COL_TYPE",
    "RESULTS_FIXED_MIN_SCALE",
    "RESULTS_LIST_MIN_HEIGHT",
    "RESULTS_ROW_HEIGHT",
    "SEGMENT_PADDING",
    "SETTINGS_LABEL_WIDTH",
    "SIDEBAR_ACTIVE_BAR",
    "SIDEBAR_COLLAPSED_WIDTH",
    "SIDEBAR_LOGO",
    "SIDEBAR_WIDTH",
    "SPACE_LG",
    "SPACE_MD",
    "SPACE_SM",
    "SPACE_XL",
    "SPACE_XS",
    "SPACE_XXL",
    "SPACE_XXXL",
    "STATUS_DOT",
    "STAT_CARD_MIN_HEIGHT",
    "THEME_DARK",
    "THEME_LABELS",
    "THEME_LIGHT",
    "TOAST_DURATION_MS",
    "TOAST_WIDTH",
    "TWO_COLUMN_MIN_WIDTH",
    "ThemeNotifier",
    "Tokens",
    "VALID_THEMES",
    "WINDOW_DEFAULT_HEIGHT",
    "WINDOW_DEFAULT_WIDTH",
    "WINDOW_MIN_HEIGHT",
    "WINDOW_MIN_WIDTH",
    "WIZARD_HEIGHT",
    "WIZARD_WIDTH",
    "alpha",
    "apply_theme",
    "code_background",
    "current_tokens",
    "get_active_theme",
    "icon_qsize",
    "link_color",
    "load_fonts",
    "mix",
    "mono_font",
    "notifier",
    "on_theme_changed",
    "palette_for",
    "placeholder_text_color",
    "repolish",
    "set_active_theme",
    "set_dark_title_bar",
    "set_property",
    "set_status",
    "set_variant",
    "spoiler_background",
    "spoiler_preview_color",
    "stylesheet_for",
    "tokens_for",
    "top_level_windows",
    "ui_font",
]
