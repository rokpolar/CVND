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
ARTICLE_PIPELINE_MODE="${ARTICLE_PIPELINE_MODE:-auto}"
RUN_ARTICLE_SUPPLEMENT="${RUN_ARTICLE_SUPPLEMENT:-0}"
GDELT_SUPPLEMENT_MAX_TIB="${GDELT_SUPPLEMENT_MAX_TIB:-0.25}"
LLM_QA_MODEL="${LLM_QA_MODEL:-gpt-5.6-luna}"
SITS_INFERENCE_WATCH="${SITS_INFERENCE_WATCH:-1}"
SITS_INFERENCE_WATCH_INTERVAL="${SITS_INFERENCE_WATCH_INTERVAL:-10}"
# Track-B download tuning.  Start aggressively and let the adaptive gate
# reduce concurrency on 429/Restricted Mode; set SITS_BLOCK_WORKERS=1 to force
# serial mode if the project quota is exhausted.
SITS_BLOCK_WORKERS="${SITS_BLOCK_WORKERS:-16}"
SITS_MAX_INFLIGHT_REQUESTS="${SITS_MAX_INFLIGHT_REQUESTS:-32}"
SITS_MIN_INFLIGHT_REQUESTS="${SITS_MIN_INFLIGHT_REQUESTS:-4}"
SKIP_COVARIATES="${SKIP_COVARIATES:-0}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-0}"
DRY_RUN="${DRY_RUN:-0}"
# Track A feeds the default S1-first, S2-fallback routing. sits_primary needs
# Track B for every district (SATELLITE_TRACK=both) and compare_tracks.
SATELLITE_TRACK="${SATELLITE_TRACK:-A}"
SATELLITE_ROUTING="${SATELLITE_ROUTING:-s1_then_s2}"
SITS_BACKEND="${SITS_BACKEND:-gee}"
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo 'Usage: run_pipeline.sh [--dry-run]' >&2; exit 2; fi
if [[ "$ARTICLE_PIPELINE_MODE" != auto && "$ARTICLE_PIPELINE_MODE" != force && "$ARTICLE_PIPELINE_MODE" != skip ]]; then
  echo 'ARTICLE_PIPELINE_MODE must be auto, force, or skip' >&2; exit 2
fi
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
if [[ "$SETUP_DEPS" == 1 ]]; then run -m pip install -r requirements-lock.txt; fi
echo 'CVND PRIMARY: event × district; legacy state caches are incompatible.'
export SITS_BLOCK_WORKERS SITS_MAX_INFLIGHT_REQUESTS SITS_MIN_INFLIGHT_REQUESTS SITS_BACKEND
echo "SKIP_GEE=$SKIP_GEE ARTICLE_PIPELINE_MODE=$ARTICLE_PIPELINE_MODE SKIP_COVARIATES=$SKIP_COVARIATES SKIP_ANALYSIS=$SKIP_ANALYSIS DRY_RUN=$DRY_RUN SATELLITE_TRACK=$SATELLITE_TRACK SATELLITE_ROUTING=$SATELLITE_ROUTING SITS_BACKEND=$SITS_BACKEND SITS_BLOCK_WORKERS=$SITS_BLOCK_WORKERS SITS_MAX_INFLIGHT_REQUESTS=$SITS_MAX_INFLIGHT_REQUESTS SITS_MIN_INFLIGHT_REQUESTS=$SITS_MIN_INFLIGHT_REQUESTS"
run src/build_emdat_events.py
if [[ "$SKIP_COVARIATES" != 1 ]]; then run src/build_district_covariates.py; fi
if [[ "$SKIP_GEE" != 1 ]]; then
  if [[ "$SITS_BACKEND" == "cdse-local" && "$SATELLITE_TRACK" == "B" ]]; then
    echo 'Using pinned local district AOI cache; no Earth Engine AOI calls.'
  else
    run src/event_aoi_area.py
  fi
  if [[ "$SATELLITE_TRACK" == "A" || "$SATELLITE_TRACK" == "both" ]]; then
    run src/satellite.py --track A --sensor s1 --backend "$SITS_BACKEND"
    run src/satellite.py --track A --sensor s2 --backend "$SITS_BACKEND"
  fi
  if [[ "$SATELLITE_TRACK" == "B" || "$SATELLITE_TRACK" == "both" ]] \
      && [[ "$DRY_RUN" != 1 && "$SITS_INFERENCE_WATCH" == 1 ]]; then
    # Track-B writes an atomic block checkpoint beside every H5.  Keep a
    # watcher alongside the downloader so completed H5 files are inferred
    # immediately while partial files remain excluded by the inference code.
    printf '>>> '
    printf '%q ' "$PYTHON" src/satellite.py --track B --backend "$SITS_BACKEND"
    printf '& (SITS inference watcher enabled)\n'
    "$PYTHON" src/satellite.py --track B --backend "$SITS_BACKEND" &
    satellite_pid=$!
    watcher_pid=''
    cleanup_sits_watcher() {
      if [[ -n "${satellite_pid:-}" ]] && kill -0 "$satellite_pid" 2>/dev/null; then
        kill -TERM "$satellite_pid" 2>/dev/null || true
      fi
      if [[ -n "${watcher_pid:-}" ]] && kill -0 "$watcher_pid" 2>/dev/null; then
        kill -TERM "$watcher_pid" 2>/dev/null || true
      fi
    }
    trap cleanup_sits_watcher EXIT INT TERM
    "$PYTHON" scripts/watch_sits_inference.py \
      --satellite-pid "$satellite_pid" \
      --interval "$SITS_INFERENCE_WATCH_INTERVAL" \
      --device auto &
    watcher_pid=$!
    set +e
    wait "$satellite_pid"
    satellite_status=$?
    wait "$watcher_pid"
    watcher_status=$?
    set -e
    trap - EXIT INT TERM
    if (( satellite_status != 0 )); then
      exit "$satellite_status"
    fi
    if (( watcher_status != 0 )); then
      echo "SITS inference watcher failed (status=$watcher_status)" >&2
      exit "$watcher_status"
    fi
  elif [[ "$SATELLITE_TRACK" == "B" || "$SATELLITE_TRACK" == "both" ]]; then
    run src/satellite.py --track B --backend "$SITS_BACKEND"
    run src/run_sits_inference.py
  fi
