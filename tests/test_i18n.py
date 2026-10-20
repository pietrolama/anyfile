"""Translations: loading, plural forms, numbers, and the Italian catalogue kept complete."""

import re
import shutil
import subprocess

import pytest

from anyfile import i18n
from anyfile.i18n import _, format_number, ngettext, parse_po, set_language
from anyfile.models.conversion import Quality

PLACEHOLDER = re.compile(r"\{[a-z_]*\}")


def test_english_is_the_source_language():
    set_language("en")
    assert _("Compress") == "Compress"
    assert ngettext("{n} file", "{n} files", 2).format(n=2) == "2 files"
    assert format_number(926.8) == "926.8"


def test_italian_translation():
    set_language("it")
    assert _("Compress") == "Comprimi"
    assert Quality.SMALL.label == "File più leggero"
    assert ngettext("{n} file converted", "{n} files converted", 1).format(n=1) == "1 file convertito"
    assert ngettext("{n} file converted", "{n} files converted", 3).format(n=3) == "3 file convertiti"
    assert format_number(926.8) == "926,8"
    # Strings without a translation fall back to English.
    assert _("A string nobody translated") == "A string nobody translated"


@pytest.mark.parametrize("env,expected", [
    ({"LANGUAGE": "it:en"}, "it"),
    ({"LANG": "it_IT.UTF-8"}, "it"),
    ({"LANG": "de_DE.UTF-8"}, "en"),   # no German translation yet
    ({"LC_ALL": "C"}, "en"),
    ({"LANGUAGE": "fr:it"}, "it"),     # first available language in the preference list
])
def test_language_detection(monkeypatch, env, expected):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert i18n.detect_language() == expected


def test_po_parser_handles_multiline_plurals_and_fuzzy():
    messages, plurals, header = parse_po('''
msgid ""
msgstr "Plural-Forms: nplurals=2; plural=(n != 1);\\n"

msgid "Two\\n"
"lines"
msgstr "Due\\nrighe"

#, fuzzy
msgid "Guess"
msgstr "Indovinello"

msgid "{n} file"
msgid_plural "{n} files"
msgstr[0] "{n} file"
msgstr[1] "{n} file"
''')
    assert messages == {"Two\nlines": "Due\nrighe"}
    assert plurals == {"{n} file": ["{n} file", "{n} file"]}
    assert "nplurals=2" in header


def _catalogue(code):
    return parse_po((i18n.LOCALE_DIR / f"{code}.po").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", [p for p in i18n.available_languages() if p != "en"])
def test_translations_keep_the_placeholders(code):
    messages, plurals, _header = _catalogue(code)
    for source, translation in messages.items():
        assert set(PLACEHOLDER.findall(source)) == set(PLACEHOLDER.findall(translation)), source
    for source, forms in plurals.items():
        for form in forms:
            assert set(PLACEHOLDER.findall(form)) <= set(PLACEHOLDER.findall(source)) | {"{n}"}, source


@pytest.mark.skipif(not shutil.which("xgettext"), reason="xgettext not installed")
@pytest.mark.parametrize("code", [p for p in i18n.available_languages() if p != "en"])
def test_every_string_in_the_code_is_translated(code, tmp_path):
    pot = tmp_path / "anyfile.pot"
    sources = sorted(str(p) for p in i18n.LOCALE_DIR.parent.rglob("*.py"))
    subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=_", "--keyword=N_",
                    "--keyword=ngettext:1,2", "-o", str(pot), *sources], check=True)
    wanted, wanted_plurals, _header = parse_po(pot.read_text(encoding="utf-8").replace('msgstr ""', 'msgstr "x"')
                                               .replace('msgstr[0] ""', 'msgstr[0] "x"'))
    messages, plurals, _header = _catalogue(code)
    missing = [m for m in wanted if m not in messages] + [m for m in wanted_plurals if m not in plurals]
    assert not missing, f"untranslated in {code}.po (run scripts/i18n.sh): {missing}"
