#!/usr/bin/env bash
# Installa ANYFILE per l'utente corrente (nessun privilegio di amministratore).
#   - ambiente virtuale in ~/.local/share/anyfile/venv
#   - comando ~/.local/bin/anyfile
#   - voce nel menu delle applicazioni
#   - azione "Converti con ANYFILE" nel menu contestuale di Dolphin
# Uso: packaging/install-user.sh [--uninstall]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$DATA/anyfile/venv"
BIN="$HOME/.local/bin/anyfile"
SERVICEMENU="$DATA/kio/servicemenus/anyfile.desktop"
APPENTRY="$DATA/applications/anyfile.desktop"

refresh_kde() {
    if command -v kbuildsycoca6 >/dev/null; then kbuildsycoca6 >/dev/null 2>&1 || true
    elif command -v kbuildsycoca5 >/dev/null; then kbuildsycoca5 >/dev/null 2>&1 || true
    fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$BIN" "$SERVICEMENU" "$APPENTRY"
    rm -rf "$DATA/anyfile"
    refresh_kde
    echo "ANYFILE rimosso."
    exit 0
fi

echo "→ Ambiente Python in $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
# -e: le modifiche al codice sorgente sono subito attive (fase di sviluppo).
"$VENV/bin/pip" install --quiet -e "$ROOT"

echo "→ Comando $BIN"
mkdir -p "$(dirname "$BIN")"
ln -sf "$VENV/bin/anyfile" "$BIN"

# Dolphin non eredita sempre il PATH della shell: si usa il percorso assoluto.
echo "→ Menu contestuale di Dolphin"
mkdir -p "$(dirname "$SERVICEMENU")"
sed "s|^Exec=anyfile |Exec=$BIN |" "$ROOT/packaging/dolphin/anyfile.desktop" > "$SERVICEMENU"
chmod +x "$SERVICEMENU"  # KDE 6 ignora i service menu utente non eseguibili

echo "→ Menu delle applicazioni"
mkdir -p "$(dirname "$APPENTRY")"
sed "s|^Exec=anyfile |Exec=$BIN |" "$ROOT/packaging/anyfile.desktop" > "$APPENTRY"

refresh_kde

echo
"$BIN" engines
echo
echo "Fatto. In Dolphin: tasto destro su un file → «Converti con ANYFILE»."
