# CVND 30-day primary analysis package

The primary outcome counts district-explicit flood articles in `[onset, onset + 30 days)`.
The sensitivity outcome uses the nested 14-day window. Satellite flood exposure remains
the prespecified 14-day post-onset measurement.

- Primary input: `data/results/primary_30d/district_flood_articles.csv` (`59f3ede8c5fee2b7e9bab068a8a0729a01f4765538804ccd614238af56c963e5`, 1548 rows,
  1198 eligible)
- Sensitivity input: `data/results/sensitivity_14d/district_flood_articles.csv` (`7262ac312d7e41f183e08ea3cf250c8ba74925bbfb3a78fce44f71a3da0a1c48`,
  1548 rows, 1074 eligible)
- Execution Git HEAD: `4f7a28e5b41b390fc2aabe77db46b713a4cbe2c4`
- Dirty worktree recorded: `true`
- Exact source inventory (including untracked files), source diff hash and dependency-lock hash are in `analysis_manifest.json`.
- This is an offline refit of the supplied joined inputs, not a new satellite/news collection.
- Registry derivation differences are recorded in `analysis_manifest.json`; additional
  unmeasured districts are not inserted as zero observations into the frozen cohort.
- `source_snapshot.zip` preserves all inventoried sources, including untracked files.

`key_results.csv` and `final_results_figure.png` are generated from the freshly fitted
primary and sensitivity model tables. Full reports and figures live in this directory
and `../sensitivity_14d/`.
