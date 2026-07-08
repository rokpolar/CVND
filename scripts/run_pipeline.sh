#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_DIR="$ROOT/venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

setup_environment() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required to set up the virtual environment." >&2
    exit 1
  fi

  if [[ ! -x "$PYTHON" ]]; then
    echo ">>> Creating virtual environment at venv/..."
    python3 -m venv "$VENV_DIR"
  else
    echo ">>> Using existing virtual environment at venv/"
  fi

  echo ">>> Installing dependencies from requirements.txt..."
  "$PYTHON" -m pip install --upgrade pip
  "$PIP" install -r "$ROOT/requirements.txt"
}

setup_environment

SKIP_GEE="${SKIP_GEE:-0}"
SKIP_ARTICLES="${SKIP_ARTICLES:-0}"

STEPS=(
  "src/build_events.py"
  "src/build_covariates.py"
)

if [[ "$SKIP_GEE" != "1" ]]; then
  STEPS+=(
    "src/test_gee.py"
    "src/satellite.py"
    "src/population.py"
  )
else
  echo "NOTE: SKIP_GEE=1 — skipping GEE steps (CP-04 to CP-06)"
fi

STEPS+=("src/compute_pss.py")

if [[ "$SKIP_ARTICLES" != "1" ]]; then
  STEPS+=("src/build_articles.py")
else
  echo "NOTE: SKIP_ARTICLES=1 — skipping article dataset build"
fi

echo "======================================================="
echo "CVND PIPELINE"
echo "======================================================="
echo "Project root : $ROOT"
echo "Python       : $PYTHON"
echo "Steps        : ${#STEPS[@]}"
echo "======================================================="

for step in "${STEPS[@]}"; do
  echo
  echo ">>> Running $step"
  echo "-------------------------------------------------------"
  "$PYTHON" "$step"
done

echo
echo "======================================================="
echo "PIPELINE COMPLETE"
echo "======================================================="
