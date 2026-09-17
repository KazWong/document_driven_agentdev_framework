#!/usr/bin/env bash
set -euo pipefail
shellcheck bin/* scripts/ci/*.sh
bats test
