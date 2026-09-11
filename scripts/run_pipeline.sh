#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # Strip CRs: a .env saved with Windows line endings would otherwise fail.
  source <(tr -d '\r' < "$ROOT/.env")
  set +a
fi
SETUP_DEPS="${SETUP_DEPS:-0}"
SKIP_GEE="${SKIP_GEE:-1}"
SKIP_ARTICLES="${SKIP_ARTICLES:-1}"
SKIP_COVARIATES="${SKIP_COVARIATES:-0}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-0}"
DRY_RUN="${DRY_RUN:-0}"
# Track A alone feeds the interim S1 routing. sits_primary needs Track B for
# every district (SATELLITE_TRACK=both) and the compare_tracks converter.
SATELLITE_TRACK="${SATELLITE_TRACK:-A}"
SATELLITE_ROUTING="${SATELLITE_ROUTING:-s1_interim}"
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo 'Usage: run_pipeline.sh [--dry-run]' >&2; exit 2; fi
# Interpreter: $PYTHON if given; else the project venv; else the first python
# on PATH that has the pipeline's packages. On Windows `python3` can be the
# Microsoft Store stub, which exists but cannot run anything, so every
# candidate is probed instead of trusted by name.
has_packages() { [[ -n "$1" && -x "$1" ]] && "$1" -c 'import numpy, pandas' >/dev/null 2>&1; }
if [[ -n "${PYTHON:-}" ]]; then
  if [[ ! -x "$PYTHON" ]]; then echo "PYTHON=$PYTHON is not executable" >&2; exit 2; fi
else
  for candidate in "$ROOT/venv/bin/python" "$ROOT/venv/Scripts/python.exe" \
                   "$(command -v python3 || true)" "$(command -v python || true)"; do
    if has_packages "$candidate"; then PYTHON="$candidate"; break; fi
  done
fi
if [[ -z "${PYTHON:-}" ]]; then
  if [[ "$SETUP_DEPS" != 1 ]]; then
    echo 'No Python with numpy/pandas found: set PYTHON=/path/to/python, or SETUP_DEPS=1 to create venv/' >&2
    exit 2
  fi
  for base in "$(command -v python3 || true)" "$(command -v python || true)"; do
    if [[ -n "$base" ]] && "$base" -c 'pass' >/dev/null 2>&1; then "$base" -m venv "$ROOT/venv"; break; fi
  done
  for candidate in "$ROOT/venv/bin/python" "$ROOT/venv/Scripts/python.exe"; do
    if [[ -x "$candidate" ]]; then PYTHON="$candidate"; break; fi
  done
  if [[ -z "${PYTHON:-}" ]]; then echo 'Could not create venv/: no working python on PATH' >&2; exit 2; fi
fi
run() {
  printf '>>> '
  printf '%q ' "$PYTHON" "$@"
  printf '\n'
  if [[ "$DRY_RUN" != 1 ]]; then "$PYTHON" "$@"; fi
}
if [[ "$SETUP_DEPS" == 1 ]]; then run -m pip install -r requirements.txt; fi
echo 'CVND PRIMARY: event × district; legacy state caches are incompatible.'
echo "SKIP_GEE=$SKIP_GEE SKIP_ARTICLES=$SKIP_ARTICLES SKIP_COVARIATES=$SKIP_COVARIATES SKIP_ANALYSIS=$SKIP_ANALYSIS DRY_RUN=$DRY_RUN SATELLITE_TRACK=$SATELLITE_TRACK SATELLITE_ROUTING=$SATELLITE_ROUTING"
run src/build_emdat_events.py
if [[ "$SKIP_COVARIATES" != 1 ]]; then run src/build_district_covariates.py; fi
if [[ "$SKIP_GEE" != 1 ]]; then
  run src/event_aoi_area.py
  run src/satellite.py --track "$SATELLITE_TRACK"
  if [[ "$SATELLITE_TRACK" == "B" || "$SATELLITE_TRACK" == "both" ]]; then
    run src/run_sits_inference.py
  fi
else
  echo 'Using district satellite caches only; missing artifacts fail explicitly.'
fi
# s1_interim: every district is measured by Track A Sentinel-1 new water.
# sits_primary: SITS (Track B) first; a district whose Track B is not finished
# stays missing (sits_pending), never S1, and compare_tracks.py decides the
# S1 -> SITS-NDWI converter for districts SITS cannot measure.
if [[ "$SATELLITE_ROUTING" == "sits_primary" ]]; then
  run src/compare_tracks.py
fi
run src/merge_results.py --routing "$SATELLITE_ROUTING"
run src/build_flood_area_table.py
if [[ "$SKIP_ARTICLES" != 1 ]]; then
  run src/district_articles.py --execute --overwrite
  article_input="$("$PYTHON" -c "import sys; sys.path.insert(0, 'src'); from cvnd_layout import data_path; print(data_path('district_gdelt_articles'))")"
  article_database="$("$PYTHON" -c "import sys; sys.path.insert(0, 'src'); from cvnd_layout import data_path; print(data_path('district_article_database'))")"
  run src/download_articles.py "$article_input" --output "$article_database"
fi
run src/district_articles.py --counts-only
run src/join_district_flood_articles.py
if [[ "$SKIP_ANALYSIS" != 1 ]]; then
  run src/analyze_coverage_disparity.py
  run src/score_coverage.py
fi
if [[ "$DRY_RUN" == 1 ]]; then
  echo 'Offline validation (no queries, downloads, model fitting, or artifact replacement):'
  "$PYTHON" src/build_emdat_events.py --dry-run
  "$PYTHON" src/pipeline_preflight.py
else
  echo 'District pipeline complete. Review exclusions and data-quality warnings before interpretation.'
fi
