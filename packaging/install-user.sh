#!/usr/bin/env bash
# Installs ANYFILE for the current user (no administrator rights needed).
#   - virtual environment in ~/.local/share/anyfile/venv
#   - command ~/.local/bin/anyfile
#   - entry in the application menu
#   - "Convert with ANYFILE" action in the Dolphin context menu
# Usage: packaging/install-user.sh [--uninstall]
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
    echo "ANYFILE removed."
    exit 0
fi

if dpkg-query -W -f='${Status}' anyfile 2>/dev/null | grep -q "install ok installed"; then
    echo "ANYFILE is already installed as a system package (.deb)." >&2
    echo "Two installations would show two entries in the Dolphin menu: remove the" >&2
    echo "package first (sudo apt remove anyfile) or use only that one." >&2
    exit 1
fi

echo "→ Python environment in $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
# -e: changes to the source code take effect immediately (development).
"$VENV/bin/pip" install --quiet -e "$ROOT"

echo "→ Command $BIN"
mkdir -p "$(dirname "$BIN")"
ln -sf "$VENV/bin/anyfile" "$BIN"

# Dolphin does not always inherit the shell PATH: use the absolute path.
echo "→ Dolphin context menu"
mkdir -p "$(dirname "$SERVICEMENU")"
sed "s|^Exec=anyfile |Exec=$BIN |" "$ROOT/packaging/dolphin/anyfile.desktop" > "$SERVICEMENU"
chmod +x "$SERVICEMENU"  # KDE 6 ignores user service menus that are not executable

echo "→ Application menu"
mkdir -p "$(dirname "$APPENTRY")"
sed "s|^Exec=anyfile |Exec=$BIN |" "$ROOT/packaging/anyfile.desktop" > "$APPENTRY"

refresh_kde

echo
"$BIN" engines
echo
echo "Done. In Dolphin: right-click a file → “Convert with ANYFILE”."
