#!/usr/bin/env bash
# Builds the Debian/Ubuntu package of ANYFILE in dist/.
# Usage: packaging/deb/build.sh            (version from pyproject.toml)
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

# Code: only the Python package (with its translations), without compiled caches.
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
# In system folders KDE does not need the executable bit on the service menu.
install -m 644 "$ROOT/packaging/dolphin/anyfile.desktop" "$STAGE/usr/share/kio/servicemenus/anyfile.desktop"
install -m 644 "$ROOT/README.md" "$ROOT/README.it.md" "$STAGE/usr/share/doc/anyfile/"
cat > "$STAGE/usr/share/doc/anyfile/copyright" <<TXT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: anyfile
Source: https://github.com/pietrolama/anyfile

Files: *
Copyright: 2026 pietrolama
License: GPL-3+

License: GPL-3+
 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 .
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in "/usr/share/common-licenses/GPL-3".
TXT

INSTALLED_KB=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: anyfile
Version: $VERSION
Architecture: all
Maintainer: pietrolama <pietrolama1@gmail.com>
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, file
Recommends: ffmpeg, imagemagick, poppler-utils, ghostscript, qpdf, tesseract-ocr, libnotify-bin
Suggests: dolphin, qt6-translations-l10n, libreoffice-writer, libreoffice-calc, libreoffice-impress, pandoc, texlive-xetex
Section: utils
Priority: optional
Homepage: https://github.com/pietrolama/anyfile
Description: local file converter with a radial menu for Dolphin
 ANYFILE converts and compresses images, audio, video, documents and PDFs
 using the installed programs (FFmpeg, ImageMagick, Poppler, LibreOffice,
 Pandoc, Ghostscript). In Dolphin, "Convert with ANYFILE" opens a wheel under
 the pointer showing only the conversions possible for the selected files.
 .
 The engines are optional: ANYFILE uses the ones available and tells what to
 install for the other conversions. Available in English and Italian.
CTRL

# Like py3compile: compiled caches created on install and removed before removal.
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
