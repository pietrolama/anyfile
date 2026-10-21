#!/usr/bin/env bash
# Writes the manifest to submit to Flathub: the same as io.github.pietrolama.anyfile.yaml,
# but ANYFILE comes from the git tag of a release instead of the local folder.
#   scripts/flathub-manifest.sh v0.4.0 [output.yaml]
# The tag must already be pushed to GitHub.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:?usage: $0 <tag> [output.yaml]}"
OUT="${2:-/dev/stdout}"

cd "$ROOT"
COMMIT="$(git rev-list -n 1 "$TAG")"
git ls-remote --exit-code --tags origin "refs/tags/$TAG" > /dev/null \
    || { echo "tag $TAG is not on GitHub yet: git push origin $TAG" >&2; exit 1; }

awk -v tag="$TAG" -v commit="$COMMIT" '
    /^      - type: dir$/ { dir = 1; next }
    dir && /^        path: \.$/ {
        print "      - type: git"
        print "        url: https://github.com/pietrolama/anyfile.git"
        print "        tag: " tag
        print "        commit: " commit
        dir = 0; next
    }
    { print }
' io.github.pietrolama.anyfile.yaml > "$OUT"
