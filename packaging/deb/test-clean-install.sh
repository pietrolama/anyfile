#!/usr/bin/env bash
# Tests the .deb package in a clean container (podman or docker): installation with
# the recommended dependencies, the full test suite on the installed package, upgrade
# to a later version, removal without leftovers.
# Usage: packaging/deb/test-clean-install.sh [image]   (default: debian:trixie)
set -euo pipefail

IMAGE="${1:-debian:trixie}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="$(command -v podman || command -v docker)"

VERSION="$(python3 -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1],"rb"))["project"]["version"])' "$ROOT/pyproject.toml")"
NEXT="${VERSION}+test1"  # fake version to try the upgrade
"$ROOT/packaging/deb/build.sh" >/dev/null
VERSION="$NEXT" "$ROOT/packaging/deb/build.sh" >/dev/null

"$ENGINE" run --rm -i \
    -v "$ROOT/dist:/pkg:ro" -v "$ROOT/tests:/src-tests:ro" \
    -e CURRENT="anyfile_${VERSION}_all.deb" -e NEXT="anyfile_${NEXT}_all.deb" \
    "$IMAGE" bash -s <<'INNER'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
step() { printf '\n== %s\n' "$*"; }

step "Installing $CURRENT (with the recommended dependencies)"
apt-get update -qq
apt-get install -y -qq "/pkg/$CURRENT" python3-pytest pandoc >/dev/null
anyfile --version
anyfile engines

step "Test suite on the installed package"
cp -r /src-tests /tmp/tests
cd /tmp/tests
python3 -c 'import anyfile, sys; assert anyfile.__file__.startswith("/usr/lib/python3/"), anyfile.__file__; print("anyfile from", anyfile.__file__)'
QT_QPA_PLATFORM=offscreen python3 -m pytest -q -p no:cacheprovider -rs .
cd /

step "Upgrading to $NEXT"
apt-get install -y -qq "/pkg/$NEXT" >/dev/null
dpkg-query -W -f='installed version: ${Version}\n' anyfile
anyfile engines >/dev/null

step "Removal"
apt-get remove -y -qq anyfile >/dev/null
for path in /usr/bin/anyfile /usr/lib/python3/dist-packages/anyfile \
            /usr/share/applications/anyfile.desktop /usr/share/kio/servicemenus/anyfile.desktop; do
    if [ -e "$path" ]; then echo "LEFTOVER: $path"; exit 1; fi
done
echo "no leftovers"
INNER
