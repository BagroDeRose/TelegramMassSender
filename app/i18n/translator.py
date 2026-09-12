"""Minimal translation engine: a key -> {language: template} lookup plus a
small Russian/English pluralization helper, following the same
active-state pattern already established by app.ui.theme
(set_active_theme/get_active_theme/current_tokens) rather than inventing a
new one or pulling in a full i18n framework (gettext, Qt Linguist .ts/.qm
+ pyside6-lupdate/-lrelease) this app has no other use for.

Deliberately NOT app/ui/i18n.py: app/config/settings.py's own
SettingsValidationError messages are user-facing (shown verbatim via
show_error()) and app/config must not import from app/ui -- a top-level
package next to app/logging is the natural home for a concern every layer
may need to reach into.
"""
from __future__ import annotations

from typing import Dict

from app.i18n.strings import PLURALS, STRINGS

LANGUAGE_RU = "ru"
LANGUAGE_EN = "en"
VALID_LANGUAGES = (LANGUAGE_RU, LANGUAGE_EN)
DEFAULT_LANGUAGE = LANGUAGE_RU

LANGUAGE_LABELS: Dict[str, str] = {
    LANGUAGE_RU: "Русский",
    LANGUAGE_EN: "English",
}

_active_language = DEFAULT_LANGUAGE


def _normalize(language: str) -> str:
    return language if language in VALID_LANGUAGES else DEFAULT_LANGUAGE


def set_language(language: str) -> None:
    global _active_language
    _active_language = _normalize(language)


def get_language() -> str:
    return _active_language


def tr(key: str, **kwargs: object) -> str:
    """Look up `key` in the STRINGS catalog for the active language,
    falling back to Russian (the app's original, always-complete
    language) if the active language is missing that specific key, and
    to the key itself if the key doesn't exist in the catalog at all --
    a missing translation must never crash the UI, and showing the raw
    key makes the gap immediately visible instead of silently blank."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    template = entry.get(_active_language) or entry.get(DEFAULT_LANGUAGE) or key
    # Always call format(), even with no kwargs -- some templates use a
    # doubled brace ("{{name}}") to show a literal "{name}" to the user
    # (e.g. explaining the {name} placeholder itself), which only
    # collapses to a single brace via an actual format() call.
    return template.format(**kwargs)


def _plural_form_ru(n: int) -> str:
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        return "one"
    if n_abs % 10 in (2, 3, 4) and n_abs % 100 not in (12, 13, 14):
        return "few"
    return "many"


def _plural_form_en(n: int) -> str:
    return "one" if abs(n) == 1 else "other"


_PLURAL_FORM_FOR_LANGUAGE = {
    LANGUAGE_RU: _plural_form_ru,
    LANGUAGE_EN: _plural_form_en,
}


def trn(key: str, n: int, **kwargs: object) -> str:
    """Pluralized lookup in the PLURALS catalog. Russian has three
    grammatical plural forms (one/few/many, e.g. получатель/получателя/
    получателей); English has two (one/other). Each catalog entry carries
    exactly the forms its own language needs -- see app.i18n.strings.

    `n` is both the count that picks the plural form AND automatically
    available to the template as `{n}` -- do not also pass n= via
    kwargs."""
    entry = PLURALS.get(key)
    if entry is None:
        return key
    language = _active_language if _active_language in entry else DEFAULT_LANGUAGE
    forms = entry.get(language) or entry.get(DEFAULT_LANGUAGE) or {}
    form = _PLURAL_FORM_FOR_LANGUAGE[language](n)
    template = forms.get(form) or next(iter(forms.values()), key)
    return template.format(n=n, **kwargs)
