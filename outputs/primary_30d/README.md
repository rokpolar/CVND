# CVND 30-day primary analysis package

The primary outcome counts district-explicit flood articles in `[onset, onset + 30 days)`.
The sensitivity outcome uses the nested 14-day window. Satellite flood exposure remains
the prespecified 14-day post-onset measurement.

- Primary input: `data/results/primary_30d/district_flood_articles.csv` (`9550241749512143d1302386f9aa8e1f1b3a915e7e5ee6e06eaa70429b15900f`, 1548 rows,
  1191 eligible)
- Sensitivity input: `data/results/sensitivity_14d/district_flood_articles.csv` (`75e245ed1bed5983be4398ca9bcf06caee52cfc2b7a0848b2513de7cec1d33ca`,
  1548 rows, 1069 eligible)
- Execution Git HEAD: `7865bb7f091f29c48439f224877d32c65ce6ab5f`
- Dirty worktree recorded: `true`
- Exact source inventory (including untracked files), source diff hash and dependency-lock hash are in `analysis_manifest.json`.
- This is an offline refit of the supplied joined inputs, not a new satellite/news collection.
- Registry derivation differences are recorded in `analysis_manifest.json`; additional
  unmeasured districts are not inserted as zero observations into the frozen cohort.
- `source_snapshot.zip` preserves all inventoried sources, including untracked files.

`key_results.csv` and `final_results_figure.png` are generated from the freshly fitted
primary and sensitivity model tables. Full reports and figures live in this directory
and `../sensitivity_14d/`.
