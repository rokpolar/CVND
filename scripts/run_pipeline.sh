#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  source "$ROOT/.env"
  set +a
fi
SETUP_DEPS="${SETUP_DEPS:-0}"
SKIP_GEE="${SKIP_GEE:-1}"
SKIP_ARTICLES="${SKIP_ARTICLES:-1}"
SKIP_COVARIATES="${SKIP_COVARIATES:-0}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-0}"
DRY_RUN="${DRY_RUN:-0}"
SATELLITE_TRACK="${SATELLITE_TRACK:-A}"
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo 'Usage: run_pipeline.sh [--dry-run]' >&2; exit 2; fi
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  if [[ -x "$ROOT/venv/Scripts/python.exe" ]]; then
    PYTHON="$ROOT/venv/Scripts/python.exe"
  elif [[ "$DRY_RUN" == 1 ]]; then
    PYTHON="$(command -v python3)"
  else
    python3 -m venv "$ROOT/venv"
    PYTHON="$ROOT/venv/bin/python"
  fi
fi
run() {
  printf '>>> '
  printf '%q ' "$PYTHON" "$@"
  printf '\n'
  if [[ "$DRY_RUN" != 1 ]]; then "$PYTHON" "$@"; fi
}
if [[ "$SETUP_DEPS" == 1 ]]; then run -m pip install -r requirements.txt; fi
echo 'CVND PRIMARY: event × district; legacy state caches are incompatible.'
echo "SKIP_GEE=$SKIP_GEE SKIP_ARTICLES=$SKIP_ARTICLES SKIP_COVARIATES=$SKIP_COVARIATES SKIP_ANALYSIS=$SKIP_ANALYSIS DRY_RUN=$DRY_RUN"
run src/build_emdat_events.py
if [[ "$SKIP_COVARIATES" != 1 ]]; then run src/build_district_covariates.py; fi
if [[ "$SKIP_GEE" != 1 ]]; then
  run event_aoi_area.py
  run src/satellite.py --track "$SATELLITE_TRACK"
  if [[ "$SATELLITE_TRACK" == "B" || "$SATELLITE_TRACK" == "both" ]]; then
    run src/run_sits_inference.py
  fi
  run post_cloud.py
else
  echo 'Using district satellite caches only; missing artifacts fail explicitly.'
fi
# SITS scores are optional external inference artifacts. Track A preserves the
# existing S1/S2 detection stack. Track B/both additionally prepares patches.
run src/merge_results.py
run src/build_flood_area_table.py
if [[ "$SKIP_ARTICLES" != 1 ]]; then
  run src/collect_gdelt.py --spatial-unit district --execute --overwrite
  article_input="$("$PYTHON" -c "import sys; sys.path.insert(0, 'src'); from cvnd_layout import data_path; print(data_path('district_gdelt_articles'))")"
  article_database="$("$PYTHON" -c "import sys; sys.path.insert(0, 'src'); from cvnd_layout import data_path; print(data_path('district_article_database'))")"
  run src/download_articles.py "$article_input" --output "$article_database"
fi
run src/district_articles.py --counts-only
run src/join_district_flood_articles.py
if [[ "$SKIP_ANALYSIS" != 1 ]]; then run src/analyze_coverage_disparity.py; fi
if [[ "$DRY_RUN" == 1 ]]; then
  echo 'Offline validation (no queries, downloads, model fitting, or artifact replacement):'
  "$PYTHON" src/build_emdat_events.py --dry-run
  "$PYTHON" src/pipeline_preflight.py
else
  echo 'District pipeline complete. Review exclusions and data-quality warnings before interpretation.'
fi
