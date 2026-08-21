#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_DIR="$ROOT/venv"
# Prefer Unix venv; fall back to Windows Scripts/python.exe
if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON="$VENV_DIR/bin/python"
elif [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
  PYTHON="$VENV_DIR/Scripts/python.exe"
else
  PYTHON=""
fi

SETUP_DEPS="${SETUP_DEPS:-0}"

setup_environment() {
  if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      echo "ERROR: python3 is required to set up the virtual environment." >&2
      exit 1
    fi
    echo ">>> Creating virtual environment at venv/..."
    python3 -m venv "$VENV_DIR"
    if [[ -x "$VENV_DIR/bin/python" ]]; then
      PYTHON="$VENV_DIR/bin/python"
    else
      PYTHON="$VENV_DIR/Scripts/python.exe"
    fi
  else
    echo ">>> Using existing virtual environment at venv/"
  fi

  if [[ "$SETUP_DEPS" == "1" ]]; then
    echo ">>> Installing dependencies from requirements.txt (SETUP_DEPS=1)..."
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
  else
    echo ">>> Skipping pip install (set SETUP_DEPS=1 to reinstall deps)"
  fi
}

setup_environment

echo ">>> Rebuilding canonical event registry from EM-DAT-BASE.xlsx"
"$PYTHON" src/build_emdat_events.py

echo ">>> Validating canonical event registry"
"$PYTHON" src/archive/build_events.py

SKIP_GEE="${SKIP_GEE:-1}"
SKIP_ARTICLES="${SKIP_ARTICLES:-1}"

STEPS=()

if [[ "$SKIP_GEE" != "1" ]]; then
  STEPS+=(
    "src/satellite.py"
    "event_aoi_area.py"
    "post_cloud.py"
    "src/merge_results.py"
    "src/compute_population.py"
  )
else
  echo "NOTE: SKIP_GEE=1 — skipping GEE satellite pull (using cached flood artifacts)"
  # Still rebuild severity from existing flood_combined / flood_extent artifacts
  if [[ -f "$ROOT/data/cache/flood_extent.csv" && -d "$ROOT/data/cache/sits_scores" ]]; then
    if [[ ! -f "$ROOT/data/intermediate/event_aoi_area.csv" || ! -f "$ROOT/data/intermediate/post_cloud.csv" ]]; then
      echo "ERROR: cached satellite data lacks state-AOI area/cloud files; run with SKIP_GEE=0." >&2
      exit 1
    fi
    STEPS+=("src/merge_results.py")
  fi
  if [[ ! -f "$ROOT/data/intermediate/flood_combined.csv" && ! -f "$ROOT/data/cache/flood_extent.csv" ]]; then
    echo "ERROR: no satellite cache exists for the rebuilt registry; run with SKIP_GEE=0." >&2
    exit 1
  fi
  STEPS+=("src/compute_population.py")
fi

STEPS+=("src/compute_pss.py")

if [[ "$SKIP_ARTICLES" != "1" ]]; then
  echo "NOTE: SKIP_ARTICLES=0 — running archived GDELT Doc API collector"
  echo "      Primary MSS still reads data/raw/gdelt_bq.json (not news.py output)"
  STEPS+=("src/archive/news.py")
else
  echo "NOTE: SKIP_ARTICLES=1 — skipping GDELT Doc API (MSS uses data/raw/gdelt_bq.json)"
fi

STEPS+=(
  "src/compute_mss.py"
  "src/compute_expected_coverage.py"
  "src/visualize.py"
)

echo "======================================================="
echo "CVND PIPELINE"
echo "======================================================="
echo "Project root : $ROOT"
echo "Python       : $PYTHON"
echo "SKIP_GEE     : $SKIP_GEE"
echo "SKIP_ARTICLES: $SKIP_ARTICLES"
echo "SETUP_DEPS   : $SETUP_DEPS"
echo "Primary model: NegBin log_ratio on article counts (MSS total_articles)"
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
