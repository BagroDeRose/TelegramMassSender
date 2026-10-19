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

13. **Shell.** Sidebar 220 px ↔ 64 px icon rail (labels become tooltips/accessible names), state in a new `sidebar_collapsed` setting; active item = 3 px accent bar + light fill; the active account (initials, name, status dot) at the bottom opens Accounts. The journal moved to the *right* of the page (it describes the page, it isn't navigation). The status bar no longer repeats the Demo Mode text.
14. **Toasts vs. modals.** Toasts (bottom-right, ~3 s, 180 ms fade) for: preset saved, group saved, report saved, diagnostics copied, settings reset, chats added. File exports (CSV, diagnostic bundle) keep a modal box: it shows the saved path, which the user may need — and an existing test pins that behaviour.
15. **Campaign page fold rule** uses the page area's own width (`CAMPAIGN_FOLD_WIDTH` = 1100 − sidebar), not the window's: an open journal or the expanded sidebar also folds the columns. In the folded layout, starting a campaign scrolls the progress panel into view. The pinned right column scrolls by itself when the window is short (found at 150 % scaling).
16. **Launch panel people/chats split** is by recipient *format*: `-100…`, `t.me/c/…` and invite links are groups/channels; `@username`/`t.me/name` are counted with users ("Users & @usernames") because their type is only known after resolving — same rule as the start confirmation.
17. **FloodWait block**: countdown in monospace; its Continue button only enables once the campaign has actually paused after the wait. The wait itself is never shortened.
18. **Results**: "Retry all failures" is the page's single primary button (when there are failures); exports are secondary/ghost on a second row. Rows stay `QListWidgetItem`s (checkable for Retry, SendItem in UserRole, plain-text summary as their text) and a delegate paints the table — so Retry, filters and tests keep working unchanged. The filter is a segmented control with a QComboBox-compatible API (`_results_filter_combo` keeps working).
19. **Status colours on tints.** In the light theme the plain status colours were 4.2–4.4:1 on their own 12 % tint (pills) — under AA for 12 px text. New `*_ink` tokens (status −18 % lightness in light, unchanged in dark) are used for text on tints only.
20. **Message boxes.** A `QProxyStyle` installed by `apply_theme` supplies themed message-box icons (also for static `QMessageBox.warning()` calls, which some tests patch and which therefore stay static) and the GNOME button layout, so the primary action is on the right everywhere. Delete-account warns instead of asking.
21. **Journal markers.** The campaign layer (logic — not touched) prefixes journal lines with `✓ ✗ … ▶ ⏸ ■ ✖ ↷`. The journal turns the marker into a themed icon and strips it from the visible text; the item text keeps it (tests, accessibility).
22. **Hygiene is enforced, not just done once.** `scripts/check_ui_hygiene.py` (run by `tests/test_ui_hygiene.py`) fails on hex/rgb/named colours, `setStyleSheet`, numeric pixel arguments to size/margin/spacing setters, or emoji/symbol glyphs in `app/ui` outside `theme/`; the only allowed glyphs are the emoji palette and the journal-marker table.
23. **Window minimum** lowered from 1040×760 to 900×600 so the app fits a 1366×768 screen at 125 % (1093×614 logical).
24. **Changed tests (old markup only):** `test_main_window_ux` — `"▶  Start campaign"` → `"Start campaign"` (the ▶ glyph became an icon); `test_stat_card` — the value's colour property is `status` (was `variant`); `test_color_contrast` and `test_message_preview` as noted in 12. Nothing else in the existing suite changed; `test_theme.py` (theme application/persistence) passes unchanged.

## 4. What changed on each screen

| Screen | Before | After |
| --- | --- | --- |
| Shell | Fixed sidebar with a 3-line brand, journal wedged between menu and page, native title bar | Collapsible sidebar with accent bar and active-account block, journal on the right, thin status bar with a status dot, dark title bar in the dark theme, page fade, toasts |
| Campaign | One long column; preview a plain text box; Start below the fold | Two columns: inputs left, chat-bubble preview + launch panel pinned right; panel turns into progress with a FloodWait countdown block; count pills; grouped action rows |
| Results | Combo filter, list of "label — error" strings, yellow "completed" | Status pill, tiles coloured on the number only, failure reasons one per line, segmented filter, table rows (status pill, type icon + text, monospace ID), report rows with a "more" menu |
| Accounts | Avatar pixmap, inline-HTML bullet status, filled "Active" button | Initials avatar, status pill, quiet "✓ Active" state, trash icon (red on hover), single-action empty state |
| Settings | Labels above controls, varying widths, reset among options | Label column + one control width, hints under controls, danger reset last with an explanation, monospace diagnostics |
| Journal | Truncated lines with horizontal scroll, text markers | Wrapped rows: muted monospace time, status icon, message; "no events yet" state |
| Dialogs / Wizard | Ad-hoc layouts and button orders; emoji toolbar | Title / content / footer with primary right; Wizard step indicator; Lucide toolbar; themed message boxes |

## 5. Verification

- `pytest tests/` in one process: 913 passed (was 883 before this branch).
- `scripts/check_ui_hygiene.py`: 0 findings. Plain greps, for the record:
  - `setStyleSheet` in `app/`: one call, `app/ui/theme/__init__.py` (`apply_theme`).
  - hex colours in `app/**/*.py` outside `app/ui/theme/tokens.py`: none.
  - emoji/symbol glyphs in `app/ui`: only the emoji palette (`message_editor._EMOJI_LIST`) and the journal-marker table (input parsing, never displayed).
- Screenshots: `docs/redesign/before/` (34) and `docs/redesign/after/` (84 at the end of the redesign, 104 with the dialog picker's — section 7: every page and dialog, both themes, RU and EN, plus `window_frame_*` showing the real title bar and `theme_switch_live_*` taken right after a live switch with the editor open).
- Checked by screenshot at 125 % and 150 % (`QT_SCALE_FACTOR`) and at the 900×600 minimum window.

## 6. Not done / deliberately left

- **Cascadia Mono is not bundled** (it ships with Windows 11 and Windows Terminal; Consolas is the fallback everywhere).
- **Native message boxes** (QMessageBox) keep Qt's own layout; only their icons, button variants and order are themed. A fully custom confirmation dialog was not worth replacing a mechanism several tests patch directly.
- **Attachments tile grid** keeps its existing structure (it has 100+ behavioural tests around drag-and-drop and selection); it got tokens, icons and the new colours, not a new layout.
- **Text formatted as code** in the editor uses the monospace token; its background colour is not themed (it never was — only spoiler and link colours are tracked in the document).
- Only the Campaign page has an explicit Tab chain; the other pages rely on Qt's creation order, which already matches their visual order after the redesign.

## 7. "From my chats…" shows every dialog (branch `feature/dialog-picker`)

The picker used to list only the groups/channels the account could post to. It now lists every dialog of the active account and lets the user choose whom to send to. Sending itself is unchanged — only how the Recipients box gets filled.

Screens: `docs/redesign/after/dialog_chat_picker_*` (list, `_filters` with a folder + archive + People, `_loading`), `dialog_wizard_chat_picker_*` / `dialog_wizard_recipients_picked_*` (the same picker from the wizard), `theme_switch_live_picker_*` (taken right after a live theme switch with the picker open) — both themes, RU and EN.

### Decisions

25. **Service layer, not UI, talks to Telegram.** `chat_targets.list_dialogs(client)` returns a `DialogList` of `DialogTarget`s (type incl. bot, title, @username, peer id — positive for people, marked for chats —, archived, last-message date, unavailable reason, folder ids) plus the folder list. It never keeps an entity or access_hash; the Recipients box line is resolved again at send. It reads only `iter_dialogs(ignore_migrated=True)` and `GetDialogFiltersRequest` — no joining, no avatars, no per-dialog requests. Migrated basic groups are skipped because their supergroup is listed.
26. **Excluded dialogs:** Saved Messages (`is_self`), deleted accounts, and 777000 (Telegram's service notifications).
27. **Writable.** People and bots are writable by default (whether one has blocked the account isn't knowable without sending); chats go through the existing `check_send_rights` for a plain text message. The reason key becomes the row's tooltip.
28. **Folders follow Telegram's own rule order:** explicitly added (pinned/included) peers are always in, explicitly excluded ones always out, then `exclude_archived/read/muted`, then the type flags (contacts, non-contacts, groups, channels, bots). Shared chat-list folders use their peers; the "All chats" default is skipped.
29. **A folder failure — FloodWait included — hides the folder filter** instead of failing the list: folders only narrow the view, and the request is never repeated. A FloodWait on the dialog list itself is shown in the picker with the wait, never retried behind the user's back; "Refresh" is the user's choice.
30. **Non-blocking.** The picker opens at once in a loading state (`open()`, window-modal, not `exec()` inside a coroutine) and MainWindow loads in `self._spawn(...)` under `_account_lock`, feeding the result in with `set_dialogs()` / `set_error()`. A result that arrives after the picker closed is dropped. One picker at a time across the page and the wizard.
31. **Model/view for thousands.** `QAbstractListModel` sorted newest first once per load; `QSortFilterProxyModel` filters on plain fields precomputed per load (casefolded title+username), never on `data()` roles, and keeps the source order instead of re-sorting; one `dataChanged` per bulk tick. 5000 dialogs: each filter change well under 0.25 s (tested), building ~0.1 s.
32. **Row.** Check box | initials circle (accent tint; muted grey for unavailable rows) | name (with an archive mark) over type icon + label + `@username` or ID in monospace | date over an "already listed" pill. Unavailable and already-listed rows have no check box and no hover. A click anywhere on a tickable row toggles it; Space works from the keyboard. The list never scrolls sideways.
33. **"Already listed"** compares normalized recipient keys, so `@name`, `t.me/name` and the numeric ID of the same addressee all match, for people (`101`) and chats (`-100…`, `t.me/c/…`).
34. **Counter** reads "Selected: N (people X, chats Y)"; bots get their own "bots Z" part only when one is ticked, rather than being counted as people.
35. **IDs for people without a @username.** Such a person goes into the box as their positive ID. If the session has no access_hash for it at send time, `RecipientResolver` reads the dialogs once — the same lazy warm-up chat IDs already used — and takes the user from there (FloodWait propagates and pauses the campaign as before). Never a guessed access_hash.
36. **Wizard.** Its recipients step shows the same button (`RecipientWidget(show_chat_picker=True)`), wired by MainWindow to the same picker and loading path, opened over the wizard, writing into the wizard's own box.
37. **Tokens / icons.** New sizes live in `tokens.py` (`DIALOG_PICKER_*`); Lucide `bot` and `archive` were added to `assets/icons/lucide` (ISC, v0.469.0 like the rest). The list is a `QListView#dialogPickerList` with its own QSS block; no inline styles.
38. **Demo Mode** got people (with and without a @username, contacts and not), two bots, archived dialogs, three folders and the three excluded dialogs, each with a date, so every part of the picker can be tried without an account.
39. **Changed tests (old API only):** `test_chat_targets_ui` (the picker tests moved from `QListWidget` items / `_type_combo` / `list_writable_chats` to the model, segments and `list_dialogs` — same scenarios), `test_chat_targets_resolve` and `test_demo_mode_chats` (`list_writable_chats` → `list_dialogs`; the demo list gained "Demo Old Project"), `test_theme_switch_live` (new constructor; also checks the picker's list after a switch; its last MainWindow test became async so its refresh task no longer outlives the suite).

### Verification

- `pytest tests/` in one process: 1009 passed (913 before this branch); 1162 after the follow-up below, 1168 with the line-edit icon tests, 1184 with the layout-fit tests (decision 44).
- `scripts/check_ui_hygiene.py`: 0 findings.
- Screenshots captured on the real Windows platform through the real qasync loop, including the wizard run via `exec()` from a Qt slot with the picker loading inside it.

### Not done

- **No avatars** (by design: nothing is downloaded); initials only.
- **Dialogs are read in full each time** the picker opens or refreshes — there's no cache across opens, so a list that changed in Telegram is always current.
- **Forum topics** stay out of scope: a forum is still posted to "General".

### Follow-up on the same branch

40. **Large-campaign guard.** More recipients than `large_campaign_threshold` (Settings → Sending, default 50, minimum 10) always asks before starting, whatever `confirm_before_start` says, on all three start paths through one `MainWindow._confirm_campaign_start` (so Retry now honours the optional confirmation too). The box lists people, bots, groups/channels and @usernames of not-yet-known type (known from the dialog cache where possible); Start is `danger`, Cancel is the default and escape button and has focus. Only one question is ever asked: above the threshold the large-campaign box replaces the optional one.
41. **`theme.set_property` for buttons a QMessageBox already polished.** A box styles each button as it is added; a plain `setProperty("variant", "danger")` afterwards left Start unstyled (the old boxes only got away with it because their styled button was also the default, which re-polishes). Tested against the rendered colour.
42. **Dialog cache.** Before: every picker open read all dialogs and folders again, and a campaign's resolver never saw that data (each campaign's first chat ID or unknown user ID read the dialogs again). Now `load_dialog_snapshot()` returns the list plus every dialog's entity by peer id; MainWindow keeps one `DialogSnapshot` for the active account for the session (`DialogCache`, keyed by account id + session name, cleared on switch, Demo Mode in/out, delete and Refresh). The resolver starts from it and reads the dialogs from Telegram again only for a missing ID, at most once per campaign. Trade-off: rights changed in Telegram since the last read are seen at send time (Telegram's own error), or after Refresh.
43. **One path from token to QColor.** Translucent tokens are `rgba(...)` strings — QSS reads them, `QColor("rgba(...)")` is invalid (black) and SVG draws nothing. `parse_color()` / `theme.qcolor()` read every token form and raise on anything else; the icon renderer uses the same parser; every `QColor(token)` in `app/ui` was moved over, and `check_ui_hygiene.py` now flags any raw `QColor(...)` outside `theme/` (except `Qt.GlobalColor.transparent`). Every colour token of both themes is tested.
44. **Columns fold by what they need, rows wrap.** At the default first-run window (1180 px) the Campaign page's left column needed 674 px and got 546; with sideways scrolling off, the rest was cut off (and a focus change could scroll it sideways), and the right column was 6 px too narrow for the launch panel at every width. Cause: the fold rule was a fixed width (`CAMPAIGN_FOLD_WIDTH`) unrelated to the content, and button rows (attachments, group, preset, import) could not wrap. Now `ResponsiveColumns` folds when the page is narrower than `two_column_width()` — the left column's real minimum plus the right column's *preferred* width (never below the old threshold) — re-checked on resize and whenever either column's contents change; those rows are `FlowLayout`s that wrap, page subtitles and the launch panel's captions wrap only when squeezed (`WrappingLabel`), so even the narrowest page (900 px window, journal open, sidebar expanded: 360 px) shows everything. Tested for 900–1920 px, journal open/closed, sidebar expanded/collapsed, on every page (`tests/test_layout_fit.py`); checked on the real platform at 100/125/150 % in both themes and languages.

## 8. Patch v2.1.1 (branch `fix/v2.1.1`)

45. **Counts by what the dialog cache knows.** A channel added by `@username` was missing from "groups & channels": the format alone can't tell a channel's @username from a person's. The counts under every Recipients box (`dialogs.recipient_breakdown()`, also used by the launch panel and the large-campaign box) now take a recipient's category from the session's dialog cache when it is there — person, bot, group/channel — and only otherwise from the format. An `@username` the cache doesn't know gets its own "@username: N" pill, with a tooltip saying its type is known when sending. Every cache change (fill, Refresh, account switch, Demo Mode in/out, delete) goes through `_cache_dialogs`/`_drop_dialog_cache`, so the counts on the page and in an open wizard re-count by themselves. Nothing is resolved for counting.
46. **"Lists ▾" and "Templates ▾".** The rows "Group: [combo] Load / Save as… / Delete" and the same for presets wrapped at the default 1180 px window and read as three unrelated controls. Each is now one menu button (`saved_menu.SavedItemsMenuButton`) in its card's header — next to the count on Recipients, on the title line of Message — with "Save current…", a Load submenu and a Delete submenu listing what is saved; while nothing is, both submenus are disabled and a disabled line says why. Tooltips say what each is for. The UI calls them saved lists and templates (RU "Сохранённые списки"/"Шаблоны", EN "Lists"/"Templates"); code and database keep groups/presets, so saved data needs no migration. The wizard has the same two menus on its Recipients and Message steps, acting on the wizard's own boxes (a template's interval goes into the wizard's spin boxes and reaches the settings only when that step is left, like anything typed there). The button paints its own Lucide `chevron-down` (the style's arrow is hidden, `QPushButton[menuButton="true"]`) with the label left-aligned, so the chevron never crowds the text.
47. **Diagnostics in plain words.** One row per check — icon and text in the status colour (`check-circle`/`success`, `warning`, `error-circle`/`error`, `info`/`text_muted`), a hint under a row that needs attention ("sign in to that account again on the Accounts page", ...). No repeated labels; "Saved sign-ins: 2 of 2 accounts". Python/Telethon versions sit under a collapsed "Technical details". "Open data folder" opens it in Explorer without showing the path. The Telegram row names the account by @username only — the old text fell back to the phone number, which then went into the copied text and the bundle.
48. **"0 of 2" saved sessions.** Diagnostics checked `get_session_path(name).exists()`, a path without the `.session` extension Telethon adds, so the count was always 0 although every session was saved. `paths.get_session_file_path()` is now the one place that knows the file name; the demo account is left out of the count. Found on the way: MainWindow tests with accounts wrote real session files into the developer's `%APPDATA%`; `tests/conftest.py` now points `APPDATA` at a temporary folder for the whole run.
49. **No empty pill on the empty Results page.** The small filled square above the report buttons was the campaign-status pill with no text yet — a pill-styled QLabel draws its background and padding even when empty. It and the duration next to it are shown only once they have text.
50. **Changed tests (old markup only):** `test_main_window_ux` — the preset/group save/load/delete tests trigger the new menu actions instead of selecting a combo item and clicking a button (same scenarios, same assertions on the repositories, the menu's items instead of the combo's); the two "Load with nothing selected shows an error" tests became "nothing saved: Load/Delete disabled with a reason", since a menu has no selection. `test_shell_redesign` — the preset toast test saves through the menu. `test_diagnostics` — the session-count test uses real `.session` file names; the text-format test checks items, hints and technical details.

### Verification

- `pytest tests/` in one process: 1214 passed (1184 before this branch).
- `scripts/check_ui_hygiene.py`: 0 findings.
- Real Windows platform, window grabs only, Demo Mode: 900 / 1180 / 1920 px, journal and sidebar in every state, 100 % and 150 %, both themes, RU and EN — no page clipped.
- Known and left alone: the Recipients box's own button row (Import TXT, Import CSV, From my chats…, Clear) still wraps "Clear" to a second line at 1100–1180 px with the sidebar expanded, as it did before this patch.
