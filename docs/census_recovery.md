# Census demographic recovery

The supplementary input is `data/raw/district_census_recovery.json`.
It fills unmatched regions only; the original Census workbook and the existing
name crosswalk are preserved. No confidence scores are stored.

## Methods

- `census_name_link`: retrieve population from the original 2011 PCA district
  through an explicitly cited name equivalence or historical state affiliation.
- `official_retabulation`: use a government-published 2011 total, rural and urban
  population table for a district created after the original Census geography.
  Urban share is calculated as urban population / total population.

Every record carries reviewed event IDs, a source URL, notes and Census year.
The population sum must reconcile exactly. Missing components, another Census
year, unsupported methods and duplicate recovery records fail validation.
No state-average imputation, area weighting or parent-district proxy is used.
Unreviewed events remain unlinked. Where specified, boundary date limits apply
to all events sharing the geography; mixed periods are not silently collapsed.

Telangana's September 2016 event uses the original Andhra Pradesh PCA geography
for Karimnagar, Medak and Warangal, before the October 2016 reorganisation.
Later Telangana entries use the government's 2023 Outlook, Annexure 18.
Assam uses Statistical Abstract 2021, Table 1.02. Meghalaya uses Statistical
Handbook 2023 (final September 2024 version), Table 1.03, rather than conflicting
provisional values on district websites. Namsai and Balod use district government
tables. For Balod, rural population is derived as total minus urban.

The output uses the existing `matched_crosswalk` status, with the method and
source in `source`. Retabulated units have an explicitly prefixed
`retabulated:` identifier, NOT an invented numeric Census 2011 district code.
Two names referencing the same Census geography in the same event are marked
ambiguous by the downstream join. West Karbi Anglong / West Karbi-Anglong in
E081 is one such duplicate; the registry itself is not modified here.

The current regenerated lookup contains 506 linked regions out of 566 (39
additional recoveries), leaving 60 unlinked regions / 128 event-district rows.
The join identifies 14 rows in seven same-event alias pairs as ambiguous,
including pre-existing aliases such as Badaun/Budaun and Mumbai/Mumbai City.
After that duplicate safeguard, 1,488 of 1,630 rows have usable Census links.

## Scope limitations

These are 2011 demographic references, not population estimates at flood dates.
Matching names and reported administrative areas does not prove equality with
the satellite polygon. The GAUL/Census/event boundary alignment still requires
separate spatial validation, particularly for districts changed after the
source publication. Existing name-matched regions are not re-audited by this
supplement. District labels that denote towns/subdistricts (e.g. Jogbani and
Chengannur) must not be filled using an entire parent district.

Morbi's district webpage has a three-person discrepancy between its total and
urban+rural population. Palghar's government sources report conflicting totals
and urban shares. Neither was automatically reconciled. Some official PDF
endpoints timed out; unavailable or conflicting evidence is not treated as zero.

## Rebuild without satellite or LLM calls

```bash
venv/bin/python src/build_district_covariates.py --unmatched-output data/results/census_unmatched_districts.csv
venv/bin/python src/join_district_flood_articles.py --audit-missing
venv/bin/python src/analyze_coverage_disparity.py
venv/bin/python src/score_coverage.py
```

The normal pipeline enables this supplement by default. `--no-recovery` opts out.
The library function accepts an explicit `recovery_path`; omitting it preserves
the previous library behavior. Satellite and article missingness remain intact.
