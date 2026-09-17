# CVND data layout

모든 production 경로는 `src/cvnd_layout.py`에서 관리한다. 분석 단위는 event×district이며 `event_id`만 있는 state cache를 district 관측으로 사용할 수 없다.

## External inputs

- `raw/EM-DAT-BASE.xlsx`: 공식 EM-DAT 원본
- `raw/census_2011_district_urban_rural.xlsx`: 공식 Census 2011 district urban/rural population 원본
- `raw/district_name_crosswalk.csv`: 외부 근거가 있는 행정구역 대응만 허용하는 명시적 crosswalk

`src/build_emdat_events.py`는 `intermediate/event_districts.csv` 하나만 생성한다. legacy `raw/events.csv`는 지원하지 않는다.

## Intermediate and cache artifacts

| Path | Contract |
| --- | --- |
| `intermediate/event_districts.csv` | `event_district_id` PK, parent/source/date/geography/evidence |
| `intermediate/district_covariates.csv` | Census total/urban/rural population, continuous urban share, match provenance |
| `intermediate/district_aoi.csv` | unique AOI status, geometry ID, area, `spec_version` |
| `cache/district/flood_extent.csv` | sensor-independent checkpoint; S1 and S2 attempt/observation fields |
| `intermediate/district_flood_combined.csv` | default S1→S2 route and all candidate areas/statuses |
| `intermediate/district_flood_area.csv` | selected area, AOI ratio, source/status/reason |
| `intermediate/district_gdelt.articles.jsonl.gz` | 30-day district-explicit candidate corpus |
| `cache/district/articles.sqlite` | retrieved article title/body/status |
| `intermediate/article_qa/` | requests, ledgers, results, two count windows and manifests |

S1은 모든 유효 AOI에서 먼저 실행하고 S1 면적 결측 키에만 S2를 실행한다. 유한한 S1 `0 km²`는 성공이다. optional Track B/SITS 파일은 `cache/district/sits_patches/`와 `sits_scores/`에만 저장한다.

## Canonical result trees

```text
results/primary_30d/
  district_flood_articles.csv
  district_analysis_exclusions.csv
  district_qc.json
  district_selection_bias.csv
  coverage_model_results.csv
  coverage_predictions.csv
  coverage_scores.csv
  coverage_oof_diagnostics.csv

results/sensitivity_14d/
  # same schemas, window_days=14

../outputs/primary_30d/
../outputs/sensitivity_14d/
```

Joined tables retain every registry row and `exclusion_reason`. `complete` and lower-bound `partial` article states are observations; `incomplete` is missing. Primary rows must all have `window_days=30`, sensitivity rows `window_days=14`. Analysis refuses missing or mixed window values.

`outputs/primary_30d/analysis_manifest.json` records input hashes, row/eligible counts, Git provenance and dependency-lock hash. Flat result/output files and `sensitivity_30d/` are legacy and must not be regenerated.
