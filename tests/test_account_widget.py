"""Tests for app.ui.account_widget.AccountWidget -- no prior dedicated
coverage existed for this widget in isolation (tests/test_account_switching.py
covers MainWindow-level wiring, not the widget's own rendering logic).
Written alongside the v1.8 Accounts stage: local alias rename, phone-number
display, and the resulting card layout changes.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from app.database.models import Account
from app.telegram.account_manager import AccountStatus
from app.ui.account_widget import AccountWidget


def _make_account(
    id=1,
    phone="+70001112233",
    telegram_user_id=None,
    username=None,
    display_name=None,
    local_alias=None,
    session_name="s",
) -> Account:
    return Account(
        id=id,
        phone=phone,
        telegram_user_id=telegram_user_id,
        username=username,
        display_name=display_name,
        local_alias=local_alias,
        session_name=session_name,
        created_at="now",
        last_used_at=None,
    )


def _status(account, is_authorized=True, needs_reauth=False, connection_error=False) -> AccountStatus:
    return AccountStatus(account=account, is_authorized=is_authorized, needs_reauth=needs_reauth, connection_error=connection_error)


def _card_name_text(widget, index=0) -> str:
    card = widget._cards[index]
    label = card.findChild(QLabel, "accountName")
    return label.text()


def _card_meta_texts(widget, index=0):
    card = widget._cards[index]
    return [label.text() for label in card.findChildren(QLabel, "accountMeta")]


def test_empty_state_shown_with_no_accounts(qapp):
    widget = AccountWidget()
    widget.set_accounts([])
    # isHidden() reflects the widget's own setVisible() call regardless of
    # whether the (never-.show()'d) top-level window is actually on
    # screen -- isVisible() would be False regardless of state here.
    assert widget._empty_label.isHidden() is False
    assert widget._cards == []


def test_card_shows_phone_as_name_when_no_alias_or_display_name(qapp):
    account = _make_account(phone="+70001112233")
    widget = AccountWidget()
    widget.set_accounts([_status(account)])
    assert _card_name_text(widget) == "+70001112233"
    # No separate phone meta line -- it's already the title, not repeated.
    assert "+70001112233" not in _card_meta_texts(widget)


def test_card_prefers_telegram_display_name_over_phone(qapp):
    account = _make_account(phone="+70001112233", display_name="Ivan Petrov")
    widget = AccountWidget()
    widget.set_accounts([_status(account)])
    assert _card_name_text(widget) == "Ivan Petrov"
    # Phone must still be visible somewhere once it's no longer the title.
    assert "+70001112233" in _card_meta_texts(widget)


def test_card_prefers_local_alias_over_telegram_display_name(qapp):
    account = _make_account(phone="+70001112233", display_name="Ivan Petrov", local_alias="Work account")
    widget = AccountWidget()
    widget.set_accounts([_status(account)])
    assert _card_name_text(widget) == "Work account"
    assert "+70001112233" in _card_meta_texts(widget)


def test_card_shows_username_when_present(qapp):
    account = _make_account(username="ivanp", display_name="Ivan Petrov")
    widget = AccountWidget()
    widget.set_accounts([_status(account)])
    assert "@ivanp" in _card_meta_texts(widget)


def test_card_shows_no_username_line_when_absent(qapp):
    account = _make_account(username=None, display_name="Ivan Petrov")
    widget = AccountWidget()
    widget.set_accounts([_status(account)])
    assert not any(text.startswith("@") for text in _card_meta_texts(widget))


def test_rename_button_emits_rename_requested_with_the_account_id(qapp):
    account = _make_account(id=7)
    widget = AccountWidget()
    widget.set_accounts([_status(account)])
    requests = []
    widget.rename_requested.connect(requests.append)

    widget._rename_buttons[0].click()

    assert requests == [7]


def test_rename_buttons_disabled_while_switching(qapp):
    account = _make_account()
    widget = AccountWidget()
    widget.set_accounts([_status(account)])

    widget.set_enabled_switching(False)
    assert widget._rename_buttons[0].isEnabled() is False

    widget.set_enabled_switching(True)
    assert widget._rename_buttons[0].isEnabled() is True


def test_apply_theme_rebuilds_cards_preserving_alias_display(qapp):
    account = _make_account(local_alias="Work account")
    widget = AccountWidget()
    widget.set_accounts([_status(account)])

    widget.apply_theme()

    assert _card_name_text(widget) == "Work account"


def test_multiple_accounts_each_get_independent_rename_buttons(qapp):
    a = _make_account(id=1, phone="+70001112233")
    b = _make_account(id=2, phone="+70004445566")
    widget = AccountWidget()
    widget.set_accounts([_status(a), _status(b)])
    requests = []
    widget.rename_requested.connect(requests.append)

    widget._rename_buttons[1].click()

    assert requests == [2]


def test_rename_and_delete_buttons_have_accessible_names(qapp):
    # Both are icon-only (no visible button text), so a screen reader has
    # nothing else to announce for them without an explicit accessible
    # name -- a tooltip alone is a separate accessibility role, not
    # automatically used as the name.
    account = _make_account()
    widget = AccountWidget()
    widget.set_accounts([_status(account)])

    assert widget._rename_buttons[0].accessibleName()
    assert widget._delete_buttons[0].accessibleName()
