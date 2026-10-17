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

4. **Contrast adjustments to the brief's starting colours** (all ratios WCAG 2.1, checked by `tests/test_color_contrast.py`):
   - Dark `text_muted` `#6B7280` → `#767E8B`: the brief's value is 3.9:1 on the window background but only 3.6:1 on the `#16191F` card surface where most helper text sits; the new value is 4.6 / 4.3:1.
   - Light `text_muted` `#8A93A0` → `#7A8391`: 3.0:1 is exactly on the floor; now 3.6:1.
   - Light accent `#3A6FF0` → `#3366E6`: white button text on `#3A6FF0` is 4.46:1, a hair under AA 4.5; now 5.0:1.
   - Dark `on_accent` is **dark text** (`#0B0D12`) on the `#5B8CFF` accent: white on it is only 3.2:1. Dark-on-light-blue is 6.2:1 and still reads as a calm primary button. This also closed the long-tracked "dark primary button contrast" gap (`test_color_contrast.py` explicitly asked to be updated when that happened — it was).
   - Dark link colour inside the message bubble is the accent lightened 18 % (5.5:1 on the bubble instead of 4.3:1).
   - Light status colours: success `#1A7F37`, warning `#9A6700`, error `#CF222E` (4.5–5.0:1 on the background).
5. **Icons: a QIconEngine, not baked pixmaps.** `app/ui/icons.py` renders Lucide SVGs through a custom `QIconEngine`. `icons.themed(name, role, checked_role, active_role)` stores *token names*, not colours, and resolves them at paint time — so a theme switch recolours every icon on the next repaint without any widget re-setting icons, and SVGs are rendered at the exact device size (crisp at 125 %/150 %). `icons.icon(name, color)` remains for fixed colours; the old glyph names (`campaign`, `close`, `check_circle`, …) are aliases.
6. **Keyboard-only focus ring.** QSS has no `:focus-visible`, so an application event filter sets a `focusRing` property on Tab/Backtab/shortcut focus and clears it on other focus changes; the QSS draws the 2 px accent ring from that property. Mouse clicks don't flash rings.
7. **Title bar.** `DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE)` (attribute 20, falling back to 19 for pre-20H1 Windows 10) is applied to every top-level window as it is shown and to all visible windows on a switch, with a `SWP_FRAMECHANGED` nudge so the frame repaints. Any failure is silent.
8. **Fonts.** Inter Regular/Medium/SemiBold (OFL, `assets/fonts/inter/`) registered once via `QFontDatabase`; QSS lists `"Inter", "Segoe UI"`. Monospace (IDs, journal time stamps, counters) is `"Cascadia Mono", Consolas` — not bundled (ships with Windows 11 / Windows Terminal; Consolas is the fallback everywhere).
9. **QSS sub-control images** (check mark, combo chevron, spin arrows) are Lucide icons rendered to 1x and @2x PNGs in the theme-assets cache per theme, because QSS can only take a file `image:` there.
10. **Message preview** is now a chat bubble painted from tokens (outgoing, tail bottom-right, album grid, file rows, time). Its HTML colours re-render on `theme.notifier.theme_changed`; bubble/album repaint by themselves.
11. **Accounts:** the active account's button became a quiet "✓ Active" state (ghost + check icon) instead of a filled primary button — it is a state, not an action; the page's single primary action is "Add account". Delete is an icon button that turns red on hover (the confirmation dialog already existed).
12. **Changed tests (old markup only):** `test_color_contrast.py` known-gap test → AA assertion (as that test instructed); `test_message_preview.py` asserted the old hard-coded spoiler hex `#54565c` and the `📎` emoji glyph — now asserts the token value and the file name.

(continued below as the work proceeds)
