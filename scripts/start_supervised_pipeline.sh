#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${PIPELINE_LOG:-$ROOT/pipeline_run.log}"
REPORT="${PIPELINE_REPORT:-$ROOT/pipeline_supervision_report.md}"
PID_FILE="${PIPELINE_PID_FILE:-$ROOT/pipeline_supervision.pids}"
nohup setsid env SETUP_DEPS=0 SKIP_GEE=0 ARTICLE_PIPELINE_MODE=frozen SATELLITE_TRACK=A SATELLITE_ROUTING=s1_then_s2 SKIP_COVARIATES=0 SKIP_ANALYSIS=0 "$ROOT/scripts/run_pipeline.sh" >"$LOG" 2>&1 < /dev/null &
pipeline_pid=$!

nohup setsid "$ROOT/venv/bin/python" "$ROOT/scripts/monitor_pipeline.py" --pid "$pipeline_pid" --log "$LOG" --report "$REPORT" --interval 300 >"${PIPELINE_MONITOR_LOG:-$ROOT/pipeline_monitor.log}" 2>&1 < /dev/null &
monitor_pid=$!

printf '%s %s\n' "$pipeline_pid" "$monitor_pid" >"$PID_FILE"
printf 'pipeline_pid=%s monitor_pid=%s\n' "$pipeline_pid" "$monitor_pid"
