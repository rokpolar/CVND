#!/usr/bin/env python3
"""Build the canonical 30-day primary package from freshly fitted outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRIMARY_DATA = ROOT / "data/results/primary_30d"
SENSITIVITY_DATA = ROOT / "data/results/sensitivity_14d"
PRIMARY_OUTPUT = ROOT / "outputs/primary_30d"
SENSITIVITY_OUTPUT = ROOT / "outputs/sensitivity_14d"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def input_record(path: Path, expected_window: int) -> dict:
    frame = pd.read_csv(path)
    windows = sorted(pd.to_numeric(frame.window_days, errors="raise").astype(int).unique())
    if windows != [expected_window]:
        raise ValueError(f"{path} has window_days={windows}, expected {expected_window}")
    eligible = frame.analysis_eligible.astype(str).str.lower().isin({"true", "1"})
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "rows": len(frame),
        "eligible_rows": int(eligible.sum()),
        "window_days": expected_window,
    }


def preferred_rows(path: Path, label: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    chosen = []
    for model in ("model_2", "model_3"):
        for term in ("log_flood_area", "urban_population_share"):
            candidates = frame[(frame.model == model) & (frame.term == term)]
            if candidates.empty:
                continue
            clustered = candidates[candidates.se_type == "state_clustered"]
            row = (clustered if not clustered.empty else candidates).iloc[0].copy()
            row["analysis"] = label
            row["effect"] = "Flood area" if term == "log_flood_area" else "Urban share (+10 pp)"
            if term == "urban_population_share":
                row["effect_size"] = row["irr_10pp"]
                row["effect_low"] = row["irr_10pp_ci_low"]
                row["effect_high"] = row["irr_10pp_ci_high"]
            else:
                row["effect_size"] = row["irr"]
                row["effect_low"] = row["irr_ci_low"]
                row["effect_high"] = row["irr_ci_high"]
            chosen.append(row)
    return pd.DataFrame(chosen)


def write_figure(key_results: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    view = key_results.reset_index(drop=True)
    labels = [f"{row.analysis}\n{row.model}: {row.effect}" for row in view.itertuples()]
    y = list(range(len(view)))
    values = view.effect_size.astype(float)
    low = values - view.effect_low.astype(float)
    high = view.effect_high.astype(float) - values
    colors = ["#276779" if value == "30-day primary" else "#94a3b8"
              for value in view.analysis]
    fig, ax = plt.subplots(figsize=(8, max(4.5, len(view) * .65)), constrained_layout=True)
    for i, color in enumerate(colors):
        ax.errorbar(values.iloc[i], y[i], xerr=[[low.iloc[i]], [high.iloc[i]]],
                    fmt="none", ecolor=color, elinewidth=2, capsize=4)
    ax.scatter(values, y, c=colors, s=42, zorder=3)
    ax.axvline(1.0, color="black", linewidth=1, linestyle="--")
    ax.set(yticks=y, yticklabels=labels, xlabel="Incidence-rate ratio (95% CI)",
           title="CVND: 30-day primary and 14-day sensitivity")
    ax.invert_yaxis()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)


def main() -> int:
    primary_input = PRIMARY_DATA / "district_flood_articles.csv"
    sensitivity_input = SENSITIVITY_DATA / "district_flood_articles.csv"
    required = [
        primary_input, sensitivity_input,
        PRIMARY_DATA / "coverage_model_results.csv",
        SENSITIVITY_DATA / "coverage_model_results.csv",
        PRIMARY_OUTPUT / "coverage_summary.json",
        SENSITIVITY_OUTPUT / "coverage_summary.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Run both joins and analyses first: " + ", ".join(missing))

    primary = input_record(primary_input, 30)
    sensitivity = input_record(sensitivity_input, 14)
    lock = ROOT / "requirements-lock.txt"
    diff = git("diff", "--no-ext-diff", "--", "src", "scripts", "requirements.txt",
               "requirements-lock.txt", "README.md", "docs", "PROJECT_CONTEXT.md")
    provenance = {
        "schema_version": 1,
        "primary": primary,
        "sensitivity": sensitivity,
        "git_head": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "source_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "requirements_lock_sha256": sha256(lock),
    }
    PRIMARY_OUTPUT.mkdir(parents=True, exist_ok=True)
    (PRIMARY_OUTPUT / "analysis_manifest.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )

    key_results = pd.concat([
        preferred_rows(PRIMARY_DATA / "coverage_model_results.csv", "30-day primary"),
        preferred_rows(SENSITIVITY_DATA / "coverage_model_results.csv", "14-day sensitivity"),
    ], ignore_index=True)
    columns = ["analysis", "model", "se_type", "effect", "term", "effect_size",
               "effect_low", "effect_high", "p_value", "n"]
    key_results[columns].to_csv(PRIMARY_OUTPUT / "key_results.csv", index=False)
    write_figure(key_results, PRIMARY_OUTPUT / "final_results_figure.png")

    readme = f"""# CVND 30-day primary analysis package

The primary outcome counts district-explicit flood articles in `[onset, onset + 30 days)`.
The sensitivity outcome uses the nested 14-day window. Satellite flood exposure remains
the prespecified 14-day post-onset measurement.

- Primary input: `{primary['path']}` (`{primary['sha256']}`, {primary['rows']} rows,
  {primary['eligible_rows']} eligible)
- Sensitivity input: `{sensitivity['path']}` (`{sensitivity['sha256']}`,
  {sensitivity['rows']} rows, {sensitivity['eligible_rows']} eligible)
- Execution Git HEAD: `{provenance['git_head']}`
- Dirty worktree recorded: `{str(provenance['git_dirty']).lower()}`
- Exact source diff hash and dependency-lock hash are in `analysis_manifest.json`.

`key_results.csv` and `final_results_figure.png` are generated from the freshly fitted
primary and sensitivity model tables. Full reports and figures live in this directory
and `../sensitivity_14d/`.
"""
    (PRIMARY_OUTPUT / "README.md").write_text(readme, encoding="utf-8")
    print(f"Built canonical package: {PRIMARY_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
