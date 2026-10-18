"""The one QSS template, rendered from the tokens of the active theme and
applied once on the QApplication (see app.ui.theme.apply_theme).

Variants are selected with dynamic properties, never with per-widget
setStyleSheet:
    variant = primary | secondary | ghost | danger   (buttons)
    status  = success | warning | error | info       (labels, pills, dots)
Changing one at runtime goes through app.ui.theme.set_property(), which
re-polishes just that widget.

Legacy objectNames (#primaryButton, #ghostButton, #dangerButton) are kept
as aliases in the same rules as the variant properties: older call sites
and tests still use them, and an alias in the same selector list can't
drift into a second set of colours.
"""
from __future__ import annotations

from string import Template

QSS_TEMPLATE = Template(
    """
/* ==== base ================================================================ */

* {
    color: $text_primary;
    font-family: "$font_family", "$font_family_fallback", sans-serif;
    font-size: ${font_body}px;
    outline: none;
}

QMainWindow, QDialog, QWidget#page, QStackedWidget#pageStack {
    background-color: $bg;
}

QDialog {
    background-color: $surface;
}

QLabel {
    color: $text_secondary;
    background: transparent;
}

QToolTip {
    background-color: $surface_elevated;
    color: $text_primary;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: ${space_xs}px ${space_sm}px;
}

QMenu {
    background-color: $surface_elevated;
    color: $text_primary;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: ${space_xs}px;
}

QMenu::item {
    padding: 6px ${space_md}px;
    border-radius: ${radius_sm}px;
    background: transparent;
}

QMenu::item:selected {
    background-color: $hover;
    color: $text_primary;
}

QMenu::item:disabled {
    color: $disabled_text;
}

QMenu::separator {
    height: 1px;
    background: $border_subtle;
    margin: ${space_xs}px 6px;
}

QMenu::icon {
    padding-left: ${space_sm}px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* ==== shell =============================================================== */

QFrame#sidebar {
    background-color: $sidebar;
    border: none;
    border-right: 1px solid $border;
}

QLabel#sidebarBrandTitle {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QFrame#sidebarDivider {
    background-color: $border_subtle;
    border: none;
    max-height: 1px;
}

QToolButton#navButton {
    background-color: transparent;
    border: none;
    border-left: ${sidebar_active_bar}px solid transparent;
    border-radius: 0px;
    padding: ${space_sm}px ${space_md}px;
    text-align: left;
    color: $text_secondary;
    font-weight: 500;
}

QToolButton#navButton:hover {
    background-color: $hover;
    color: $text_primary;
}

QToolButton#navButton:checked {
    background-color: $accent_soft;
    border-left: ${sidebar_active_bar}px solid $accent;
    color: $text_primary;
    font-weight: 600;
}

QToolButton#sidebarToggle {
    background: transparent;
    border: none;
    padding: ${space_xs}px;
    border-radius: ${radius_sm}px;
}

QToolButton#sidebarToggle:hover {
    background-color: $hover;
}

QFrame#sidebarAccount {
    background: transparent;
    border: none;
    border-top: 1px solid $border_subtle;
}

QToolButton#sidebarAccountButton {
    background: transparent;
    border: none;
    border-radius: ${radius_sm}px;
    padding: ${space_sm}px;
    text-align: left;
}

QToolButton#sidebarAccountButton:hover {
    background-color: $hover;
}

QLabel#sidebarAccountName {
    color: $text_primary;
    font-weight: 500;
}

QLabel#sidebarAccountMeta {
    color: $text_muted;
    font-size: ${font_caption}px;
}

QStatusBar {
    background-color: $bg;
    color: $text_muted;
    border-top: 1px solid $border_subtle;
    font-size: ${font_caption}px;
}

QStatusBar QLabel {
    color: $text_muted;
    font-size: ${font_caption}px;
}

QStatusBar::item {
    border: none;
}

QLabel#connectionStatusLabel {
    color: $text_secondary;
    font-size: ${font_caption}px;
    padding: 0 ${space_xs}px;
}

QFrame#demoBanner {
    background-color: $warning_soft;
    border: none;
    border-bottom: 1px solid $warning;
}

QLabel#demoBannerLabel {
    color: $warning;
    font-weight: 600;
}

/* ==== toasts ============================================================== */

QFrame#toast {
    background-color: $surface_elevated;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
}

QLabel#toastText {
    color: $text_primary;
}

/* ==== page chrome ========================================================= */

QLabel#pageTitle {
    color: $text_primary;
    font-size: ${font_page_title}px;
    font-weight: 600;
}

QLabel#pageSubtitle {
    color: $text_secondary;
}

QLabel#settingsSectionTitle, QLabel#sectionTitle {
    color: $text_muted;
    font-size: ${font_caption}px;
    font-weight: 600;
}

QFrame#card, QFrame#statCard, QFrame#reportCard, QFrame#accountCard, QFrame#launchPanel {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
}

QLabel#cardTitle {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QLabel#cardCount {
    color: $text_secondary;
    font-size: ${font_caption}px;
    font-weight: 500;
    background-color: $hover;
    border-radius: ${radius_sm}px;
    padding: 2px ${space_sm}px;
}

QLabel#helperText, QLabel#summaryLabel, QLabel#charCountLabel, QLabel#attachmentsPreviewLabel {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QLabel#fieldLabel {
    color: $text_primary;
    font-weight: 500;
}

QLabel#emptyStateTitle {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QLabel#emptyStateBody {
    color: $text_secondary;
}

QLabel#monoText {
    font-family: "$font_family_mono", "$font_family_mono_fallback", monospace;
    color: $text_secondary;
}

/* ---- status: labels, pills, dots ---------------------------------------- */

QLabel[status="success"] { color: $success; }
QLabel[status="warning"] { color: $warning; }
QLabel[status="error"] { color: $error; }
QLabel[status="info"] { color: $accent; }

QLabel#statusLabel {
    font-weight: 600;
}

QLabel#pill {
    background-color: $hover;
    color: $text_secondary;
    border-radius: 10px;
    padding: 2px ${space_sm}px;
    font-size: ${font_caption}px;
    font-weight: 500;
}

QLabel#pill[status="success"] { background-color: $success_soft; color: $success_ink; }
QLabel#pill[status="warning"] { background-color: $warning_soft; color: $warning_ink; }
QLabel#pill[status="error"] { background-color: $error_soft; color: $error_ink; }
QLabel#pill[status="info"] { background-color: $info_soft; color: $info_ink; }

QLabel#statusDot {
    min-width: ${status_dot}px;
    max-width: ${status_dot}px;
    min-height: ${status_dot}px;
    max-height: ${status_dot}px;
    border-radius: ${status_dot_radius}px;
    background-color: $text_muted;
}

QLabel#statusDot[status="success"] { background-color: $success; }
QLabel#statusDot[status="warning"] { background-color: $warning; }
QLabel#statusDot[status="error"] { background-color: $error; }
QLabel#statusDot[status="info"] { background-color: $accent; }

/* ==== buttons ============================================================= */

QPushButton, QToolButton {
    background-color: $surface_elevated;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 6px ${space_md}px;
    min-height: ${control_inner_height}px;
    color: $text_primary;
    font-weight: 500;
}

QPushButton:hover, QToolButton:hover {
    background-color: $hover;
}

QPushButton:pressed, QToolButton:pressed {
    background-color: $pressed;
}

QPushButton:disabled, QToolButton:disabled {
    color: $disabled_text;
    background-color: $disabled_bg;
    border-color: $border_subtle;
}

QPushButton[focusRing="true"], QToolButton[focusRing="true"] {
    border: ${focus_ring}px solid $focus_ring;
    padding: 5px 11px;
}

QPushButton[variant="primary"], QPushButton#primaryButton {
    background-color: $accent;
    border: 1px solid $accent;
    color: $on_accent;
    font-weight: 600;
}

QPushButton[variant="primary"]:hover, QPushButton#primaryButton:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}

QPushButton[variant="primary"]:pressed, QPushButton#primaryButton:pressed {
    background-color: $accent_pressed;
    border-color: $accent_pressed;
}

QPushButton[variant="primary"]:disabled, QPushButton#primaryButton:disabled {
    background-color: $disabled_bg;
    border-color: $border_subtle;
    color: $disabled_text;
}

QPushButton[variant="primary"][focusRing="true"], QPushButton#primaryButton[focusRing="true"] {
    border: ${focus_ring}px solid $text_primary;
}

QPushButton[variant="ghost"], QPushButton#ghostButton, QToolButton[variant="ghost"] {
    background-color: transparent;
    border: 1px solid transparent;
    color: $text_secondary;
}

QPushButton[variant="ghost"]:hover, QPushButton#ghostButton:hover, QToolButton[variant="ghost"]:hover {
    background-color: $hover;
    color: $text_primary;
}

QPushButton[variant="ghost"]:pressed, QPushButton#ghostButton:pressed, QToolButton[variant="ghost"]:pressed {
    background-color: $pressed;
}

QPushButton[variant="ghost"]:disabled, QPushButton#ghostButton:disabled, QToolButton[variant="ghost"]:disabled {
    background-color: transparent;
    border-color: transparent;
    color: $disabled_text;
}

QPushButton[variant="ghost"][focusRing="true"], QPushButton#ghostButton[focusRing="true"],
QToolButton[variant="ghost"][focusRing="true"] {
    border: ${focus_ring}px solid $focus_ring;
}

QPushButton[variant="danger"], QPushButton#dangerButton {
    background-color: transparent;
    border: 1px solid $border;
    color: $error;
}

QPushButton[variant="danger"]:hover, QPushButton#dangerButton:hover {
    background-color: $error_soft;
    border-color: $error;
}

QPushButton[variant="danger"]:disabled, QPushButton#dangerButton:disabled {
    color: $disabled_text;
    border-color: $border_subtle;
    background-color: transparent;
}

QToolButton[variant="icon"], QToolButton#chipRemoveButton, QToolButton#journalToggleButton,
QToolButton#favoriteButton, QToolButton#iconButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: ${radius_sm}px;
    padding: ${space_xs}px;
    min-height: 0px;
}

QToolButton[variant="icon"]:hover, QToolButton#journalToggleButton:hover,
QToolButton#favoriteButton:hover, QToolButton#iconButton:hover {
    background-color: $hover;
}

QToolButton#chipRemoveButton:hover {
    background-color: $error_soft;
}

QToolButton[variant="icon"][focusRing="true"], QToolButton#chipRemoveButton[focusRing="true"],
QToolButton#iconButton[focusRing="true"], QToolButton#favoriteButton[focusRing="true"] {
    border: ${focus_ring}px solid $focus_ring;
}

QToolButton#toolbarButton, QPushButton#toolbarButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: ${radius_sm}px;
    padding: ${space_xs}px ${space_sm}px;
    color: $text_secondary;
    min-height: 0px;
}

QToolButton#toolbarButton:hover, QPushButton#toolbarButton:hover {
    background-color: $hover;
    color: $text_primary;
}

QToolButton#toolbarButton:checked {
    background-color: $accent_soft;
    border-color: transparent;
    color: $text_primary;
}

QToolButton#toolbarButton::menu-indicator {
    image: none;
    width: 0px;
}

QToolButton:checkable:checked {
    background-color: $accent_soft;
    border-color: $accent;
    color: $text_primary;
}

/* Segmented control: a row of checkable buttons inside #segmented. */
QFrame#segmented {
    background-color: $bg;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
}

QFrame#segmented QPushButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px ${space_md}px;
    color: $text_secondary;
    min-height: 0px;
}

QFrame#segmented QPushButton:hover {
    color: $text_primary;
}

QFrame#segmented QPushButton:checked {
    background-color: $surface_elevated;
    border: 1px solid $border;
    color: $text_primary;
}

QFrame#segmented QPushButton[focusRing="true"] {
    border: ${focus_ring}px solid $focus_ring;
}

/* ==== inputs ============================================================== */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QListWidget, QTextBrowser, QTableView {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 5px ${space_sm}px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}

QLineEdit, QSpinBox, QComboBox {
    min-height: ${control_inner_height}px;
}

QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover, QComboBox:hover {
    border-color: $scrollbar_handle;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid $focus_ring;
}

QLineEdit[focusRing="true"], QPlainTextEdit[focusRing="true"], QTextEdit[focusRing="true"],
QSpinBox[focusRing="true"], QComboBox[focusRing="true"], QListWidget[focusRing="true"] {
    border: ${focus_ring}px solid $focus_ring;
}

/* A QLineEdit's action icons (addAction: search, clear button) are
   QToolButtons inside the field. Without this they inherit the regular
   button rule above -- min-height, padding, border, background -- and
   sit taller than the field itself, pushed down and over its frame. Qt
   positions and sizes them; the QSS only has to stay out of the way. */
QLineEdit QToolButton,
QLineEdit QToolButton:hover,
QLineEdit QToolButton:pressed,
QLineEdit QToolButton:disabled,
QLineEdit QToolButton[focusRing="true"] {
    background: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
    min-height: 0px;
    min-width: 0px;
}

QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    color: $disabled_text;
    background-color: $disabled_bg;
    border-color: $border_subtle;
}

QLineEdit[readOnly="true"] {
    color: $text_secondary;
    background-color: $disabled_bg;
}

QComboBox {
    padding-right: ${space_xl}px;
}

QComboBox::drop-down {
    border: none;
    width: ${space_xl}px;
    subcontrol-position: center right;
}

QComboBox::down-arrow {
    image: url($chevron_down_url);
    width: 12px;
    height: 12px;
}

/* The popup is its own top-level view; Qt doesn't theme it through the
   QComboBox selector. */
QComboBox QAbstractItemView {
    background-color: $surface_elevated;
    color: $text_primary;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: ${space_xs}px;
    outline: none;
    selection-background-color: $hover;
    selection-color: $accent;
}

QComboBox QAbstractItemView::item {
    padding: 6px ${space_sm}px;
    border-radius: 4px;
    min-height: 20px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: $hover;
}

QComboBox QAbstractItemView::item:selected {
    background-color: $hover;
    color: $text_primary;
}

/* ---- checkboxes ---------------------------------------------------------- */

QCheckBox {
    spacing: ${space_sm}px;
    color: $text_primary;
    background: transparent;
}

QCheckBox::indicator, QListWidget::indicator, QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $scrollbar_handle;
    border-radius: 4px;
    background-color: $input_bg;
}

QCheckBox::indicator:hover, QListWidget::indicator:hover {
    border-color: $accent;
}

QCheckBox::indicator:checked, QListWidget::indicator:checked, QTableView::indicator:checked {
    background-color: $accent;
    border-color: $accent;
    image: url($check_url);
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

QCheckBox[focusRing="true"]::indicator {
    border: ${focus_ring}px solid $focus_ring;
}

/* ---- spin boxes: arrows must be images once the buttons carry any QSS -- */

QSpinBox {
    padding-right: ${space_xl}px;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: $spinbox_button;
    border: none;
    border-left: 1px solid $border_subtle;
    width: 20px;
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
    width: 10px;
    height: 10px;
}

QSpinBox::down-arrow {
    image: url($spinbox_down_arrow_url);
    width: 10px;
    height: 10px;
}

/* ---- lists / tables -------------------------------------------------------- */

QListWidget {
    padding: ${space_xs}px;
}

QListWidget::item {
    padding: ${space_xs}px;
    border-radius: 4px;
}

QListWidget::item:hover {
    background-color: $hover;
}

QListWidget::item:selected {
    background-color: $accent_soft;
    color: $text_primary;
}

QHeaderView::section {
    background-color: $surface;
    color: $text_muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: ${space_sm}px;
    font-size: ${font_caption}px;
    font-weight: 600;
}

QLabel#tableHeader {
    color: $text_muted;
    font-size: ${font_caption}px;
    font-weight: 600;
}

QListView#dialogPickerList {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 0px;
    outline: none;
}

QListView#dialogPickerList[focusRing="true"] {
    border: ${focus_ring}px solid $focus_ring;
}

QListView#dialogPickerList::item {
    border-bottom: 1px solid $border_subtle;
    padding: 0px ${space_xs}px;
}

QListView#dialogPickerList::item:hover {
    background-color: $hover;
}

QListView#dialogPickerList::item:disabled:hover {
    background-color: transparent;
}

QListView#dialogPickerList::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $scrollbar_handle;
    border-radius: 4px;
    background-color: $input_bg;
}

QListView#dialogPickerList::indicator:hover {
    border-color: $accent;
}

QListView#dialogPickerList::indicator:checked {
    background-color: $accent;
    border-color: $accent;
    image: url($check_url);
}

QListWidget#resultsList {
    padding: 0px;
}

QListWidget#resultsList::item {
    border-radius: 0px;
    border-bottom: 1px solid $border_subtle;
    padding: 0px;
}

QListWidget#resultsList::item:selected {
    background-color: $hover;
}

/* Custom attachment tiles draw their own selection; neutralize the view's
   own item paint and the native focus rectangle (outline). */
QListWidget#attachmentsList::item,
QListWidget#attachmentsList::item:selected,
QListWidget#attachmentsList::item:focus {
    background-color: transparent;
    border: none;
    outline: none;
}

QListWidget#attachmentsList {
    outline: none;
}

QWidget#attachmentTile {
    background-color: transparent;
    border-radius: ${radius_md}px;
    border: ${focus_ring}px solid transparent;
}

QWidget#attachmentTile[selected="true"] {
    background-color: $accent_soft;
    border: ${focus_ring}px solid $accent;
}

/* Attachment cards have no hover effect at all -- not even on the remove
   button inside them, which would otherwise flash as the mouse sweeps a row
   of cards. */
QWidget#attachmentTile QToolButton#chipRemoveButton:hover {
    background-color: transparent;
    border-color: transparent;
}

QWidget#attachmentTile[focused="true"] {
    border: ${focus_ring}px solid $focus_ring;
}

QFrame#thumbnailTile, QLabel#thumbnailImage {
    background-color: $thumbnail_bg;
    border-radius: ${radius_sm}px;
}

QLabel#thumbnailName {
    color: $text_primary;
    font-size: ${font_caption}px;
}

QLabel#thumbnailMeta {
    color: $text_muted;
    font-size: ${font_caption}px;
}

QFrame#attachmentChip {
    background-color: $surface_elevated;
    border: 1px solid $border_subtle;
    border-radius: ${radius_sm}px;
}

QLabel#attachmentChipName {
    color: $text_primary;
    font-size: ${font_helper}px;
}

/* ==== progress ============================================================== */

QProgressBar {
    background-color: $hover;
    border: none;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: $accent;
    border-radius: 3px;
}

/* ==== results / accounts / reports ========================================== */

QLabel#statValue {
    color: $text_primary;
    font-size: ${font_stat_value}px;
    font-weight: 600;
}

QLabel#statLabel {
    color: $text_muted;
    font-size: ${font_caption}px;
    font-weight: 500;
}

QFrame#accountCard[active="true"] {
    border: 1px solid $accent;
}

QLabel#accountName, QLabel#reportName {
    color: $text_primary;
    font-size: ${font_body}px;
    font-weight: 600;
}

QLabel#accountMeta, QLabel#reportMeta {
    color: $text_muted;
    font-size: ${font_helper}px;
}

QLabel#avatar {
    background-color: $accent_soft;
    color: $accent;
    border-radius: ${avatar_radius}px;
    font-weight: 600;
    min-width: ${avatar}px;
    max-width: ${avatar}px;
    min-height: ${avatar}px;
    max-height: ${avatar}px;
}

QLabel#avatar[size="large"] {
    border-radius: ${avatar_lg_radius}px;
    min-width: ${avatar_lg}px;
    max-width: ${avatar_lg}px;
    min-height: ${avatar_lg}px;
    max-height: ${avatar_lg}px;
    font-size: ${font_card_title}px;
}

QFrame#reportCard:hover {
    border-color: $scrollbar_handle;
}

/* ==== launch / progress panel (Campaign page) ================================ */

QLabel#launchTitle {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QLabel#summaryKey {
    color: $text_muted;
}

QLabel#summaryValue {
    color: $text_primary;
    font-weight: 500;
}

QLabel#bigCounter {
    color: $text_primary;
    font-size: ${font_page_title}px;
    font-weight: 600;
}

QFrame#floodBlock {
    background-color: $warning_soft;
    border: 1px solid $warning;
    border-radius: ${radius_sm}px;
}

QLabel#floodTitle {
    color: $warning;
    font-weight: 600;
}

QLabel#floodCountdown {
    color: $text_primary;
    font-size: ${font_page_title}px;
    font-weight: 600;
    font-family: "$font_family_mono", "$font_family_mono_fallback", monospace;
}

/* ==== message preview ("chat") =============================================== */

QFrame#chatPreview {
    background-color: $chat_bg;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
}

QTextBrowser#bubbleBrowser {
    background: transparent;
    border: none;
    padding: 0px;
}

QLabel#bubbleText {
    color: $bubble_text;
    background: transparent;
}

QLabel#bubbleMeta {
    color: $bubble_meta;
    font-size: ${font_caption}px;
}

/* ==== journal ================================================================== */

QFrame#journalPanel {
    background-color: $surface;
    border: none;
    border-left: 1px solid $border;
}

QLabel#journalTitle {
    color: $text_primary;
    font-weight: 600;
}

QListWidget#journalList {
    background-color: transparent;
    border: none;
    padding: 0px;
}

QListWidget#journalList::item {
    padding: 0px;
    border-radius: 0px;
}

QListWidget#journalList::item:hover, QListWidget#journalList::item:selected {
    background-color: $hover;
}

/* ==== dialogs ================================================================== */

QFrame#dialogFooter {
    background-color: $bg;
    border: none;
    border-top: 1px solid $border;
}

QLabel#dialogTitle {
    color: $text_primary;
    font-size: ${font_card_title}px;
    font-weight: 600;
}

QMessageBox {
    background-color: $surface;
}

QMessageBox QLabel {
    color: $text_primary;
}

QLabel#dialogErrorLabel {
    color: $error;
}

QLabel#stepIndicator {
    color: $text_muted;
    font-size: ${font_caption}px;
    font-weight: 500;
}

QLabel#stepIndicator[status="info"] {
    color: $accent;
    font-weight: 600;
}

QFrame#stepBar {
    background-color: $border;
    border: none;
    min-height: 2px;
    max-height: 2px;
}

QFrame#stepBar[status="info"] {
    background-color: $accent;
}

/* ==== scrollbars =============================================================== */

QScrollBar:vertical {
    background: $scrollbar_track;
    width: 10px;
    margin: 2px;
    border: none;
}

QScrollBar::handle:vertical {
    background: $scrollbar_handle;
    border-radius: 3px;
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
    margin: 2px;
    border: none;
}

QScrollBar::handle:horizontal {
    background: $scrollbar_handle;
    border-radius: 3px;
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
"""
)
