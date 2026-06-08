#!/usr/bin/env bash
# Pre-publish check — run this BEFORE pushing to main (production deploys from main).
# Catches syntax errors and logic regressions locally, the same checks CI runs.
#
#   ./scripts/preflight.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv-audit/bin/python}"

echo "→ Checagem de sintaxe (py_compile)..."
"$PY" -m py_compile app.py data/*.py reports/*.py calculations/*.py tests/*.py

echo "→ Testes (pytest)..."
"$PY" -m pytest -q

echo ""
echo "✅ Preflight OK — seguro publicar (git push origin main)."