else
  echo 'Using district satellite caches only; missing artifacts fail explicitly.'
fi
# s1_then_s2: use S1 when observed and S2 NDWI only for missing-S1 districts.
# sits_primary: SITS (Track B) first; a district whose Track B is not finished
# stays missing (sits_pending), never S1, and compare_tracks.py decides the
# S1 -> SITS-NDWI converter for districts SITS cannot measure.
if [[ "$SATELLITE_ROUTING" == "sits_primary" ]]; then
  run src/compare_tracks.py
fi
run src/merge_results.py --routing "$SATELLITE_ROUTING"
run src/build_flood_area_table.py
article_input="$ROOT/data/intermediate/district_gdelt.articles.jsonl.gz"
article_database="$ROOT/data/cache/district/articles.sqlite"
qa_args=(--source "$article_input" --database "$article_database" --model "$LLM_QA_MODEL")
if [[ "$ARTICLE_PIPELINE_MODE" == skip ]]; then
  ARTICLE_STATE=skip
elif [[ "$ARTICLE_PIPELINE_MODE" == force ]]; then
  ARTICLE_STATE=none
else
  ARTICLE_STATE="$("$PYTHON" src/article_qa.py state "${qa_args[@]}")"
fi
echo "Article pipeline state: $ARTICLE_STATE"
if [[ "$ARTICLE_STATE" == none ]]; then
  run src/district_articles.py --execute --overwrite
  run src/download_articles.py "$article_input" --output "$article_database"
  run src/district_articles.py --counts-only
  run src/article_qa.py prepare "${qa_args[@]}"
  ARTICLE_STATE=heuristic_complete
fi
if [[ "$ARTICLE_STATE" == heuristic_complete ]]; then
  if [[ "$RUN_ARTICLE_SUPPLEMENT" == 1 ]]; then
    run src/article_qa.py retry-text "${qa_args[@]}"
    run src/article_qa.py prepare "${qa_args[@]}"
    run src/article_qa.py supplement "${qa_args[@]}" --execute --maximum-tib "$GDELT_SUPPLEMENT_MAX_TIB"
    run src/article_qa.py download-new "${qa_args[@]}"
    run src/article_qa.py prepare "${qa_args[@]}"
  fi
  run src/article_qa.py run-batches "${qa_args[@]}" --execute
  run src/article_qa.py counts "${qa_args[@]}"
  ARTICLE_STATE=llm_complete
fi
if [[ "$ARTICLE_STATE" == llm_complete ]]; then
  run src/join_district_flood_articles.py --articles data/intermediate/article_qa/counts_30d.csv
  run src/join_district_flood_articles.py --articles data/intermediate/article_qa/counts_14d.csv \
    --output data/results/sensitivity_14d/district_flood_articles.csv \
    --exclusions data/results/sensitivity_14d/district_analysis_exclusions.csv \
    --qc data/results/sensitivity_14d/district_qc.json
fi
if [[ "$SKIP_ANALYSIS" != 1 && "$ARTICLE_STATE" != skip ]]; then
  run src/analyze_coverage_disparity.py
  run src/analyze_coverage_disparity.py \
    --input data/results/sensitivity_14d/district_flood_articles.csv \
    --output-dir outputs/sensitivity_14d \
    --results-dir data/results/sensitivity_14d
  run src/score_coverage.py
  run src/score_coverage.py \
    --input data/results/sensitivity_14d/district_flood_articles.csv \
    --output-dir outputs/sensitivity_14d \
    --results-dir data/results/sensitivity_14d
  run scripts/build_analysis_package.py
fi
if [[ "$DRY_RUN" == 1 ]]; then
  echo 'Offline validation (no queries, downloads, model fitting, or artifact replacement):'
  "$PYTHON" src/build_emdat_events.py --dry-run
  "$PYTHON" src/pipeline_preflight.py
else
  echo 'District pipeline complete. Review exclusions and data-quality warnings before interpretation.'
fi
