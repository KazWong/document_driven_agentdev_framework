#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="robotics-ai-agent-dev-env"
GIT_TOP="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$GIT_TOP" || "$GIT_TOP" != "$ROOT" ]]; then
  printf 'package: %s must be the root of a Git checkout\n' "$ROOT" >&2
  exit 2
fi

# Package exactly HEAD. Local .env is legacy runtime state and is intentionally
# allowed to differ because .gitattributes excludes it from release exports.
dirty="$(git -C "$ROOT" status --porcelain --untracked-files=all | awk '
  { path=substr($0,4); if (path != ".env" && path != "\".env\"") print }
')"
if [[ -n "$dirty" ]]; then
  printf 'package: refusing to package with uncommitted source changes:\n%s\n' "$dirty" >&2
  exit 2
fi

VERSION="$(git -C "$ROOT" show HEAD:VERSION | tr -d '\r\n')"
SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_TREE="$(git -C "$ROOT" rev-parse 'HEAD^{tree}')"
OUTPUT="${1:-$(dirname "$ROOT")}"
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
TMP="$(mktemp -d "$OUTPUT/.${NAME}-${VERSION}.tmp.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

TAR_TMP="$TMP/${NAME}-${VERSION}.tar.gz"
ZIP_TMP="$TMP/${NAME}-${VERSION}.zip"
MANIFEST_TMP="$TMP/${NAME}-${VERSION}-MANIFEST.txt"
PROVENANCE_TMP="$TMP/${NAME}-${VERSION}-PROVENANCE.txt"
SUMS_TMP="$TMP/${NAME}-${VERSION}-SHA256SUMS.txt"

# Git supplies the authoritative tracked-file set and committed Unix modes.
# gzip -n removes volatile gzip header metadata; the archive entries themselves
# use the committed Git metadata, so repeated builds of the same commit match.
git -C "$ROOT" archive --format=tar --prefix="$NAME/" HEAD | gzip -n -9 > "$TAR_TMP"
git -C "$ROOT" archive --format=zip --prefix="$NAME/" HEAD > "$ZIP_TMP"
tar -tzf "$TAR_TMP" > "$MANIFEST_TMP"
cat > "$PROVENANCE_TMP" <<EOF_PROVENANCE
release=$VERSION
source_commit=$SOURCE_COMMIT
source_tree=$SOURCE_TREE
archive_root=$NAME
EOF_PROVENANCE

TAR_EXTRACT="$TMP/tar-extract"
ZIP_EXTRACT="$TMP/zip-extract"
mkdir -p "$TAR_EXTRACT" "$ZIP_EXTRACT"
tar -xzf "$TAR_TMP" -C "$TAR_EXTRACT"
unzip -q "$ZIP_TMP" -d "$ZIP_EXTRACT"
TAR_ROOT="$TAR_EXTRACT/$NAME"
ZIP_ROOT="$ZIP_EXTRACT/$NAME"

python3 "$ROOT/scripts/qa/validate_tree.py" --mode release "$TAR_ROOT" > "$TMP/tar-validation.json"
python3 "$ROOT/scripts/qa/validate_tree.py" --mode release "$ZIP_ROOT" > "$TMP/zip-validation.json"
(cd "$TAR_ROOT" && sha256sum -c ARTIFACT-MANIFEST.sha256 >/dev/null)
(cd "$ZIP_ROOT" && sha256sum -c ARTIFACT-MANIFEST.sha256 >/dev/null)

diff -qr "$TAR_ROOT" "$ZIP_ROOT" >/dev/null
python3 - "$TAR_ROOT" "$ZIP_ROOT" <<'PY'
from pathlib import Path
import stat
import sys

def executable_modes(root: Path) -> dict[str, bool]:
    return {
        str(path.relative_to(root)): bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
        for path in root.rglob("*")
        if path.is_file()
    }

a = executable_modes(Path(sys.argv[1]))
b = executable_modes(Path(sys.argv[2]))
if a != b:
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    raise SystemExit(
        "archive executable-mode mismatch: "
        f"tar-only={only_a}, zip-only={only_b}, changed={[(k, a[k], b[k]) for k in changed]}"
    )
PY

(
  cd "$TMP"
  sha256sum \
    "$(basename "$TAR_TMP")" \
    "$(basename "$ZIP_TMP")" \
    "$(basename "$MANIFEST_TMP")" \
    "$(basename "$PROVENANCE_TMP")" \
    > "$(basename "$SUMS_TMP")"
)

for artifact in "$TAR_TMP" "$ZIP_TMP" "$MANIFEST_TMP" "$PROVENANCE_TMP" "$SUMS_TMP"; do
  mv -f "$artifact" "$OUTPUT/$(basename "$artifact")"
done

printf '%s\n' \
  "$OUTPUT/${NAME}-${VERSION}.tar.gz" \
  "$OUTPUT/${NAME}-${VERSION}.zip" \
  "$OUTPUT/${NAME}-${VERSION}-MANIFEST.txt" \
  "$OUTPUT/${NAME}-${VERSION}-PROVENANCE.txt" \
  "$OUTPUT/${NAME}-${VERSION}-SHA256SUMS.txt"
