#!/usr/bin/env bash
# Costruisce il pacchetto Debian/Ubuntu di ANYFILE in dist/.
# Uso: packaging/deb/build.sh            (versione da pyproject.toml)
#      VERSION=0.2.1 packaging/deb/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${VERSION:-$(python3 -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1],"rb"))["project"]["version"])' "$ROOT/pyproject.toml")}"
PKG="anyfile_${VERSION}_all"
STAGE="$ROOT/build/deb/$PKG"
PYDIR="$STAGE/usr/lib/python3/dist-packages"

rm -rf "$STAGE"
mkdir -p "$PYDIR" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/kio/servicemenus" "$STAGE/usr/share/doc/anyfile" "$STAGE/DEBIAN"

# Codice: solo il pacchetto Python, senza cache compilate.
cp -r "$ROOT/src/anyfile" "$PYDIR/"
find "$PYDIR" -name __pycache__ -prune -exec rm -rf {} +

cat > "$STAGE/usr/bin/anyfile" <<'PY'
#!/usr/bin/python3
import sys

from anyfile.main import main

sys.exit(main())
PY
chmod 755 "$STAGE/usr/bin/anyfile"

install -m 644 "$ROOT/packaging/anyfile.desktop" "$STAGE/usr/share/applications/anyfile.desktop"
# Nelle cartelle di sistema KDE non richiede il bit di esecuzione sul service menu.
install -m 644 "$ROOT/packaging/dolphin/anyfile.desktop" "$STAGE/usr/share/kio/servicemenus/anyfile.desktop"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/anyfile/README.md"
cat > "$STAGE/usr/share/doc/anyfile/copyright" <<TXT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: anyfile
Source: https://github.com/pietrolama/anyfile

Files: *
Copyright: 2026 pietrolama
TXT

INSTALLED_KB=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: anyfile
Version: $VERSION
Architecture: all
Maintainer: pietrolama <pietrolama1@gmail.com>
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, file
Recommends: ffmpeg, imagemagick, poppler-utils, ghostscript, libnotify-bin
Suggests: dolphin, libreoffice-writer, libreoffice-calc, libreoffice-impress, pandoc, texlive-xetex
Section: utils
Priority: optional
Homepage: https://github.com/pietrolama/anyfile
Description: convertitore di file locale con menu radiale per Dolphin
 ANYFILE converte e comprime immagini, audio, video, documenti e PDF usando i
 programmi installati (FFmpeg, ImageMagick, Poppler, LibreOffice, Pandoc,
 Ghostscript). In Dolphin, «Converti con ANYFILE» apre una ruota sotto il
 puntatore con le sole conversioni possibili per i file selezionati.
 .
 I motori sono facoltativi: ANYFILE usa quelli presenti e indica cosa
 installare per le altre conversioni.
CTRL

# Come py3compile: cache compilate create all'installazione e rimosse prima della rimozione.
cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    python3 -m compileall -q /usr/lib/python3/dist-packages/anyfile || true
fi
SH
cat > "$STAGE/DEBIAN/prerm" <<'SH'
#!/bin/sh
set -e
find /usr/lib/python3/dist-packages/anyfile -name __pycache__ -prune -exec rm -rf {} + || true
SH
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$STAGE" "$ROOT/dist/$PKG.deb" >/dev/null
echo "$ROOT/dist/$PKG.deb"
