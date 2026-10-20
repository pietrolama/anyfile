"""Translations: English in the code, other languages from gettext .po files.

The .po files in anyfile/locale/ are read directly at runtime, so no compilation
step is needed for development installs, the .deb package or Windows.

    from anyfile.i18n import _, ngettext, N_

    _("Compress")                         # translated now
    ngettext("{n} file", "{n} files", n)  # plural forms
    N_("Lossy compression")               # marked for extraction, translated later with _()
"""

from __future__ import annotations

import locale
import os
import re
import sys
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locale"

_messages: dict[str, str] = {}
_plurals: dict[str, list[str]] = {}
_plural_rule = lambda n: 0 if n == 1 else 1  # noqa: E731 — English, and the default
_language: str | None = None


def N_(message: str) -> str:
    """Marks a string for translation without translating it (module-level constants)."""
    return message


def _(message: str) -> str:
    if _language is None:
        set_language(detect_language())
    return _messages.get(message) or message


def ngettext(singular: str, plural: str, n: int) -> str:
    if _language is None:
        set_language(detect_language())
    forms = _plurals.get(singular)
    if forms:
        index = _plural_rule(n)
        if index < len(forms) and forms[index]:
            return forms[index]
    return singular if n == 1 else plural


def language() -> str:
    if _language is None:
        set_language(detect_language())
    return _language or "en"


# Languages that write 1,5 instead of 1.5.
_DECIMAL_COMMA = {"it", "de", "fr", "es", "pt", "nl", "pl", "cs", "ru", "sv", "da", "fi", "tr"}


def format_number(value: float, decimals: int = 1) -> str:
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if language() in _DECIMAL_COMMA else text


def available_languages() -> list[str]:
    return ["en", *sorted(p.stem for p in LOCALE_DIR.glob("*.po"))]


def detect_language() -> str:
    """First language from the environment that has a translation, otherwise English."""
    candidates: list[str] = []
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            # LANGUAGE may hold a preference list: "it:en".
            candidates.extend(value.split(":"))
            break
    if not candidates and sys.platform == "win32":
        candidates.append(_windows_ui_language())
    available = set(available_languages())
    for candidate in candidates:
        code = candidate.split(".")[0].split("@")[0].split("_")[0].lower()
        if code in ("c", "posix"):
            return "en"
        if code in available:
            return code
    return "en"


def _windows_ui_language() -> str:
    try:
        import ctypes

        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lcid, "en")
    except (AttributeError, OSError):
        return "en"


def set_language(code: str) -> None:
    global _language, _plural_rule
    _messages.clear()
    _plurals.clear()
    _plural_rule = lambda n: 0 if n == 1 else 1  # noqa: E731
    _language = code
    path = LOCALE_DIR / f"{code}.po"
    if code != "en" and path.is_file():
        messages, plurals, header = parse_po(path.read_text(encoding="utf-8"))
        _messages.update(messages)
        _plurals.update(plurals)
        _plural_rule = _plural_rule_from(header)


# --- .po files ----------------------------------------------------------------------

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(text: str) -> str:
    body = text.strip()[1:-1]
    return re.sub(r'\\(.)', lambda m: _ESCAPES.get(m.group(1), m.group(1)), body)


def parse_po(text: str) -> tuple[dict[str, str], dict[str, list[str]], str]:
    """Reads a .po file: (messages, plural messages, header). Fuzzy entries are skipped."""
    messages: dict[str, str] = {}
    plurals: dict[str, list[str]] = {}
    header = ""

    for block in re.split(r"\n\s*\n", text):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if not lines or any(line.startswith("#,") and "fuzzy" in line for line in lines):
            continue
        fields: dict[str, str] = {}
        current = None
        for line in lines:
            if line.startswith("#"):
                continue
            if line.startswith('"'):
                if current is not None:
                    fields[current] += _unquote(line)
                continue
            key, _sep, value = line.partition(" ")
            current = key
            fields[current] = _unquote(value)
        msgid = fields.get("msgid")
        if msgid is None:
            continue
        if msgid == "":
            header = fields.get("msgstr", "")
        elif "msgid_plural" in fields:
            forms = [fields[k] for k in sorted(f for f in fields if f.startswith("msgstr["))]
            if any(forms):
                plurals[msgid] = forms
        elif fields.get("msgstr"):
            messages[msgid] = fields["msgstr"]
    return messages, plurals, header


def _plural_rule_from(header: str):
    """Supports the common two-form rules: “n != 1” (Italian, German…) and “n > 1” (French)."""
    match = re.search(r"plural\s*=\s*\(?\s*n\s*(!=\s*1|>\s*1)\s*\)?", header)
    if match and match.group(1).replace(" ", "") == ">1":
        return lambda n: 0 if n <= 1 else 1
    return lambda n: 0 if n == 1 else 1
