""""Lists ▾" and "Templates ▾": one compact menu button each (save the
current one, a Load submenu, a Delete submenu) instead of a label, combo
box and three buttons -- that row wrapped at the default window width.
Internally they are still recipient groups and presets; saved data is
read as is. The same menus are in the Campaign Wizard and act on the
wizard's own boxes there."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QComboBox

from app.campaign import presets
from app.database.database import Database
from app.i18n import LANGUAGE_EN, LANGUAGE_RU, set_language, tr
from app.recipients import groups
from app.security.secure_storage import SecureStorage
from app.ui.main_window import MainWindow


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


def _action(menu, name):
    for action in menu.actions():
        if action.text() == name:
            return action
    raise AssertionError(f"{name!r} not in {[a.text() for a in menu.actions()]}")


async def test_the_old_combo_rows_are_gone_and_the_menus_sit_in_the_card_headers(qapp, tmp_path):
    window = _make_window(tmp_path)
    for card in (window._recipients_card, window._message_card):
        assert card.findChildren(QComboBox) == []
    assert window._lists_menu.parentWidget() is window._recipients_card
    assert window._templates_menu.parentWidget() is window._message_card
    window.show()
    QApplication.processEvents()
    # Above the box, on the title line -- not one more row under it.
    assert window._lists_menu.geometry().bottom() < window._recipient_widget.parentWidget().geometry().top()
    assert window._lists_menu.text() == tr("main_window.lists.button")
    assert window._lists_menu.toolTip() == tr("main_window.lists.tooltip")
    assert window._templates_menu.text() == tr("main_window.templates.button")
    assert window._templates_menu.toolTip() == tr("main_window.templates.tooltip")


async def test_menu_lists_what_is_saved_for_load_and_delete(qapp, tmp_path):
    window = _make_window(tmp_path)
    groups.save_group(window._group_repo, "Customers", "@a", {})
    groups.save_group(window._group_repo, "Partners", "@b", {})
    window._refresh_saved_menus()

    menu = window._lists_menu
    assert menu.save_action.text() == tr("main_window.lists.save_action")
    assert menu.load_menu.isEnabled() and menu.delete_menu.isEnabled()
    assert sorted(a.text() for a in menu.load_menu.actions()) == ["Customers", "Partners"]
    assert sorted(a.text() for a in menu.delete_menu.actions()) == ["Customers…", "Partners…"]
    assert menu.empty_action is None


async def test_menus_follow_the_language(qapp, tmp_path):
    window = _make_window(tmp_path)
    presets.save_preset(window._preset_repo, "Weekly", "text", [], [])
    window._refresh_saved_menus()
    try:
        set_language(LANGUAGE_EN)
        window.retranslate_ui()
        assert window._lists_menu.text() == "Lists"
        assert window._templates_menu.text() == "Templates"
        assert window._templates_menu.save_action.text() == "Save current message…"
        assert [a.text() for a in window._templates_menu.load_menu.actions()] == ["Weekly"]
        assert window._lists_menu.empty_action.text() == "No saved lists yet — nothing to load or delete"
        set_language(LANGUAGE_RU)
        window.retranslate_ui()
        assert window._lists_menu.text() == "Списки"
        assert window._templates_menu.text() == "Шаблоны"
    finally:
        set_language(LANGUAGE_RU)


async def test_saved_names_are_called_lists_and_templates_in_the_ui(qapp):
    try:
        set_language(LANGUAGE_RU)
        assert tr("main_window.dialogs.save_group_title") == "Сохранить список"
        assert tr("main_window.dialogs.delete_group_title") == "Удалить список?"
        set_language(LANGUAGE_EN)
        assert tr("main_window.dialogs.save_group_title") == "Save list"
        assert tr("main_window.dialogs.save_preset_title") == "Save template"
        assert "preset" not in tr("main_window.dialogs.delete_preset_message", name="x").lower()
    finally:
        set_language(LANGUAGE_RU)


async def test_wizard_has_both_menus_and_loads_a_list_into_its_own_box(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._recipient_widget.set_text("@page_only")
    groups.save_group(window._group_repo, "Customers", "@ivan_test", {"username:ivan_test": "Ivan"})
    window._refresh_saved_menus()
    wizard = window._build_campaign_wizard()
    try:
        assert window._wizard_lists_menu.item_names() == ["Customers"]
        _action(window._wizard_lists_menu.load_menu, "Customers").trigger()
        assert wizard.recipient_widget.get_text() == "@ivan_test"
        assert wizard.recipient_widget.name_overrides() == {"username:ivan_test": "Ivan"}
        assert window._recipient_widget.get_text() == "@page_only"
    finally:
        wizard.reject()


async def test_wizard_loads_a_template_into_its_own_message_attachments_and_interval(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "page text"
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    presets.save_preset(window._preset_repo, "Timed", "Hi {name}", [], [photo], 45, 90)
    window._refresh_saved_menus()
    settings_before = window._service.settings_repository.load_app_settings()
    wizard = window._build_campaign_wizard()
    try:
        _action(window._wizard_templates_menu.load_menu, "Timed").trigger()
        assert wizard.message()[0] == "Hi {name}"
        assert [a.path for a in wizard.attachments_widget.get_attachments()] == [photo]
        assert wizard.interval() == (45, 90)
        # The page and the saved settings are untouched until the wizard
        # itself saves its sending options.
        assert window._message_text == "page text"
        assert window._attachments_widget.get_attachments() == []
        settings_after = window._service.settings_repository.load_app_settings()
        assert (settings_after.min_delay_seconds, settings_after.max_delay_seconds) == (
            settings_before.min_delay_seconds,
            settings_before.max_delay_seconds,
        )
    finally:
        wizard.reject()


async def test_wizard_saves_its_own_message_and_both_menus_update(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "page text"
    wizard = window._build_campaign_wizard()
    try:
        wizard.set_message("wizard text", [])
        wizard.set_interval(20, 40)
        with patch("app.ui.main_window.QInputDialog") as mock_dialog:
            mock_dialog.getText.return_value = ("From wizard", True)
            window._wizard_templates_menu.save_action.trigger()
        # Asked over the wizard, not behind it.
        assert mock_dialog.getText.call_args[0][0] is wizard
        (saved,) = presets.list_presets(window._preset_repo)
        loaded = presets.load_preset(saved)
        assert loaded.message_text == "wizard text"
        assert (loaded.min_delay_seconds, loaded.max_delay_seconds) == (20, 40)
        assert window._templates_menu.item_names() == ["From wizard"]
        assert window._wizard_templates_menu.item_names() == ["From wizard"]
    finally:
        wizard.reject()


async def test_wizard_delete_asks_over_the_wizard(qapp, tmp_path):
    window = _make_window(tmp_path)
    groups.save_group(window._group_repo, "Doomed", "@a", {})
    window._refresh_saved_menus()
    wizard = window._build_campaign_wizard()
    try:
        with patch("app.ui.main_window.confirm_delete_group", return_value=True) as confirm:
            _action(window._wizard_lists_menu.delete_menu, "Doomed…").trigger()
        assert confirm.call_args[0][0] is wizard
        assert groups.list_groups(window._group_repo) == []
        assert window._lists_menu.item_names() == []
        assert not window._wizard_lists_menu.load_menu.isEnabled()
    finally:
        wizard.reject()
