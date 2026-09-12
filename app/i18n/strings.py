"""The translation catalog: every user-facing string in the app, keyed by a
dotted path roughly matching "module.section.thing", mapped to its Russian
(the app's original language, always complete) and English text.

Deliberately NOT translated (kept as plain literals at each call site,
never routed through tr()): the product name ("Telegram Mass Sender",
"Mass Sender") -- brand identity does not change with the UI language.
Also not translated: the generated CSV report's own content (headers,
status words) -- it is a file artifact for the user's own records, not a
UI surface, and changing its column headers based on UI language was not
requested and would be a silent scope expansion.

STRINGS entries are plain key -> {"ru": ..., "en": ...} templates, used
via app.i18n.translator.tr() (str.format() placeholders for parameterized
ones, e.g. "{name}"). PLURALS entries are for the handful of counted
nouns that need real plural-form agreement (Russian: one/few/many;
English: one/other) rather than a single naively-pluralized template --
used via app.i18n.translator.trn().
"""
from __future__ import annotations

from typing import Dict

STRINGS: Dict[str, Dict[str, str]] = {
    # ---- main_window: status bar / toolbar --------------------------------
    "main_window.status.ready": {"ru": "Готово", "en": "Ready"},
    "main_window.status.no_account": {"ru": "Нет подключённого аккаунта", "en": "No account connected"},
    "main_window.status.connected": {"ru": "Подключён: {label}", "en": "Connected: {label}"},
    "main_window.journal_toggle.text": {"ru": "Журнал", "en": "Journal"},
    "main_window.journal_toggle.tooltip": {"ru": "Показать/скрыть журнал", "en": "Show/hide journal"},
    "main_window.status.campaign_running": {"ru": "Рассылка выполняется…", "en": "Campaign running…"},
    "main_window.status.campaign_paused": {"ru": "Рассылка на паузе", "en": "Campaign paused"},
    "main_window.status.campaign_waiting_flood": {"ru": "Ожидание ограничения Telegram…", "en": "Waiting on a Telegram limit…"},
    "main_window.status.campaign_completed": {"ru": "Рассылка завершена", "en": "Campaign completed"},
    "main_window.status.campaign_stopped": {"ru": "Рассылка остановлена", "en": "Campaign stopped"},
    "main_window.status.campaign_error": {"ru": "Рассылка остановлена из-за ошибки", "en": "Campaign stopped due to an error"},
    "main_window.results.running": {"ru": "Рассылка выполняется…", "en": "Campaign running…"},
    "main_window.results.completed": {"ru": "✓ Рассылка завершена", "en": "✓ Campaign completed"},
    "main_window.results.stopped": {"ru": "■ Рассылка остановлена", "en": "■ Campaign stopped"},
    "main_window.results.error": {"ru": "! Рассылка остановлена из-за критической ошибки", "en": "! Campaign stopped due to a critical error"},
    "main_window.flood_wait.started": {
        "ru": "Telegram временно ограничил отправку. Необходимо подождать: {duration}",
        "en": "Telegram has temporarily limited sending. Waiting: {duration}",
    },
    "main_window.flood_wait.tick": {
        "ru": "Ожидание окончания ограничения Telegram: {duration}",
        "en": "Waiting for the Telegram limit to lift: {duration}",
    },
    "main_window.duration.minutes_seconds": {"ru": "{minutes} мин {seconds} сек", "en": "{minutes}m {seconds}s"},
    "main_window.duration.seconds": {"ru": "{seconds} сек", "en": "{seconds}s"},

    # ---- main_window: campaign page ----------------------------------------
    "main_window.campaign_page.title": {"ru": "Кампания", "en": "Campaign"},
    "main_window.campaign_page.subtitle": {"ru": "Создайте и запустите рассылку в Telegram", "en": "Create and launch a Telegram campaign"},
    "main_window.campaign_page.recipients_card": {"ru": "Получатели", "en": "Recipients"},
    "main_window.groups.placeholder": {"ru": "Выберите группу…", "en": "Choose a group…"},
    "main_window.groups.load_button": {"ru": "Загрузить", "en": "Load"},
    "main_window.groups.save_button": {"ru": "Сохранить как…", "en": "Save as…"},
    "main_window.groups.delete_button": {"ru": "Удалить", "en": "Delete"},
    "main_window.dialogs.save_group_title": {"ru": "Сохранить группу", "en": "Save group"},
    "main_window.dialogs.group_name_label": {"ru": "Название группы:", "en": "Group name:"},
    "main_window.dialogs.group_saved_message": {"ru": "Группа «{name}» сохранена.", "en": "Group “{name}” saved."},
    "main_window.dialogs.no_group_selected": {"ru": "Сначала выберите группу в списке.", "en": "First select a group from the list."},
    "main_window.dialogs.delete_group_title": {"ru": "Удалить группу?", "en": "Delete group?"},
    "main_window.dialogs.delete_group_message": {
        "ru": "Группа «{name}» будет удалена без возможности восстановления. Продолжить?",
        "en": "The group “{name}” will be permanently deleted. Continue?",
    },
    "main_window.campaign_page.open_editor_button": {"ru": "✏  Открыть редактор", "en": "✏  Open editor"},
    "main_window.campaign_page.open_editor_tooltip": {
        "ru": "Полноразмерный редактор для длинных сообщений с форматированием",
        "en": "Full-size editor for long, formatted messages",
    },
    "main_window.campaign_page.name_placeholder_hint": {
        "ru": "{{name}} — имя получателя в Telegram, подставляется при отправке",
        "en": "{{name}} — the recipient's Telegram name, filled in when sending",
    },
    "main_window.campaign_page.message_card": {"ru": "Сообщение", "en": "Message"},
    "main_window.presets.placeholder": {"ru": "Выберите шаблон…", "en": "Choose a preset…"},
    "main_window.presets.load_button": {"ru": "Загрузить", "en": "Load"},
    "main_window.presets.save_button": {"ru": "Сохранить как…", "en": "Save as…"},
    "main_window.presets.delete_button": {"ru": "Удалить", "en": "Delete"},
    "main_window.dialogs.save_preset_title": {"ru": "Сохранить шаблон", "en": "Save preset"},
    "main_window.dialogs.preset_name_label": {"ru": "Название шаблона:", "en": "Preset name:"},
    "main_window.dialogs.preset_saved_message": {"ru": "Шаблон «{name}» сохранён.", "en": "Preset “{name}” saved."},
    "main_window.dialogs.no_preset_selected": {"ru": "Сначала выберите шаблон в списке.", "en": "First select a preset from the list."},
    "main_window.dialogs.delete_preset_title": {"ru": "Удалить шаблон?", "en": "Delete preset?"},
    "main_window.dialogs.delete_preset_message": {"ru": "Шаблон «{name}» будет удалён без возможности восстановления. Продолжить?", "en": "The preset “{name}” will be permanently deleted. Continue?"},
    "main_window.dialogs.preset_missing_attachments_title": {"ru": "Вложения не найдены", "en": "Attachments not found"},
    "main_window.dialogs.preset_missing_attachments_message": {
        "ru": "Следующие файлы из шаблона больше не найдены и не были добавлены: {names}",
        "en": "The following files from the preset could no longer be found and were not added: {names}",
    },
    "main_window.campaign_page.preview_name_label": {"ru": "Пример имени для {{name}}:", "en": "Example name for {{name}}:"},
    "main_window.campaign_page.preview_name_default": {"ru": "Александр", "en": "Alex"},
    "main_window.campaign_page.preview_name_tooltip": {
        "ru": (
            "Показывает, как сообщение будет выглядеть после подстановки "
            "{{name}} -- реальное имя получателя недоступно до момента "
            "отправки, это лишь пример"
        ),
        "en": (
            "Shows how the message will look once {{name}} is filled in -- "
            "the recipient's real name isn't available before sending, "
            "this is just an example"
        ),
    },
    "main_window.campaign_page.attachments_card": {"ru": "Вложения", "en": "Attachments"},
    "main_window.campaign_page.campaign_card": {"ru": "Рассылка", "en": "Campaign"},
    "main_window.campaign_page.open_wizard_button": {"ru": "Мастер кампании", "en": "Campaign Wizard"},

    # ---- app/ui/campaign_wizard.py -------------------------------------------
    "campaign_wizard.title": {"ru": "Мастер кампании", "en": "Campaign Wizard"},
    "campaign_wizard.step_label": {"ru": "Шаг {current} из {total}: {title}", "en": "Step {current} of {total}: {title}"},
    "campaign_wizard.step.recipients": {"ru": "Получатели", "en": "Recipients"},
    "campaign_wizard.step.message": {"ru": "Сообщение", "en": "Message"},
    "campaign_wizard.step.attachments": {"ru": "Вложения", "en": "Attachments"},
    "campaign_wizard.step.sending_options": {"ru": "Параметры отправки", "en": "Sending options"},
    "campaign_wizard.step.preview": {"ru": "Предпросмотр", "en": "Preview"},
    "campaign_wizard.step.confirmation": {"ru": "Подтверждение", "en": "Confirmation"},
    "campaign_wizard.back_button": {"ru": "Назад", "en": "Back"},
    "campaign_wizard.next_button": {"ru": "Далее", "en": "Next"},
    "campaign_wizard.cancel_button": {"ru": "Отмена", "en": "Cancel"},
    "campaign_wizard.start_button": {"ru": "Начать рассылку", "en": "Start campaign"},
    "campaign_wizard.recipients.hint": {
        "ru": "Добавьте получателей: @username, ID, ссылки t.me или номера телефонов в международном формате.",
        "en": "Add recipients: @username, ID, t.me links, or international-format phone numbers.",
    },
    "campaign_wizard.message.hint": {
        "ru": "Составьте текст сообщения. {{name}} будет заменено на имя получателя при отправке.",
        "en": "Write the message text. {{name}} will be replaced with the recipient's name when sending.",
    },
    "campaign_wizard.message.open_editor_button": {"ru": "✏  Открыть редактор", "en": "✏  Open editor"},
    "campaign_wizard.message.empty": {"ru": "Сообщение ещё не задано.", "en": "No message text yet."},
    "campaign_wizard.sending_options.hint": {
        "ru": "Интервал между отправками сообщений (в секундах). Это общая настройка приложения.",
        "en": "The interval between sends, in seconds. This is a shared application setting.",
    },
    "campaign_wizard.confirmation.summary": {
        "ru": (
            "Получателей: {recipients}\n"
            "Вложений: {attachments}\n"
            "Интервал между отправками: {min}–{max} сек\n\n"
            "Нажмите «Начать рассылку», чтобы запустить кампанию."
        ),
        "en": (
            "Recipients: {recipients}\n"
            "Attachments: {attachments}\n"
            "Interval between sends: {min}–{max}s\n\n"
            "Click “Start campaign” to launch the campaign."
        ),
    },

    # ---- main_window: accounts page ----------------------------------------
    "main_window.accounts_page.title": {"ru": "Аккаунты", "en": "Accounts"},
    "main_window.accounts_page.subtitle": {"ru": "Подключённые Telegram-аккаунты", "en": "Connected Telegram accounts"},

    # ---- main_window: results page ------------------------------------------
    "main_window.results_page.title": {"ru": "Результаты", "en": "Results"},
    "main_window.results_page.subtitle": {"ru": "Статистика текущей рассылки и сохранённые отчёты", "en": "Current campaign statistics and saved reports"},
    "main_window.results_page.empty_title": {"ru": "Нет данных о рассылке", "en": "No campaign data yet"},
    "main_window.results_page.empty_body": {
        "ru": "Запустите рассылку на странице «Кампания», чтобы увидеть статистику здесь.",
        "en": "Start a campaign on the Campaign page to see statistics here.",
    },
    "main_window.results_page.stat_total": {"ru": "Всего", "en": "Total"},
    "main_window.results_page.stat_successful": {"ru": "Успешно", "en": "Successful"},
    "main_window.results_page.stat_failed": {"ru": "Ошибок", "en": "Failed"},
    "main_window.results_page.stat_skipped": {"ru": "Пропущено", "en": "Skipped"},
    "main_window.results_page.export_csv_button": {"ru": "Экспорт CSV-отчёта", "en": "Export CSV report"},
    "main_window.results_page.export_failures_button": {"ru": "Экспортировать только ошибки", "en": "Export failures only"},
    "main_window.results_page.save_report_button": {"ru": "Сохранить отчёт", "en": "Save report"},
    "main_window.results_page.duration_label": {"ru": "Длительность: {duration}", "en": "Duration: {duration}"},
    "main_window.results_page.failure_categories": {"ru": "Причины ошибок: {categories}", "en": "Failure reasons: {categories}"},
    "main_window.results_page.unknown_error": {"ru": "неизвестная ошибка", "en": "unknown error"},
    "main_window.results_page.recipients_section": {"ru": "Получатели", "en": "Recipients"},
    "main_window.results_page.filter_label": {"ru": "Показать:", "en": "Show:"},
    "main_window.results_page.filter_all": {"ru": "Все", "en": "All"},
    "main_window.results_page.filter_sent": {"ru": "Отправлено", "en": "Sent"},
    "main_window.results_page.filter_failed": {"ru": "Ошибки", "en": "Failed"},
    "main_window.results_page.filter_skipped": {"ru": "Пропущено", "en": "Skipped"},
    "main_window.results_page.retry_selected_button": {"ru": "Повторить выбранные", "en": "Retry selected"},
    "main_window.results_page.retry_all_button": {"ru": "Повторить все ошибки", "en": "Retry all failures"},
    "main_window.results_page.saved_reports_section": {"ru": "Сохранённые отчёты", "en": "Saved reports"},
    "main_window.results_page.saved_reports_empty_title": {"ru": "Нет сохранённых отчётов", "en": "No saved reports"},
    "main_window.results_page.saved_reports_empty_body": {
        "ru": "Сохраните отчёт о рассылке, чтобы найти его здесь позже.",
        "en": "Save a campaign report to find it here later.",
    },
    "main_window.results_page.report_open_button": {"ru": "Открыть", "en": "Open"},
    "main_window.results_page.report_export_button": {"ru": "Экспорт", "en": "Export"},
    "main_window.results_page.report_more_button": {"ru": "⋯", "en": "⋯"},
    "main_window.results_page.report_more_tooltip": {"ru": "Ещё", "en": "More"},
    "main_window.results_page.report_rename_action": {"ru": "Переименовать", "en": "Rename"},
    "main_window.results_page.report_delete_action": {"ru": "Удалить", "en": "Delete"},
    "main_window.results_page.report_favorite_tooltip": {"ru": "Избранное", "en": "Favorite"},
    "main_window.results_page.report_favorite_on": {"ru": "★", "en": "★"},
    "main_window.results_page.report_favorite_off": {"ru": "☆", "en": "☆"},
    "main_window.results_page.report_meta_line": {
        "ru": "{total} получателей · {successful} успешно · {failed} ошибок",
        "en": "{total} recipients · {successful} successful · {failed} failed",
    },

    # ---- main_window: settings page -----------------------------------------
    "main_window.settings_page.title": {"ru": "Настройки", "en": "Settings"},
    "main_window.settings_page.subtitle": {"ru": "Параметры приложения", "en": "Application settings"},
    "main_window.settings.appearance_card": {"ru": "Внешний вид", "en": "Appearance"},
    "main_window.settings.sending_card": {"ru": "Отправка", "en": "Sending"},
    "main_window.settings.application_card": {"ru": "Приложение", "en": "Application"},
    "main_window.settings.reports_card": {"ru": "Отчёты", "en": "Reports"},
    "main_window.settings.advanced_card": {"ru": "Дополнительно", "en": "Advanced"},
    "main_window.settings.theme_label": {"ru": "Тема оформления", "en": "Theme"},
    "main_window.settings.theme_hint": {
        "ru": "Выбор темы сохраняется и восстанавливается при следующем запуске",
        "en": "The chosen theme is saved and restored on the next launch",
    },
    "main_window.settings.language_label": {"ru": "Язык интерфейса", "en": "Interface language"},
    "main_window.settings.language_hint": {
        "ru": "Выбор языка сохраняется и применяется сразу, без перезапуска",
        "en": "The chosen language is saved and applied immediately, no restart needed",
    },
    "main_window.settings.interval_label": {"ru": "Интервал отправки, сек", "en": "Sending interval, sec"},
    "main_window.settings.interval_dash": {"ru": "—", "en": "—"},
    "main_window.settings.interval_hint": {
        "ru": (
            "Случайная пауза перед отправкой каждому следующему получателю. "
            "Снижает интенсивность работы программы, но не гарантирует "
            "отсутствие ограничений со стороны Telegram."
        ),
        "en": (
            "A random pause before sending to each next recipient. Reduces "
            "how intensively the app operates, but does not guarantee "
            "Telegram won't apply its own limits."
        ),
    },
    "main_window.settings.confirm_before_start_checkbox": {"ru": "Подтверждать запуск рассылки", "en": "Confirm before starting a campaign"},
    "main_window.settings.confirm_before_start_tooltip": {
        "ru": "Показывать диалог подтверждения перед стартом каждой рассылки",
        "en": "Show a confirmation dialog before every campaign start",
    },
    "main_window.settings.remember_window_size_checkbox": {"ru": "Запоминать размер окна", "en": "Remember window size"},
    "main_window.settings.remember_last_page_checkbox": {"ru": "Открывать последний раздел при запуске", "en": "Open the last-used page on launch"},
    "main_window.settings.reports_directory_label": {"ru": "Папка для отчётов", "en": "Reports folder"},
    "main_window.settings.browse_button": {"ru": "Обзор…", "en": "Browse…"},
    "main_window.settings.default_button": {"ru": "По умолчанию", "en": "Default"},
    "main_window.settings.auto_save_reports_checkbox": {
        "ru": "Автоматически сохранять отчёт после рассылки",
        "en": "Automatically save a report after each campaign",
    },
    "main_window.settings.debug_logging_checkbox": {"ru": "Расширенное логирование (для диагностики)", "en": "Verbose logging (for diagnostics)"},
    "main_window.settings.reset_settings_button": {"ru": "Сбросить настройки приложения", "en": "Reset application settings"},

    # ---- main_window: settings dialogs / handlers ----------------------------
    "main_window.dialogs.interval_title": {"ru": "Интервал отправки", "en": "Sending interval"},
    "main_window.dialogs.reports_directory_title": {"ru": "Папка для отчётов", "en": "Reports folder"},
    "main_window.dialogs.settings_title": {"ru": "Настройки", "en": "Settings"},
    "main_window.dialogs.settings_reset_message": {
        "ru": "Настройки приложения сброшены к значениям по умолчанию.",
        "en": "Application settings have been reset to their defaults.",
    },
    "main_window.dialogs.unavailable_title": {"ru": "Недоступно", "en": "Unavailable"},
    "main_window.dialogs.add_account_unavailable": {
        "ru": "Добавление аккаунта недоступно во время рассылки.",
        "en": "You can't add an account while a campaign is running.",
    },
    "main_window.dialogs.delete_account_unavailable": {
        "ru": "Удаление аккаунта недоступно во время рассылки.",
        "en": "You can't delete an account while a campaign is running.",
    },
    "main_window.dialogs.switch_account_title": {"ru": "Переключение аккаунта", "en": "Switching account"},
    "main_window.dialogs.switch_account_failed": {
        "ru": "Не удалось переключить аккаунт.\nПроверьте подключение и состояние сессии.",
        "en": "Couldn't switch accounts.\nCheck your connection and the session state.",
    },

    # ---- main_window: campaign start validation ------------------------------
    "main_window.dialogs.campaign_title": {"ru": "Рассылка", "en": "Campaign"},
    "main_window.start_error.already_running": {
        "ru": "Для этого аккаунта уже выполняется рассылка.",
        "en": "A campaign is already running for this account.",
    },
    "main_window.start_error.no_account": {
        "ru": "Сначала подключите и выберите Telegram-аккаунт.",
        "en": "First connect and select a Telegram account.",
    },
    "main_window.start_error.no_recipients": {
        "ru": "Список получателей пуст или не содержит корректных значений.",
        "en": "The recipient list is empty or contains no valid entries.",
    },
    "main_window.start_error.missing_files": {
        "ru": "Не найдены прикреплённые файлы: {names}",
        "en": "Attached file(s) not found: {names}",
    },
    "main_window.start_error.unreadable_files": {
        "ru": (
            "Не удалось прочитать файлы: {names}. Файл может быть открыт в "
            "другой программе или у вас нет прав на его чтение. Закройте "
            "файл в других программах или выберите другой файл."
        ),
        "en": (
            "Couldn't read file(s): {names}. The file may be open in "
            "another program, or you may not have permission to read it. "
            "Close it in other programs or choose a different file."
        ),
    },
    "main_window.start_error.no_content": {
        "ru": "Введите текст сообщения или добавьте вложение.",
        "en": "Enter message text or add an attachment.",
    },
    "main_window.start_error.not_authorized": {
        "ru": "Аккаунт не авторизован. Подключите аккаунт заново.",
        "en": "The account isn't authorized. Reconnect the account.",
    },
    "main_window.start_error.connect_failed": {
        "ru": "Не удалось подключиться к Telegram: {error}",
        "en": "Couldn't connect to Telegram: {error}",
    },
    "main_window.dialogs.campaign_error_title": {"ru": "Рассылка остановлена", "en": "Campaign stopped"},
    "main_window.dialogs.campaign_error_message": {
        "ru": "Рассылка остановлена из-за критической ошибки аккаунта. Подробности см. в журнале.",
        "en": "The campaign stopped due to a critical account error. See the journal for details.",
    },

    # ---- main_window: reports ---------------------------------------------
    "main_window.report.default_name": {"ru": "Рассылка {timestamp}", "en": "Campaign {timestamp}"},
    "main_window.dialogs.save_report_title": {"ru": "Сохранить отчёт", "en": "Save report"},
    "main_window.dialogs.report_name_label": {"ru": "Название:", "en": "Name:"},
    "main_window.dialogs.save_report_error_title": {"ru": "Сохранение отчёта", "en": "Saving report"},
    "main_window.dialogs.save_report_error_message": {"ru": "Не удалось сохранить отчёт: {error}", "en": "Couldn't save the report: {error}"},
    "main_window.dialogs.report_saved_title": {"ru": "Отчёт сохранён", "en": "Report saved"},
    "main_window.dialogs.report_saved_message": {
        "ru": "Отчёт «{name}» добавлен в сохранённые отчёты.",
        "en": "Report “{name}” was added to your saved reports.",
    },
    "main_window.dialogs.report_title": {"ru": "Отчёт", "en": "Report"},
    "main_window.dialogs.report_file_missing": {"ru": "Файл отчёта не найден: {path}", "en": "Report file not found: {path}"},
    "main_window.dialogs.export_report_title": {"ru": "Экспорт отчёта", "en": "Export report"},
    "main_window.dialogs.export_report_file_filter": {"ru": "CSV файлы (*.csv)", "en": "CSV files (*.csv)"},
    "main_window.dialogs.export_report_saved": {"ru": "Отчёт сохранён: {path}", "en": "Report saved: {path}"},
    "main_window.dialogs.rename_report_title": {"ru": "Переименовать отчёт", "en": "Rename report"},
    "main_window.dialogs.export_report_write_failed": {"ru": "Не удалось сохранить файл: {error}", "en": "Couldn't save the file: {error}"},

    # ---- sidebar ------------------------------------------------------------
    "sidebar.nav.campaign": {"ru": "Кампания", "en": "Campaign"},
    "sidebar.nav.accounts": {"ru": "Аккаунты", "en": "Accounts"},
    "sidebar.nav.results": {"ru": "Результаты", "en": "Results"},
    "sidebar.nav.settings": {"ru": "Настройки", "en": "Settings"},
    "sidebar.brand_subtitle": {"ru": "для Telegram", "en": "for Telegram"},

    # ---- campaign_controls ---------------------------------------------------
    "campaign_controls.edit_in_settings_button": {"ru": "Изменить в настройках", "en": "Edit in Settings"},
    "campaign_controls.start_button": {"ru": "▶  Начать рассылку", "en": "▶  Start campaign"},
    "campaign_controls.start_tooltip": {
        "ru": "Нужны: подключённый аккаунт, хотя бы один получатель и текст или вложение",
        "en": "Needed: a connected account, at least one recipient, and text or an attachment",
    },
    "campaign_controls.pause_button": {"ru": "⏸  Пауза", "en": "⏸  Pause"},
    "campaign_controls.resume_button": {"ru": "▶  Продолжить", "en": "▶  Resume"},
    "campaign_controls.stop_button": {"ru": "■  Остановить", "en": "■  Stop"},
    "campaign_controls.stats_line": {
        "ru": "Всего: {total}    Отправлено: {sent}    Ошибок: {failed}    Пропущено: {skipped}    Осталось: {pending}",
        "en": "Total: {total}    Sent: {sent}    Failed: {failed}    Skipped: {skipped}    Remaining: {pending}",
    },
    "campaign_controls.export_report_button": {"ru": "Экспорт отчёта", "en": "Export report"},
    "campaign_controls.export_report_tooltip": {
        "ru": "Сохранить результаты текущей рассылки в CSV-файл (открывается в Excel)",
        "en": "Save the current campaign's results to a CSV file (opens in Excel)",
    },
    "campaign_controls.interval_summary": {"ru": "Интервал отправки: {min}–{max} сек", "en": "Sending interval: {min}–{max} sec"},
    "campaign_controls.duration_estimate": {
        "ru": "Приблизительная длительность рассылки: {duration}",
        "en": "Estimated campaign duration: {duration}",
    },
    "campaign_controls.current_item": {
        "ru": "Получатель {position} из {total}: {recipient}",
        "en": "Recipient {position} of {total}: {recipient}",
    },
    "campaign_controls.elapsed_remaining": {
        "ru": "Прошло: {elapsed}  ·  Осталось: ~{remaining}",
        "en": "Elapsed: {elapsed}  ·  Remaining: ~{remaining}",
    },
    "campaign_controls.elapsed_only": {"ru": "Прошло: {elapsed}", "en": "Elapsed: {elapsed}"},

    # ---- account_widget --------------------------------------------------
    "account_widget.status.connected": {"ru": "Подключён", "en": "Connected"},
    "account_widget.status.connection_problem": {"ru": "Проблема с подключением", "en": "Connection problem"},
    "account_widget.status.reauth_required": {"ru": "Требуется повторная авторизация", "en": "Re-authorization required"},
    "account_widget.status.not_authorized": {"ru": "Не авторизован", "en": "Not authorized"},
    "account_widget.empty_title": {"ru": "Нет Telegram-аккаунтов", "en": "No Telegram accounts"},
    "account_widget.empty_body": {"ru": "Добавьте аккаунт, чтобы начать.", "en": "Add an account to get started."},
    "account_widget.add_account_button": {"ru": "+ Добавить аккаунт", "en": "+ Add account"},
    "account_widget.reconnect_button": {"ru": "Переподключить", "en": "Reconnect"},
    "account_widget.use_button_active": {"ru": "Активен", "en": "Active"},
    "account_widget.use_button_inactive": {"ru": "Использовать", "en": "Use"},
    "account_widget.delete_tooltip": {"ru": "Удалить аккаунт", "en": "Delete account"},
    "account_widget.switching": {"ru": "Переключение…", "en": "Switching…"},

    # ---- recipient_widget -----------------------------------------------
    "recipient_widget.placeholder": {
        "ru": "@username1\n123456789\n+4917612345678\nhttps://t.me/username3",
        "en": "@username1\n123456789\n+4917612345678\nhttps://t.me/username3",
    },
    "recipient_widget.tooltip": {
        "ru": (
            "По одному получателю на строку: @username, Telegram ID, ссылка "
            "t.me/...\nили номер телефона в международном формате (например "
            "+4917612345678)"
        ),
        "en": (
            "One recipient per line: @username, Telegram ID, a t.me/... "
            "link,\nor a phone number in international format (e.g. "
            "+4917612345678)"
        ),
    },
    "recipient_widget.import_txt_button": {"ru": "Импорт TXT", "en": "Import TXT"},
    "recipient_widget.import_csv_button": {"ru": "Импорт CSV", "en": "Import CSV"},
    "recipient_widget.clear_button": {"ru": "Очистить", "en": "Clear"},
    "recipient_widget.empty_summary": {
        "ru": "Нет получателей — вставьте @username, ID, ссылки t.me/... или номера телефонов, либо импортируйте TXT- или CSV-файл",
        "en": "No recipients — paste @usernames, IDs, t.me/... links, or phone numbers, or import a TXT or CSV file",
    },
    "recipient_widget.summary_invalid_count": {"ru": "ошибок формата: {count}", "en": "format errors: {count}"},
    "recipient_widget.summary_duplicates_removed": {"ru": "дубликатов удалено: {count}", "en": "duplicates removed: {count}"},
    "recipient_widget.review_invalid_button": {"ru": "Показать ошибки", "en": "Show errors"},
    "recipient_widget.review_invalid_title": {"ru": "Некорректные строки", "en": "Invalid rows"},
    "recipient_widget.import_dialog_title": {"ru": "Импорт получателей", "en": "Import recipients"},
    "recipient_widget.import_file_filter": {"ru": "Текстовые файлы (*.txt)", "en": "Text files (*.txt)"},
    "recipient_widget.import_csv_file_filter": {"ru": "CSV-файлы (*.csv)", "en": "CSV files (*.csv)"},
    "recipient_widget.import_read_failed": {"ru": "Не удалось прочитать файл: {error}", "en": "Couldn't read the file: {error}"},
    "recipient_widget.import_result": {
        "ru": (
            "Импортировано: {total}\nДубликатов удалено: {duplicates}\n"
            "Некорректных строк: {invalid}\nИтого получателей: {valid}"
        ),
        "en": (
            "Imported: {total}\nDuplicates removed: {duplicates}\n"
            "Invalid lines: {invalid}\nTotal recipients: {valid}"
        ),
    },

    # ---- app/recipients/parser.py -------------------------------------------
    "recipients.parser.error.empty_line": {"ru": "Пустая строка", "en": "Empty line"},
    "recipients.parser.error.invalid_phone": {
        "ru": "Некорректный номер телефона. Используйте международный формат, например +4917612345678",
        "en": "Invalid phone number. Use international format, e.g. +4917612345678",
    },
    "recipients.parser.error.invalid_tme_link": {"ru": "Некорректная ссылка t.me", "en": "Invalid t.me link"},
    "recipients.parser.error.invalid_username": {"ru": "Некорректный username", "en": "Invalid username"},
    "recipients.parser.error.unknown_format": {"ru": "Неизвестный формат получателя", "en": "Unrecognized recipient format"},

    # ---- app/recipients/csv_importer.py -------------------------------------
    "csv_importer.error.no_identifier_in_row": {
        "ru": "В строке не найден @username, ID или номер телефона",
        "en": "No @username, ID, or phone number found in this row",
    },

    # ---- attachments_widget -----------------------------------------------
    "attachments_widget.empty_title": {"ru": "Нет вложений", "en": "No attachments"},
    "attachments_widget.empty_body": {
        "ru": "Перетащите файлы сюда или нажмите «Добавить файл»",
        "en": "Drag files here or click “Add file”",
    },
    "attachments_widget.add_button": {"ru": "Добавить файл", "en": "Add file"},
    "attachments_widget.remove_selected_button": {"ru": "Удалить выбранное", "en": "Remove selected"},
    "attachments_widget.clear_button": {"ru": "Очистить", "en": "Clear"},
    "attachments_widget.add_dialog_title": {"ru": "Выбрать файлы", "en": "Choose files"},
    "attachments_widget.remove_tile_button": {"ru": " Удалить", "en": " Remove"},
    "attachments_widget.remove_tile_tooltip": {"ru": "Удалить вложение", "en": "Remove attachment"},

    # ---- journal_widget -----------------------------------------------------
    "journal_widget.title": {"ru": "Журнал", "en": "Journal"},
    "journal_widget.hide_tooltip": {"ru": "Скрыть журнал", "en": "Hide journal"},

    # ---- message_editor -------------------------------------------------
    "message_editor.bold_tooltip": {"ru": "Жирный (Ctrl+B)", "en": "Bold (Ctrl+B)"},
    "message_editor.italic_tooltip": {"ru": "Курсив (Ctrl+I)", "en": "Italic (Ctrl+I)"},
    "message_editor.underline_tooltip": {"ru": "Подчёркнутый (Ctrl+U)", "en": "Underline (Ctrl+U)"},
    "message_editor.strike_tooltip": {"ru": "Зачёркнутый", "en": "Strikethrough"},
    "message_editor.spoiler_tooltip": {"ru": "Спойлер", "en": "Spoiler"},
    "message_editor.code_tooltip": {"ru": "Код", "en": "Code"},
    "message_editor.pre_tooltip": {"ru": "Блок кода", "en": "Code block"},
    "message_editor.link_button": {"ru": "🔗", "en": "🔗"},
    "message_editor.link_tooltip": {"ru": "Добавить ссылку к выделенному тексту", "en": "Add a link to the selected text"},
    "message_editor.emoji_button": {"ru": "🙂", "en": "🙂"},
    "message_editor.emoji_tooltip": {"ru": "Вставить emoji", "en": "Insert emoji"},
    "message_editor.placeholder": {"ru": "Текст сообщения...", "en": "Message text..."},
    "message_editor.link_dialog_title": {"ru": "Ссылка", "en": "Link"},
    "message_editor.link_no_selection": {
        "ru": "Сначала выделите текст, к которому нужно добавить ссылку.",
        "en": "First select the text you want to turn into a link.",
    },
    "message_editor.add_link_dialog_title": {"ru": "Добавить ссылку", "en": "Add link"},
    "message_editor.url_label": {"ru": "URL:", "en": "URL:"},

    # ---- message_editor_dialog --------------------------------------------
    "message_editor_dialog.title": {"ru": "Редактор сообщения", "en": "Message editor"},
    "message_editor_dialog.char_count": {"ru": "Символов: {count}", "en": "Characters: {count}"},
    "message_editor_dialog.cancel_button": {"ru": "Отмена", "en": "Cancel"},
    "message_editor_dialog.apply_button": {"ru": "Применить", "en": "Apply"},
    "message_editor_dialog.unsaved_title": {"ru": "Несохранённые изменения", "en": "Unsaved changes"},
    "message_editor_dialog.unsaved_message": {
        "ru": "Изменения не были применены. Закрыть без сохранения?",
        "en": "Your changes haven't been applied. Close without saving?",
    },
    "message_editor_dialog.unsaved_yes": {"ru": "Да", "en": "Yes"},
    "message_editor_dialog.unsaved_no": {"ru": "Нет", "en": "No"},

    # ---- message_preview ----------------------------------------------------
    "message_preview.placeholder": {"ru": "Текст сообщения появится здесь…", "en": "Your message text will appear here…"},

    # ---- login_dialog -------------------------------------------------------
    "login_dialog.title": {"ru": "Подключение Telegram", "en": "Connect Telegram"},
    "login_dialog.api_id_placeholder": {"ru": "напр. 12345678", "en": "e.g. 12345678"},
    "login_dialog.api_id_tooltip": {
        "ru": "Получается на my.telegram.org/apps (раздел API development tools)",
        "en": "Obtained at my.telegram.org/apps (API development tools section)",
    },
    "login_dialog.api_hash_placeholder": {"ru": "32-символьный API Hash", "en": "32-character API Hash"},
    "login_dialog.api_hash_tooltip": {
        "ru": "Секретный ключ приложения Telegram с my.telegram.org — никому не передавайте его",
        "en": "Your Telegram application's secret key from my.telegram.org — never share it with anyone",
    },
    "login_dialog.phone_placeholder": {"ru": "+79991234567", "en": "+79991234567"},
    "login_dialog.phone_tooltip": {
        "ru": "Номер телефона аккаунта в международном формате, со знаком +",
        "en": "The account's phone number in international format, with a leading +",
    },
    "login_dialog.api_id_label": {"ru": "API ID:", "en": "API ID:"},
    "login_dialog.api_hash_label": {"ru": "API Hash:", "en": "API Hash:"},
    "login_dialog.phone_label": {"ru": "Телефон:", "en": "Phone:"},
    "login_dialog.connect_button": {"ru": "Подключить", "en": "Connect"},
    "login_dialog.error.api_id_not_a_number": {"ru": "API ID должен быть числом.", "en": "API ID must be a number."},
    "login_dialog.error.invalid_api_hash": {"ru": "Введите корректный API Hash.", "en": "Enter a valid API Hash."},
    "login_dialog.error.invalid_phone_format": {
        "ru": "Введите номер телефона в международном формате, напр. +79991234567.",
        "en": "Enter the phone number in international format, e.g. +79991234567.",
    },
    "login_dialog.error.invalid_phone": {"ru": "Некорректный номер телефона.", "en": "Invalid phone number."},
    "login_dialog.error.flood_wait": {
        "ru": "Telegram временно ограничил запросы. Подождите {seconds} сек.",
        "en": "Telegram has temporarily limited requests. Wait {seconds} sec.",
    },
    "login_dialog.error.connect_failed": {"ru": "Не удалось подключиться: {error}", "en": "Couldn't connect: {error}"},
    "login_dialog.code_label": {"ru": "Введите код из Telegram:", "en": "Enter the code from Telegram:"},
    "login_dialog.confirm_button": {"ru": "Подтвердить", "en": "Confirm"},
    "login_dialog.error.code_required": {"ru": "Введите код подтверждения.", "en": "Enter the confirmation code."},
    "login_dialog.error.invalid_code": {"ru": "Неверный код. Попробуйте снова.", "en": "Incorrect code. Try again."},
    "login_dialog.error.code_expired": {
        "ru": "Код истёк. Запросите подключение заново.",
        "en": "The code has expired. Request a new connection.",
    },
    "login_dialog.error.code_confirm_failed": {"ru": "Не удалось подтвердить код: {error}", "en": "Couldn't confirm the code: {error}"},
    "login_dialog.password_label": {"ru": "Введите пароль двухфакторной аутентификации:", "en": "Enter your two-factor authentication password:"},
    "login_dialog.error.password_required": {"ru": "Введите пароль.", "en": "Enter the password."},
    "login_dialog.error.invalid_password": {"ru": "Неверный пароль.", "en": "Incorrect password."},
    "login_dialog.error.password_confirm_failed": {"ru": "Не удалось подтвердить пароль: {error}", "en": "Couldn't confirm the password: {error}"},
    "login_dialog.success_title": {"ru": "✓ Telegram аккаунт подключён", "en": "✓ Telegram account connected"},
    "login_dialog.done_button": {"ru": "Готово", "en": "Done"},
    "login_dialog.summary_account": {"ru": "Аккаунт:\n{phone}", "en": "Account:\n{phone}"},
    "login_dialog.summary_name": {"ru": "Имя:\n{name}", "en": "Name:\n{name}"},
    "login_dialog.summary_username": {"ru": "Username:\n@{username}", "en": "Username:\n@{username}"},
    "login_dialog.summary_username_none": {"ru": "Username:\n-", "en": "Username:\n-"},

    # ---- dialogs.py -----------------------------------------------------
    "dialogs.delete_account.title": {"ru": "Удалить аккаунт?", "en": "Delete account?"},
    "dialogs.delete_account.message": {
        "ru": "Будет удалена локальная Telegram-сессия аккаунта {phone}.\n\nПродолжить?",
        "en": "This will delete the local Telegram session for {phone}.\n\nContinue?",
    },
    "dialogs.yes": {"ru": "Да", "en": "Yes"},
    "dialogs.no": {"ru": "Нет", "en": "No"},
    "dialogs.exit_during_campaign.title": {"ru": "Рассылка ещё выполняется", "en": "A campaign is still running"},
    "dialogs.exit_during_campaign.message": {"ru": "Вы действительно хотите выйти?", "en": "Are you sure you want to quit?"},
    "dialogs.cancel": {"ru": "Отмена", "en": "Cancel"},
    "dialogs.close": {"ru": "Закрыть", "en": "Close"},
    "dialogs.exit": {"ru": "Выйти", "en": "Quit"},
    "dialogs.start_campaign.title": {"ru": "Начать рассылку?", "en": "Start the campaign?"},
    "dialogs.start_campaign.start": {"ru": "Начать", "en": "Start"},
    "dialogs.reset_settings.title": {"ru": "Сбросить настройки?", "en": "Reset settings?"},
    "dialogs.reset_settings.message": {
        "ru": "Все настройки приложения будут возвращены к значениям по умолчанию. Продолжить?",
        "en": "All application settings will be reset to their defaults. Continue?",
    },
    "dialogs.reset_settings.reset": {"ru": "Сбросить", "en": "Reset"},

    # ---- theme.py: theme combo labels --------------------------------------
    "theme.label.dark": {"ru": "Тёмная", "en": "Dark"},
    "theme.label.light": {"ru": "Светлая", "en": "Light"},

    # ---- thumbnails.py: file-size units --------------------------------
    "thumbnails.unit.bytes": {"ru": "Б", "en": "B"},
    "thumbnails.unit.kilobytes": {"ru": "КБ", "en": "KB"},
    "thumbnails.unit.megabytes": {"ru": "МБ", "en": "MB"},
    "thumbnails.unit.gigabytes": {"ru": "ГБ", "en": "GB"},

    # ---- app/config/settings.py: validation errors, shown via show_error ----
    "settings.validation.interval_must_be_positive": {
        "ru": "Интервал должен быть больше нуля.",
        "en": "The interval must be greater than zero.",
    },
    "settings.validation.min_greater_than_max": {
        "ru": "Минимальная задержка не может быть больше максимальной.",
        "en": "The minimum delay can't be greater than the maximum.",
    },
    "settings.validation.interval_too_small": {
        "ru": "Слишком маленький интервал. Минимально допустимое значение: {min} сек.",
        "en": "The interval is too small. The minimum allowed value is {min} sec.",
    },
    "settings.validation.interval_too_large": {
        "ru": "Слишком большой интервал. Максимально допустимое значение: {max} сек.",
        "en": "The interval is too large. The maximum allowed value is {max} sec.",
    },
    "settings.validation.retry_count_out_of_range": {
        "ru": "Количество повторов должно быть от {min} до {max}.",
        "en": "The retry count must be between {min} and {max}.",
    },

    # ---- app/campaign/presets.py -------------------------------------------
    "presets.untitled_name": {"ru": "Без названия", "en": "Untitled"},
    "presets.error.corrupted": {"ru": "Не удалось прочитать сохранённый шаблон (повреждённые данные)", "en": "Couldn't read the saved preset (corrupted data)"},

    # ---- app/recipients/groups.py -------------------------------------------
    "recipient_groups.untitled_name": {"ru": "Без названия", "en": "Untitled"},
    "recipient_groups.error.corrupted": {
        "ru": "Не удалось прочитать сохранённую группу (повреждённые данные)",
        "en": "Couldn't read the saved group (corrupted data)",
    },

    # ---- app/campaign/report_library.py: errors shown via show_error --------
    "report_library.error.file_not_found": {"ru": "Файл отчёта не найден: {path}", "en": "Report file not found: {path}"},
    "report_library.error.read_failed": {"ru": "Не удалось прочитать файл отчёта: {error}", "en": "Couldn't read the report file: {error}"},
    "report_library.untitled_name": {"ru": "Без названия", "en": "Untitled"},

    # ---- app/telegram/account_manager.py: shown via show_error --------------
    "account_manager.error.switch_blocked": {
        "ru": "Переключение аккаунта недоступно во время рассылки.",
        "en": "You can't switch accounts while a campaign is running.",
    },

    # ---- app/telegram/recipient_resolver.py: STATUS_LABELS, reach the Journal --
    "recipient_resolver.status.ready": {"ru": "Готов", "en": "Ready"},
    "recipient_resolver.status.invalid_format": {"ru": "Некорректный формат", "en": "Invalid format"},
    "recipient_resolver.status.user_not_found": {"ru": "Пользователь не найден", "en": "User not found"},
    "recipient_resolver.status.invalid_id": {"ru": "Некорректный Telegram ID", "en": "Invalid Telegram ID"},
    "recipient_resolver.status.cannot_message": {"ru": "Нельзя отправить сообщение", "en": "Can't send a message"},
    "recipient_resolver.status.phone_not_found": {
        "ru": (
            "Telegram не смог разрешить этот номер телефона. Пользователь "
            "может быть недоступен по номеру из-за настроек приватности "
            "Telegram."
        ),
        "en": (
            "Telegram couldn't resolve this phone number. The user may be "
            "unreachable by number due to their Telegram privacy settings."
        ),
    },
    "recipient_resolver.error.not_a_user": {
        "ru": "Получатель должен быть пользователем, а не группой/каналом",
        "en": "The recipient must be a user, not a group or channel",
    },

    # ---- app/campaign/campaign_manager.py: Journal messages -----------------
    "campaign_manager.journal.started": {"ru": "▶ Рассылка запущена: получателей {count}", "en": "▶ Campaign started: {count} recipients"},
    "campaign_manager.journal.paused": {"ru": "⏸ Рассылка поставлена на паузу", "en": "⏸ Campaign paused"},
    "campaign_manager.journal.resumed": {"ru": "▶ Рассылка возобновлена", "en": "▶ Campaign resumed"},
    "campaign_manager.journal.completed": {"ru": "✓ Рассылка завершена", "en": "✓ Campaign completed"},
    "campaign_manager.journal.stopped": {"ru": "■ Рассылка остановлена", "en": "■ Campaign stopped"},
    "campaign_manager.journal.paused_after_flood": {
        "ru": "Рассылка приостановлена после ограничения Telegram. Нажмите «Продолжить», чтобы продолжить.",
        "en": "The campaign was paused after a Telegram limit. Click “Resume” to continue.",
    },
    "campaign_manager.journal.next_send_in": {"ru": "Следующая отправка через {seconds} сек.", "en": "Next send in {seconds} sec."},
    "campaign_manager.journal.flood_wait": {
        "ru": "Telegram временно ограничил отправку. Необходимо подождать: {seconds} сек.",
        "en": "Telegram has temporarily limited sending. Waiting: {seconds} sec.",
    },
    "campaign_manager.journal.item_failed": {"ru": "✗ {recipient} — {error}", "en": "✗ {recipient} — {error}"},
    "campaign_manager.journal.item_sent": {"ru": "✓ {recipient} — отправлено", "en": "✓ {recipient} — sent"},
    "campaign_manager.journal.critical_error": {"ru": "✗ Критическая ошибка аккаунта: {error}", "en": "✗ Critical account error: {error}"},
    "campaign_manager.journal.retrying": {
        "ru": "… повтор {attempt}/{max_attempts} для {recipient} через {backoff} сек.",
        "en": "… retry {attempt}/{max_attempts} for {recipient} in {backoff} sec.",
    },
    "campaign_manager.journal.network_error": {"ru": "✗ {recipient} — сетевая ошибка", "en": "✗ {recipient} — network error"},
    "campaign_manager.journal.unexpected_error": {
        "ru": "✗ {recipient} — непредвиденная ошибка: {error}",
        "en": "✗ {recipient} — unexpected error: {error}",
    },
    "campaign_manager.error.user_not_found": {"ru": "пользователь не найден", "en": "user not found"},
    "campaign_manager.error.user_blocked": {"ru": "пользователь заблокировал аккаунт", "en": "the user has blocked this account"},
    "campaign_manager.error.invalid_id": {"ru": "некорректный Telegram ID", "en": "invalid Telegram ID"},
    "campaign_manager.error.write_forbidden": {"ru": "отправка сообщения запрещена", "en": "sending a message is not allowed"},
    "campaign_manager.error.privacy_restricted": {"ru": "Telegram ограничил возможность отправки", "en": "Telegram has restricted sending"},
    "campaign_manager.error.account_unavailable": {"ru": "Аккаунт недоступен", "en": "Account unavailable"},
    "campaign_manager.error.network": {"ru": "Сетевая ошибка", "en": "Network error"},
    "campaign_manager.error.unexpected": {"ru": "Непредвиденная ошибка", "en": "Unexpected error"},
    "campaign_manager.error.recipient_unavailable": {"ru": "Получатель недоступен", "en": "Recipient unavailable"},
}

PLURALS: Dict[str, Dict[str, Dict[str, str]]] = {
    "recipient_widget.recipient_count": {
        "ru": {"one": "{n} получатель", "few": "{n} получателя", "many": "{n} получателей"},
        "en": {"one": "{n} recipient", "other": "{n} recipients"},
    },
    "dialogs.start_campaign.message": {
        "ru": {
            "one": "Сообщение будет отправлено {n} получателю. Продолжить?",
            "few": "Сообщение будет отправлено {n} получателям. Продолжить?",
            "many": "Сообщение будет отправлено {n} получателям. Продолжить?",
        },
        "en": {
            "one": "The message will be sent to {n} recipient. Continue?",
            "other": "The message will be sent to {n} recipients. Continue?",
        },
    },
}
