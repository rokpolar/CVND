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
# Satellite stages (AOI, Track A) run by default; SKIP_GEE=1 reuses
# the cached satellite tables instead.
SKIP_GEE="${SKIP_GEE:-0}"
ARTICLE_PIPELINE_MODE="${ARTICLE_PIPELINE_MODE:-frozen}"
# Offline one-time migration/revalidation of already-paid QA results. Set to 0
# to require a fresh heuristic + LLM run when the current manifests are stale.
ARTICLE_ADOPT_EXISTING_QA="${ARTICLE_ADOPT_EXISTING_QA:-1}"
RUN_ARTICLE_SUPPLEMENT="${RUN_ARTICLE_SUPPLEMENT:-0}"
GDELT_SUPPLEMENT_MAX_TIB="${GDELT_SUPPLEMENT_MAX_TIB:-0.25}"
LLM_QA_MODEL="${LLM_QA_MODEL:-gpt-5.6-luna}"
SKIP_COVARIATES="${SKIP_COVARIATES:-0}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-0}"
DRY_RUN="${DRY_RUN:-0}"
# Production contract: S1 for all valid AOIs, then S2 only where S1 is missing.
# Track B/SITS is not part of this full-pipeline entry point.
SATELLITE_TRACK="${SATELLITE_TRACK:-A}"
SATELLITE_ROUTING="${SATELLITE_ROUTING:-s1_then_s2}"
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo 'Usage: run_pipeline.sh [--dry-run]' >&2; exit 2; fi
if [[ "$ARTICLE_PIPELINE_MODE" != frozen && "$ARTICLE_PIPELINE_MODE" != auto && "$ARTICLE_PIPELINE_MODE" != force && "$ARTICLE_PIPELINE_MODE" != skip ]]; then
  echo 'ARTICLE_PIPELINE_MODE must be frozen, auto, force, or skip' >&2; exit 2
fi
if [[ "$ARTICLE_ADOPT_EXISTING_QA" != 0 && "$ARTICLE_ADOPT_EXISTING_QA" != 1 ]]; then
  echo 'ARTICLE_ADOPT_EXISTING_QA must be 0 or 1' >&2; exit 2
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
if [[ "$SATELLITE_TRACK" != A ]]; then
  echo "SATELLITE_TRACK=$SATELLITE_TRACK: the production pipeline is Track A only" >&2; exit 2
fi
if [[ "$SATELLITE_ROUTING" != s1_then_s2 ]]; then
  echo "SATELLITE_ROUTING=$SATELLITE_ROUTING: the production pipeline requires s1_then_s2" >&2; exit 2
fi
s2_status='Track A only: Sentinel-1 first; S2 NDWI only where matched AOI has no S1 observation; no Track B/SITS'
echo 'CVND PRIMARY: event × district; legacy state caches are incompatible.'
echo "SKIP_GEE=$SKIP_GEE ARTICLE_PIPELINE_MODE=$ARTICLE_PIPELINE_MODE SKIP_COVARIATES=$SKIP_COVARIATES SKIP_ANALYSIS=$SKIP_ANALYSIS DRY_RUN=$DRY_RUN SATELLITE_TRACK=$SATELLITE_TRACK SATELLITE_ROUTING=$SATELLITE_ROUTING"
echo "S2/SITS: $s2_status"
run src/build_emdat_events.py
if [[ "$SKIP_COVARIATES" != 1 ]]; then run src/build_district_covariates.py; fi
if [[ "$SKIP_GEE" != 1 ]]; then
  run src/event_aoi_area.py
  run src/satellite.py --track A --sensor s1
  run src/satellite.py --track A --sensor s2
else
  echo 'Using district satellite caches only; missing artifacts fail explicitly.'
fi
# s1_then_s2 uses S1 when observed and S2 NDWI only for missing-S1 districts.
run src/merge_results.py --routing "$SATELLITE_ROUTING"
run src/build_flood_area_table.py
article_input="$ROOT/data/intermediate/district_gdelt.articles.jsonl.gz"
article_database="$ROOT/data/cache/district/articles.sqlite"
qa_args=(--source "$article_input" --database "$article_database" --model "$LLM_QA_MODEL")
if [[ "$ARTICLE_PIPELINE_MODE" == frozen ]]; then
  ARTICLE_STATE="$("$PYTHON" src/article_qa.py state "${qa_args[@]}")"
  if [[ "$ARTICLE_STATE" != llm_complete ]]; then
    echo "ARTICLE_PIPELINE_MODE=frozen requires validated llm_complete artifacts; found $ARTICLE_STATE" >&2
    echo 'Frozen mode never collects articles, downloads bodies, adopts snapshots, or runs LLM-QA.' >&2
    exit 1
  fi
elif [[ "$ARTICLE_PIPELINE_MODE" == skip ]]; then
  ARTICLE_STATE=skip
elif [[ "$ARTICLE_PIPELINE_MODE" == force ]]; then
  ARTICLE_STATE=none
else
  if [[ "$ARTICLE_ADOPT_EXISTING_QA" == 1 ]]; then
    run src/article_qa.py adopt-existing "${qa_args[@]}"
  fi
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
    run src/article_qa.py prepare "${qa_args[@]}"
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
