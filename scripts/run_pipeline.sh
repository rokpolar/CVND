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
ARTICLE_PIPELINE_MODE="${ARTICLE_PIPELINE_MODE:-auto}"
# Offline one-time migration/revalidation of already-paid QA results. Set to 0
# to require a fresh heuristic + LLM run when the current manifests are stale.
ARTICLE_ADOPT_EXISTING_QA="${ARTICLE_ADOPT_EXISTING_QA:-1}"
RUN_ARTICLE_SUPPLEMENT="${RUN_ARTICLE_SUPPLEMENT:-0}"
GDELT_SUPPLEMENT_MAX_TIB="${GDELT_SUPPLEMENT_MAX_TIB:-0.25}"
LLM_QA_MODEL="${LLM_QA_MODEL:-gpt-5.6-luna}"
SITS_INFERENCE_WATCH="${SITS_INFERENCE_WATCH:-1}"
SITS_INFERENCE_WATCH_INTERVAL="${SITS_INFERENCE_WATCH_INTERVAL:-10}"
# Track B rounds: rerun the download until every district is finished, waiting
# SITS_RETRY_WAIT seconds between rounds (lets Earth Engine quota recover).
SITS_DOWNLOAD_ROUNDS="${SITS_DOWNLOAD_ROUNDS:-5}"
SITS_RETRY_WAIT="${SITS_RETRY_WAIT:-300}"
# Track-B download tuning.  Start aggressively and let the adaptive gate
# reduce concurrency on 429/Restricted Mode; set SITS_BLOCK_WORKERS=1 to force
# serial mode if the project quota is exhausted.
SITS_BLOCK_WORKERS="${SITS_BLOCK_WORKERS:-16}"
SITS_MAX_INFLIGHT_REQUESTS="${SITS_MAX_INFLIGHT_REQUESTS:-32}"
SITS_MIN_INFLIGHT_REQUESTS="${SITS_MIN_INFLIGHT_REQUESTS:-4}"
SKIP_COVARIATES="${SKIP_COVARIATES:-0}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-0}"
DRY_RUN="${DRY_RUN:-0}"
# Default: S1 for all valid AOIs, then S2 only where S1 is missing.
# Track B/SITS requires explicit SATELLITE_TRACK=B or both and SITS routing.
SATELLITE_TRACK="${SATELLITE_TRACK:-A}"
SATELLITE_ROUTING="${SATELLITE_ROUTING:-s1_then_s2}"
SITS_BACKEND="${SITS_BACKEND:-gee}"
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo 'Usage: run_pipeline.sh [--dry-run]' >&2; exit 2; fi
if [[ "$ARTICLE_PIPELINE_MODE" != auto && "$ARTICLE_PIPELINE_MODE" != force && "$ARTICLE_PIPELINE_MODE" != skip ]]; then
  echo 'ARTICLE_PIPELINE_MODE must be auto, force, or skip' >&2; exit 2
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
# One Track B download round. With the watcher, completed H5 files are inferred
# while downloads continue (satellite.py writes an atomic block checkpoint
# beside every H5, and partial files stay excluded by the inference code).
download_track_b() {
  if [[ "$DRY_RUN" == 1 || "$SITS_INFERENCE_WATCH" != 1 ]]; then
    run src/satellite.py --track B --backend "$SITS_BACKEND"
    return
  fi
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
}
if [[ "$SETUP_DEPS" == 1 ]]; then run -m pip install -r requirements-lock.txt; fi
if [[ ! "$SITS_DOWNLOAD_ROUNDS" =~ ^[1-9][0-9]*$ || ! "$SITS_RETRY_WAIT" =~ ^[0-9]+$ ]]; then
  echo 'SITS_DOWNLOAD_ROUNDS must be a positive integer and SITS_RETRY_WAIT a number of seconds' >&2; exit 2
fi
case "$SATELLITE_TRACK" in A|B|both) ;; *) echo "SATELLITE_TRACK=$SATELLITE_TRACK: expected A, B or both" >&2; exit 2;; esac
case "$SATELLITE_ROUTING" in sits_then_track_a|s1_then_s2|sits_primary) ;; *) echo "SATELLITE_ROUTING=$SATELLITE_ROUTING: expected sits_then_track_a, s1_then_s2 or sits_primary" >&2; exit 2;; esac
sits_measurements="$("$PYTHON" -c "import sys; sys.path.insert(0, 'src'); from cvnd_layout import data_path; print(data_path('district_sits_measurements'))")"
# Contradictory settings are refused before anything runs: a sits_primary run
# that cannot obtain any SITS measurement would silently produce no S2 rows.
if [[ "$SATELLITE_ROUTING" == "sits_primary" ]]; then
  if [[ "$SKIP_GEE" != 1 && "$SATELLITE_TRACK" == "A" ]]; then
    echo 'SATELLITE_ROUTING=sits_primary needs Track B, but SATELLITE_TRACK=A never runs it.' >&2
    echo 'Use SATELLITE_TRACK=both, or the default SATELLITE_ROUTING=s1_then_s2 (S1 then S2 fallback).' >&2
    exit 2
  fi
  if [[ "$SKIP_GEE" == 1 && ! -s "$sits_measurements" ]]; then
    echo "SATELLITE_ROUTING=sits_primary with SKIP_GEE=1 needs cached Track B measurements, but $sits_measurements is missing or empty." >&2
    echo 'Use SKIP_GEE=0 SATELLITE_TRACK=both to measure them, or the default SATELLITE_ROUTING=s1_then_s2 (S1 then S2 fallback).' >&2
    exit 2
  fi
