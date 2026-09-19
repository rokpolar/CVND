# CVND 30-day primary analysis package

The primary outcome counts district-explicit flood articles in `[onset, onset + 30 days)`.
The sensitivity outcome uses the nested 14-day window. Satellite flood exposure remains
the prespecified 14-day post-onset measurement.

- Primary input: `data/results/primary_30d/district_flood_articles.csv` (`3ff0313a2b8823528553124310c16b5ef272cd92f8a219087c088a626a2d8cc8`, 1553 rows,
  1191 eligible)
- Sensitivity input: `data/results/sensitivity_14d/district_flood_articles.csv` (`79281623bc814617ac6906f6c0c44168872f9bc45cc60212ada92810067d35bd`,
  1553 rows, 1069 eligible)
- Execution Git HEAD: `d8150c5c6302b85c4e0741435aec6eefece10aa5`
- Dirty worktree recorded: `true`
- Exact source inventory (including untracked files), source diff hash and dependency-lock hash are in `analysis_manifest.json`.
- This is an offline refit of the supplied joined inputs, not a new satellite/news collection.
- Registry derivation differences are recorded in `analysis_manifest.json`; additional
  unmeasured districts are not inserted as zero observations into the frozen cohort.
- `source_snapshot.zip` preserves all inventoried sources, including untracked files.

`key_results.csv` and `final_results_figure.png` are generated from the freshly fitted
primary and sensitivity model tables. Full reports and figures live in this directory
and `../sensitivity_14d/`.
