#!/usr/bin/env bash
# Keeps the translations in step with the code.
#   scripts/i18n.sh          extract the strings and update every .po file
#   scripts/i18n.sh new LL   start a translation for language LL (e.g. de, fr, es)
# Needs the gettext tools (sudo apt install gettext). Strings marked with _(), N_()
# and ngettext() in src/anyfile are extracted; .po files are read directly at runtime.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCALE="$ROOT/src/anyfile/locale"
POT="$LOCALE/anyfile.pot"

cd "$ROOT"
xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=N_ --keyword=ngettext:1,2 \
    --add-comments=TRANSLATORS: --package-name=anyfile \
    --msgid-bugs-address="https://github.com/pietrolama/anyfile/issues" \
    -o "$POT" $(find src/anyfile -name "*.py" | sort)

if [[ "${1:-}" == "new" ]]; then
    msginit --no-translator --locale="$2" --input="$POT" --output-file="$LOCALE/$2.po"
    echo "Created $LOCALE/$2.po: translate the empty msgstr entries."
    exit 0
fi

for po in "$LOCALE"/*.po; do
    msgmerge --quiet --update --backup=none "$po" "$POT"
    printf '%s: ' "$(basename "$po")"
    msgfmt --check --statistics -o /dev/null "$po"
done
