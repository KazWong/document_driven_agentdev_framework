#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$ROOT")"
NAME="$(basename "$ROOT")"
VERSION="$(cat "$ROOT/VERSION")"
OUTPUT="${1:-$PARENT}"
mkdir -p "$OUTPUT"
find "$ROOT" -type f ! -name ARTIFACT-MANIFEST.sha256 ! -name '*.pyc' ! -name .env ! -path '*/.pytest_cache/*' ! -path '*/__pycache__/*' -print0 \
  | sort -z | while IFS= read -r -d '' file; do (cd "$ROOT" && sha256sum "${file#$ROOT/}"); done \
  > "$ROOT/ARTIFACT-MANIFEST.sha256"
TAR="$OUTPUT/${NAME}-${VERSION}.tar.gz"
ZIP="$OUTPUT/${NAME}-${VERSION}.zip"
rm -f "$TAR" "$ZIP"
tar --sort=name --mtime='UTC 2026-09-03' --owner=0 --group=0 --numeric-owner \
  --exclude="$NAME/.pytest_cache" --exclude="$NAME/.pytest_cache/*" \
  --exclude="$NAME/**/__pycache__" --exclude="$NAME/**/__pycache__/*" \
  --exclude='*.pyc' --exclude="$NAME/.env" \
  -czf "$TAR" -C "$PARENT" "$NAME"
(cd "$PARENT" && zip -q -r "$ZIP" "$NAME" \
  -x '*/.pytest_cache/*' '*/__pycache__/*' '*.pyc' "$NAME/.env")
tar -tzf "$TAR" > "$OUTPUT/${NAME}-${VERSION}-MANIFEST.txt"
(cd "$OUTPUT" && sha256sum "$(basename "$TAR")" "$(basename "$ZIP")") \
  > "$OUTPUT/${NAME}-${VERSION}-SHA256SUMS.txt"
printf '%s\n%s\n' "$TAR" "$ZIP"
