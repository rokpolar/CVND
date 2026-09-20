# Track A 전체 대비 Track B 35구역 sensitivity

## 역할

이 디렉터리는 production 결과를 대체하지 않는 위성 측정 sensitivity다. Production primary는 전체 registry에 Track A `s1_then_s2`를 적용한 `data/results/primary_30d/`와 `outputs/primary_30d/`이다. 여기서는 기존 feasibility 조사에서 다음 조건을 모두 만족한 35개 event×district만 Track B/SITS로 교체했다.

- `aoi_status == matched`
- `sr_status == ok`
- `sr_usable_frac >= 0.4`
- 현재 event×district registry에 존재

기사 후보·본문·heuristic·LLM-QA 결과는 frozen 상태 그대로 사용했다. Track B는 14일 위성 관측창, 뉴스 반응은 30일 primary를 사용한다.

## 완료 상태

- Track A canonical: 1,548행, 분석 가능 1,198행
- Track B cohort: 35/35 H5 준비 및 SITS 추론 완료
- Track B route: `SITS_NDWI` 31행, `SITS_NDWI_RESTORED` 4행
- Track B 적용 후 전체 분석 가능 표본: 1,198행
- 기사 수·도시화율·분석 포함 여부는 Track A 입력과 동일

## Track A와 Track B 면적 비교

| 지표 | Track A | Track B |
| --- | ---: | ---: |
| 35구역 면적 합계 | 8,953.8953 km² | 2,701.1158 km² |
| 중앙값 | 83.4515 km² | 16.4317 km² |
| Track B/Track A 비율 중앙값 | — | 0.2814 |
| 더 작은 Track B 관측 | — | 32/35 |
| 더 큰 Track B 관측 | — | 3/35 |

SITS는 clear optical footprint와 NDWI/SITS gate 위에서 면적을 산출하므로 S1 new-water 면적과 같은 측정량으로 간주하면 안 된다. 이 차이는 Track B가 더 정확하다는 증거가 아니라 센서·가용영역·분류 규칙의 차이다.

## 분석 결론

35개 위성값을 Track B로 교체해 30일 분석을 다시 적합해도 결론은 유지됐다.

- Spearman rho: Track A `0.1538`, Track B overlay `0.1513`
- Model 2 state-clustered flood coefficient: `-0.0126`, `p=0.9031` — H1 미지지
- Model 2 state-clustered urban coefficient: `1.3837`, `p=0.0041`
- 도시화율 10%p 증가 IRR: `1.148` (95% CI `1.049–1.258`) — H2만 지지

35개는 광학 사용 가능성이 높은 선택 표본이다. SITS-only 하위표본 계수는 표본 선택과 작은 N의 영향을 받으므로 주 결론이나 인과효과로 해석하지 않는다.

## 파일

- `data/results/track_b_35_sensitivity/cohort.csv`: 고정 35구역 목록
- `district_sits_measurements.csv`: H5/checkpoint/source commit hash를 포함한 durable 측정값
- `district_flood_combined.csv`: 35개 SITS routing 결과
- `district_flood_area.csv`: 35개 분석용 면적표
- `district_flood_articles_30d.csv`: canonical 30일 입력에서 위성 열만 35개 교체한 1,548행 입력
- `track_a_vs_track_b.csv`: 구역별 S1/SITS 면적과 차이
- `manifest.json`: 조건·행 수·분포·SHA-256
- `paper_results.md`, `coverage_summary.json`, 그림: Track B overlay 전체 분석

원시 H5 패치(약 175GB)와 NPZ score cache(약 66MB)는 `data/cache/`에 있으며 Git에는 올리지 않는다. 측정 결과를 재병합하려면 다음을 실행한다.

```bash
PYTHONPATH=src venv/bin/python scripts/build_track_b_35_package.py
venv/bin/python src/analyze_coverage_disparity.py \
  --input data/results/track_b_35_sensitivity/district_flood_articles_30d.csv \
  --results-dir data/results/track_b_35_sensitivity/analysis \
  --output-dir outputs/track_b_35_sensitivity
```
