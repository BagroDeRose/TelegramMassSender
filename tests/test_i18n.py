"""Tests for the translation engine (app/i18n) -- lookup, fallback,
pluralization, and catalog completeness (every registered key has both a
Russian and an English entry, per the roadmap's "presence of translations
for all registered UI strings" requirement).
"""
from __future__ import annotations

import pytest

from app.i18n import LANGUAGE_EN, LANGUAGE_RU, get_language, set_language, tr, trn
from app.i18n.strings import PLURALS, STRINGS


@pytest.fixture(autouse=True)
def _reset_language():
    # Every test starts from the same known state and leaves it as it
    # found it, regardless of what an individual test switches to --
    # module-level language state would otherwise leak between tests.
    original = get_language()
    yield
    set_language(original)


def test_default_language_is_russian():
    assert get_language() == LANGUAGE_RU


def test_set_language_changes_active_language():
    set_language(LANGUAGE_EN)
    assert get_language() == LANGUAGE_EN


def test_set_language_normalizes_an_invalid_value_to_the_default():
    set_language("fr")
    assert get_language() == LANGUAGE_RU


def test_tr_returns_the_active_languages_text():
    set_language(LANGUAGE_RU)
    assert tr("main_window.status.ready") == "Готово"
    set_language(LANGUAGE_EN)
    assert tr("main_window.status.ready") == "Ready"


def test_tr_formats_placeholders():
    set_language(LANGUAGE_EN)
    assert tr("main_window.start_error.missing_files", names="a.pdf") == "Attached file(s) not found: a.pdf"


def test_tr_unknown_key_returns_the_key_itself_rather_than_crashing():
    assert tr("this.key.does.not.exist") == "this.key.does.not.exist"


def test_tr_falls_back_to_russian_if_active_language_is_missing_the_key(monkeypatch):
    monkeypatch.setitem(STRINGS, "test.partial_key", {"ru": "Только по-русски"})
    set_language(LANGUAGE_EN)
    assert tr("test.partial_key") == "Только по-русски"


def test_tr_handles_a_doubled_brace_showing_a_literal_placeholder():
    # main_window.campaign_page.name_placeholder_hint intentionally shows
    # the user the literal text "{name}" (explaining the real
    # placeholder), which needs "{{name}}" in the template to survive a
    # real .format() call untouched.
    assert "{name}" in tr("main_window.campaign_page.name_placeholder_hint")


@pytest.mark.parametrize(
    "n,expected",
    [(1, "1 получатель"), (2, "2 получателя"), (4, "4 получателя"), (5, "5 получателей"), (11, "11 получателей"), (21, "21 получатель")],
)
def test_trn_russian_plural_forms(n, expected):
    set_language(LANGUAGE_RU)
    assert trn("recipient_widget.recipient_count", n) == expected


@pytest.mark.parametrize("n,expected", [(1, "1 recipient"), (2, "2 recipients"), (0, "0 recipients")])
def test_trn_english_plural_forms(n, expected):
    set_language(LANGUAGE_EN)
    assert trn("recipient_widget.recipient_count", n) == expected


def test_trn_unknown_key_returns_the_key_itself():
    assert trn("this.plural.does.not.exist", 3) == "this.plural.does.not.exist"


def test_trn_extra_kwargs_are_available_to_the_template():
    set_language(LANGUAGE_RU)
    text = trn("dialogs.start_campaign.message", 3)
    assert "3" in text


# ---- catalog completeness --------------------------------------------------


def test_every_string_entry_has_both_languages():
    missing = {key: set(STRINGS[key].keys()) for key in STRINGS if set(STRINGS[key].keys()) != {LANGUAGE_RU, LANGUAGE_EN}}
    assert missing == {}


def test_every_string_entry_has_non_empty_text_for_both_languages():
    empty = [key for key, entry in STRINGS.items() if not entry.get(LANGUAGE_RU) or not entry.get(LANGUAGE_EN)]
    assert empty == []


def test_every_plural_entry_has_both_languages():
    missing = {key: set(PLURALS[key].keys()) for key in PLURALS if set(PLURALS[key].keys()) != {LANGUAGE_RU, LANGUAGE_EN}}
    assert missing == {}


def test_every_russian_plural_entry_has_all_three_forms():
    incomplete = {key: entry[LANGUAGE_RU] for key, entry in PLURALS.items() if set(entry[LANGUAGE_RU].keys()) != {"one", "few", "many"}}
    assert incomplete == {}


def test_every_english_plural_entry_has_both_forms():
    incomplete = {key: entry[LANGUAGE_EN] for key, entry in PLURALS.items() if set(entry[LANGUAGE_EN].keys()) != {"one", "other"}}
    assert incomplete == {}


def test_no_key_appears_in_both_strings_and_plurals():
    # A key belongs to exactly one catalog -- tr() and trn() look in
    # different dicts, so an accidental key collision would silently pick
    # whichever dict its own call happens to read from.
    assert set(STRINGS.keys()).isdisjoint(set(PLURALS.keys()))


def test_string_templates_with_placeholders_are_valid_format_strings():
    # A template with mismatched/malformed {braces} would raise at format()
    # time, at the exact moment a user triggers that specific code path --
    # this catches it for every entry, once, up front.
    for key, entry in STRINGS.items():
        for language, template in entry.items():
            try:
                template.format(**{})
            except (KeyError, IndexError):
                pass  # a real placeholder needing a kwarg -- expected, not malformed
            except ValueError as exc:
                pytest.fail(f"Malformed format string for {key!r} [{language}]: {exc!r}")
