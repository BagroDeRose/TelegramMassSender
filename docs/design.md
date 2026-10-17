# UI redesign — design notes

Working document for the `feature/ui-redesign` branch: what the theme system
looked like before, the UX problems found per screen, and every decision taken
along the way (the redesign was done autonomously, so the reasoning lives here).

Concept: **"a quiet console"** — a work tool you trust. Almost monochrome; colour
carries meaning only (status, progress, the one main action). No gradients,
glows, decorative shadows, looping animations or mascots. The only two
expressive places are the message preview and the launch/progress panel.

Screenshots: `docs/redesign/before/` and `docs/redesign/after/`, captured with
`scripts/capture_screenshots.py` (real Windows platform, isolated temporary
database and secret store, Demo Mode, synthetic data only).

---

## 1. Inventory of the theme system before the redesign

| What | Where |
| --- | --- |
| Stored choice | SQLite `settings` table, key `theme` (`app/config/settings.py: SETTINGS_KEY_THEME`), values `"dark"` / `"light"`, default `"dark"` (`DEFAULT_THEME`). Read/written by `SettingsRepository`. |
| Switch UI | Settings → Appearance → `MainWindow._theme_combo` (`itemData` = `"dark"`/`"light"`), handled by `MainWindow._on_theme_combo_changed`, applied immediately. |
| Application point | `MainWindow._apply_theme()` at startup and `_on_theme_combo_changed()` on a switch: `theme.set_active_theme()` + one `QApplication.setStyleSheet(theme.stylesheet_for(name))`. |
| Tokens + QSS | `app/ui/theme.py`: `Tokens` dataclass, `_DARK` / `_LIGHT`, one `string.Template` QSS rendered for both themes, scale constants (`SPACE_*`, `RADIUS_*`, `FONT_SIZE_*`), `FONT_FAMILY = "Segoe UI"`. |
| Generated assets | `QSpinBox` arrow PNGs written to `get_theme_assets_dir()` by `stylesheet_for()` (QSS can't colour those sub-controls). |
| Colour read by logic (not QSS) | `theme.current_tokens()` / accessors in: `sidebar.py` (nav icon tint), `account_widget.py` (status dot `●` inline HTML, avatar, delete icon), `journal_widget.py` (row status icons, close icon), `attachments_widget.py` (tile glyphs, tile action icons), `main_window.py::_update_connection_status` (status-bar dot `●` inline HTML), `message_editor.py` (spoiler/link `QTextCharFormat`), `message_preview.py` (placeholder, code, spoiler, link inline HTML), `thumbnails.py` (letterbox colour). |
| Re-tint on switch | `_on_theme_combo_changed` calls `apply_theme()` on sidebar, attachments, journal, accounts and re-renders the preview. Open dialogs were **not** refreshed (they only had the global QSS). |
| QPalette | Never set — native Windows palette everywhere QSS doesn't reach (`QMessageBox` icons/text, text selection in some widgets, `QToolTip` fallback, context menus of line edits). |
| Window title bar | Native, always light on Windows 10/11 even in the dark theme. |
| Icons | Hand-drawn `QPainter` glyphs in `app/ui/icons.py` (campaign, accounts, results, settings, attachment, document, close, edit, check/error circle, clock, plus, video, audio, archive). |
| Emoji / symbol glyphs used as icons | Buttons: `▶ ⏸ ■` (start/pause/resume/stop), `✏` (open editor ×2), `⋯` (report menu), `★ ☆` (favourite), editor toolbar `🙈 🔗 🙂`, `📎` (attachment list in the preview), `●` (status dots), `✓ ■` in result status labels, `✓` in the login success title. Journal lines carry `✓ ✗ ▶ ⏸ ■ ✖ ↷ …` prefixes produced by the campaign layer. |
| Inline `setStyleSheet` | None besides the single global call (good — nothing to override the new QSS). |
| Inline HTML colours | Status dots (account card, status bar) and the message preview's rich text. |

## 2. UX problems found (per screen)

**Shell**
- The sidebar can't collapse and carries a 3-line brand block that eats space; the active account is only visible in the status bar.
- The Demo Mode text appears twice (banner + status bar message).
- Page switches are instant jumps; there are no non-blocking notifications — "preset saved", "report saved", "copied" are all modal message boxes that need a click.
- Dark theme still shows a white Windows title bar.

**Campaign**
- One long column: the message preview and the Start button are below the fold on a 1280×860 window; you scroll to start, and scroll again to watch progress.
- The "preview" is a plain text box, not something that reads as a message.
- The Start/progress area mixes interval, estimate, three buttons, a progress bar, a stats sentence and an export button with no hierarchy. FloodWait is a single orange sentence.
- Recipient counters are one long sentence ("12 получателей (из них групп/каналов…, ошибок формата: 1)").
- The preview-name field and the `{name}` hint sit far from the preview they affect.
- Emoji `✏`, `📎` render as tofu/coloured emoji inconsistently.

**Results**
- Status line "✓ Рассылка завершена" is drawn in the *warning* colour (yellow) even on success.
- Recipient list is a plain `QListWidget` of "label — error" strings: no columns, no status badges, IDs in proportional font, type as "(канал)" text.
- The filter is a combo box for four options; the failure breakdown is a long run-on sentence.
- Export CSV is a primary button although the page's main action is ambiguous; three equal-weight export buttons.

**Accounts**
- Card actions: "Активен" is a primary-looking filled button for a state, not an action; delete is a bare `×`.
- Empty state has two buttons of similar weight.

**Settings**
- Section cards are fine, but control widths vary, labels sit above controls inconsistently, the danger "reset" button lives among ordinary options.

**Journal**
- Fixed 260 px panel squeezed *between* sidebar and page; lines are truncated with a horizontal scrollbar; timestamps are proportional; the leading `✓/✗` text marker duplicates the icon.

**Dialogs**
- No shared structure: editor/wizard/login each place buttons differently; the wizard has no step indicator beyond "Шаг 5 из 6"; message boxes use native icons on a dark background.

## 3. Decisions

Recorded as they were taken. Each is "decision — why".

1. **Migrate, don't rebuild.** `app/ui/theme.py` becomes the package `app/ui/theme/` (`tokens.py`, `qss.py`, `palette.py`, `fonts.py`, `__init__.py` re-exporting the old public names). Every existing `from app.ui import theme` / `from app.ui.theme import SPACE_LG` keeps working, the settings key and values are untouched, so a user's stored `"light"` simply opens the new light theme. — The brief forbids a second system, and the existing tests pin this API.
2. **One application point.** `MainWindow._apply_theme()` / `_on_theme_combo_changed()` both go through a single `theme.apply_theme(app, name)` that sets the palette, fonts and the stylesheet once, then notifies live widgets through a `ThemeNotifier` signal. No widget calls `setStyleSheet`. — Global `setStyleSheet` repolishes every live widget; doing it once per switch is the only acceptable cost.
3. **Old token names kept as aliases** where tests or call sites rely on them (`surface_elevated`, `selected_account`, `spinbox_*`, `scrollbar_*`, `link`, `spoiler_*`, `code_bg`, `placeholder`, `thumbnail_bg`, `favorite`). Their values now derive from the new palette instead of being independent hex values.

(continued below as the work proceeds)
