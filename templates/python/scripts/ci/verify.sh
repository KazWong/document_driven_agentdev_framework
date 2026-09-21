#!/usr/bin/env bash
set -euo pipefail
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m pytest tests
if command -v ruff >/dev/null 2>&1; then
  ruff check .
fi
