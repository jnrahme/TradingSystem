#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[verify] checking patch hygiene"
git diff --check

echo "[verify] compiling python sources"
python3 -m compileall src

echo "[verify] parsing schema json files"
python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

schema_dir = Path("schemas")
paths = sorted(schema_dir.glob("*.json"))
if not paths:
    raise SystemExit("no schema files found")

for path in paths:
    with path.open("r", encoding="utf-8") as handle:
        json.load(handle)
print(f"parsed {len(paths)} schema files")
PY

echo "[verify] running test suite"
pytest -q

echo "[verify] resetting local paper state for smoke run"
rm -f var/trading-state.sqlite3 var/internal-paper-state.json apps/dashboard/data/summary.json

echo "[verify] exercising internal paper worker"
PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper --execute >/tmp/nts-ci-run-once.json
PYTHONPATH=src python3 -m new_trading_system.cli reconcile --broker internal-paper >/tmp/nts-ci-reconcile.json
PYTHONPATH=src python3 -m new_trading_system.cli verify --broker internal-paper >/tmp/nts-ci-verify.json

echo "[verify] done"
