#!/usr/bin/env bash
# Prova il pacchetto .deb in un container pulito (podman o docker):
# installazione con le dipendenze consigliate, suite di test completa sul pacchetto
# installato, aggiornamento a una versione successiva, rimozione senza residui.
# Uso: packaging/deb/test-clean-install.sh [immagine]   (predefinita: debian:trixie)
set -euo pipefail

IMAGE="${1:-debian:trixie}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="$(command -v podman || command -v docker)"

VERSION="$(python3 -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1],"rb"))["project"]["version"])' "$ROOT/pyproject.toml")"
NEXT="${VERSION}+prova1"  # versione fittizia per provare l'aggiornamento
"$ROOT/packaging/deb/build.sh" >/dev/null
VERSION="$NEXT" "$ROOT/packaging/deb/build.sh" >/dev/null

"$ENGINE" run --rm -i \
    -v "$ROOT/dist:/pkg:ro" -v "$ROOT/tests:/src-tests:ro" \
    -e CURRENT="anyfile_${VERSION}_all.deb" -e NEXT="anyfile_${NEXT}_all.deb" \
    "$IMAGE" bash -s <<'INNER'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
step() { printf '\n== %s\n' "$*"; }

step "Installazione di $CURRENT (con le dipendenze consigliate)"
apt-get update -qq
apt-get install -y -qq "/pkg/$CURRENT" python3-pytest pandoc >/dev/null
anyfile --version
anyfile engines

step "Suite di test sul pacchetto installato"
cp -r /src-tests /tmp/tests
cd /tmp/tests
python3 -c 'import anyfile, sys; assert anyfile.__file__.startswith("/usr/lib/python3/"), anyfile.__file__; print("anyfile da", anyfile.__file__)'
QT_QPA_PLATFORM=offscreen python3 -m pytest -q -p no:cacheprovider -rs .
cd /

step "Aggiornamento a $NEXT"
apt-get install -y -qq "/pkg/$NEXT" >/dev/null
dpkg-query -W -f='versione installata: ${Version}\n' anyfile
anyfile engines >/dev/null

step "Rimozione"
apt-get remove -y -qq anyfile >/dev/null
for path in /usr/bin/anyfile /usr/lib/python3/dist-packages/anyfile \
            /usr/share/applications/anyfile.desktop /usr/share/kio/servicemenus/anyfile.desktop; do
    if [ -e "$path" ]; then echo "RESIDUO: $path"; exit 1; fi
done
echo "nessun residuo"
INNER
