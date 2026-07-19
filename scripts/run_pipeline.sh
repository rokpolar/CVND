#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_DIR="$ROOT/venv"
PYTHON="$VENV_DIR/bin/python"

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
  "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
}

setup_environment

SKIP_GEE="${SKIP_GEE:-1}"
SKIP_ARTICLES="${SKIP_ARTICLES:-1}"
LEGACY_DI="${LEGACY_DI:-0}"

STEPS=(
  "src/build_covariates.py"
)

if [[ "$SKIP_GEE" != "1" ]]; then
  STEPS+=(
    "src/test_gee.py"
    "src/satellite.py"
    "src/merge_results.py"
    "src/compute_population.py"
  )
else
  echo "NOTE: SKIP_GEE=1 — skipping GEE satellite pull"
  # Still rebuild severity from existing flood_combined / flood_extent artifacts
  if [[ -f "$ROOT/data/flood_extent.csv" && -d "$ROOT/data/sits_scores" ]]; then
    STEPS+=("src/merge_results.py")
  fi
  STEPS+=("src/compute_population.py")
fi

STEPS+=("src/compute_pss.py")

if [[ "$SKIP_ARTICLES" != "1" ]]; then
  STEPS+=("src/news.py")
else
  echo "NOTE: SKIP_ARTICLES=1 — skipping GDELT API collection (CP-08)"
fi

STEPS+=("src/compute_mss.py")

if [[ "$LEGACY_DI" == "1" ]]; then
  echo "NOTE: LEGACY_DI=1 — running demoted Min-Max DI (not primary)"
  STEPS+=("src/compute_di.py")
else
  echo "NOTE: LEGACY_DI=0 — skipping legacy DI; primary metric is expected_coverage log_ratio"
fi

STEPS+=(
  "src/compute_expected_coverage.py"
  "src/visualize.py"
)

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
