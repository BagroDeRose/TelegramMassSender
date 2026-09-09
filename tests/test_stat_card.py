"""Tests for the Results-page StatCard tile (app.ui.stat_card)."""
from __future__ import annotations

from app.ui.stat_card import StatCard


def test_default_value_is_zero(qapp):
    card = StatCard("Всего")
    assert card._value_label.text() == "0"


def test_set_value_updates_label(qapp):
    card = StatCard("Успешно", variant="success")
    card.set_value(121)
    assert card._value_label.text() == "121"


def test_variant_sets_dynamic_property(qapp):
    card = StatCard("Ошибок", variant="error")
    assert card._value_label.property("variant") == "error"


def test_no_variant_leaves_property_unset(qapp):
    card = StatCard("Всего")
    assert card._value_label.property("variant") in (None, "")


def test_restyle_does_not_raise(qapp):
    card = StatCard("Пропущено", variant="warning")
    card.restyle()