fi
if [[ "$SATELLITE_ROUTING" == "sits_then_track_a" ]]; then
  if [[ "$SKIP_GEE" == 1 ]]; then
    s2_status="SITS where cached Track B measured ($sits_measurements); Track A (S1, then S2 NDWI) elsewhere"
  elif [[ "$SATELLITE_TRACK" == "A" ]]; then
    s2_status='SITS from existing Track B measurements only (SATELLITE_TRACK=A runs no Track B); Track A elsewhere'
  else
    s2_status="SITS for every district Track B can measure now (SATELLITE_TRACK=$SATELLITE_TRACK SITS_BACKEND=$SITS_BACKEND); Track A elsewhere"
  fi
elif [[ "$SATELLITE_ROUTING" == "s1_then_s2" ]]; then
  s2_status='S2 NDWI fallback only (s1_then_s2: Sentinel-1 first; Track A S2 NDWI where S1 has no observation; no SITS)'
elif [[ "$SKIP_GEE" == 1 ]]; then
  s2_status="SITS from cache (sits_primary: reusing $sits_measurements; no new Track B measurement)"
else
  s2_status="SITS measured now (sits_primary: SATELLITE_TRACK=$SATELLITE_TRACK SITS_BACKEND=$SITS_BACKEND; S1_TO_SITS where SITS cannot measure)"
fi
echo 'CVND PRIMARY: event × district; legacy state caches are incompatible.'
export SITS_BLOCK_WORKERS SITS_MAX_INFLIGHT_REQUESTS SITS_MIN_INFLIGHT_REQUESTS SITS_BACKEND
echo "SKIP_GEE=$SKIP_GEE ARTICLE_PIPELINE_MODE=$ARTICLE_PIPELINE_MODE SKIP_COVARIATES=$SKIP_COVARIATES SKIP_ANALYSIS=$SKIP_ANALYSIS DRY_RUN=$DRY_RUN SATELLITE_TRACK=$SATELLITE_TRACK SATELLITE_ROUTING=$SATELLITE_ROUTING SITS_BACKEND=$SITS_BACKEND SITS_BLOCK_WORKERS=$SITS_BLOCK_WORKERS SITS_MAX_INFLIGHT_REQUESTS=$SITS_MAX_INFLIGHT_REQUESTS SITS_MIN_INFLIGHT_REQUESTS=$SITS_MIN_INFLIGHT_REQUESTS SITS_DOWNLOAD_ROUNDS=$SITS_DOWNLOAD_ROUNDS SITS_RETRY_WAIT=$SITS_RETRY_WAIT"
echo "S2/SITS: $s2_status"
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
  if [[ "$SATELLITE_TRACK" == "B" || "$SATELLITE_TRACK" == "both" ]]; then
    # Every district must finish Track B before the merge. A download round
    # leaves districts whose blocks failed (or that raised ERROR) for the next
    # run, so rounds repeat -- each one resumes only the unfinished districts --
    # until none remain. If some are still unfinished after
    # SITS_DOWNLOAD_ROUNDS rounds the pipeline stops before the merge.
    # [변경 2026-09-19] 전에는 덜 받은 구역이 있으면 watcher가 2를 반환해
    # 파이프라인이 바로 멈췄다. 지금은 여기서 자동 재다운로드(최대
    # SITS_DOWNLOAD_ROUNDS회, 회차 사이 SITS_RETRY_WAIT초)한 뒤에도 남으면
    # 멈춘다. "못 받은 구역" 판정은 scripts/track_b_pending.py가 하며, AOI
    # 매칭 실패 구역은 거기서 제외된다. 필요시 이 코드(회차/대기 기본값,
    # 멈춤 조건)와 track_b_pending.py의 판정 기준을 바꿀 것.
    round=1
    while :; do
      echo "Track B download round $round/$SITS_DOWNLOAD_ROUNDS"
      download_track_b
      if [[ "$DRY_RUN" == 1 ]]; then break; fi
      track_b_pending="$("$PYTHON" scripts/track_b_pending.py)"
      if [[ -z "$track_b_pending" ]]; then
        echo 'Track B: every district finished.'
        break
      fi
      if (( round >= SITS_DOWNLOAD_ROUNDS )); then break; fi
      echo "Track B: $(printf '%s\n' "$track_b_pending" | wc -l) district(s) unfinished; retrying in ${SITS_RETRY_WAIT}s"
      sleep "$SITS_RETRY_WAIT"
      round=$((round + 1))
    done
    if [[ "$DRY_RUN" == 1 || "$SITS_INFERENCE_WATCH" != 1 ]]; then
      run src/run_sits_inference.py
    fi
    if [[ -n "${track_b_pending:-}" ]]; then
      echo "Track B still unfinished after $SITS_DOWNLOAD_ROUNDS round(s); stopping before the merge." >&2
      echo 'Rerun the pipeline (or src/satellite.py --track B) to resume these districts:' >&2
      printf '%s\n' "$track_b_pending" | sed 's/^/  /' >&2
      exit 1
    fi
  fi
else
  echo 'Using district satellite caches only; missing artifacts fail explicitly.'
fi
# s1_then_s2: use S1 when observed and S2 NDWI only for missing-S1 districts.
# sits_primary: SITS (Track B) first; a district whose Track B is not finished
# stays missing (sits_pending), never S1, and compare_tracks.py decides the
# S1 -> SITS-NDWI converter for districts SITS cannot measure.
# The merge only reads flood_extent.csv and district_sits_measurements.csv; to
# compare routings later, rerun it alone with --routing X --output other.csv.
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
