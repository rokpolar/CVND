# 사건 × district 상대적 보도량 점수

이 기능은 정답 라벨을 학습하는 분류기가 아니다. 현재 GDELT 색인, 접근 가능한 기사 본문 및 기존 flood-keyword heuristic 아래의 **관측 기사 수**를 예측하고, 그 분포에 비해 낮거나 높은 관측을 탐색적 후보로 표시한다. 사회적으로 마땅한 보도량, 인과적 차별, 언론의 의도적 외면을 추정하지 않는다. 기존 H1/H2 `FORMULAS`, `adjusted_predictions()`와 `coverage_predictions.csv`는 별도 분석으로 유지된다.

## 입력과 모형

기본 입력은 `data_path("district_flood_articles")`이다. 기존 `analysis_eligible`을 그대로 적용한다. `prepare_analysis()`의 기존 완전사례 계약(urban_population_share 포함)을 유지하며 total_population > 0, 유효 날짜, 비어 있지 않은 source_record_id를 추가 검사한다. event_district_id는 전체 행에서 비어 있지 않고 유일해야 한다. 기사 수는 유한한 0 이상 정수이고 침수면적은 유한한 0 이상 값이다. 적격 플래그와 제외 사유 또는 제공된 join 품질 감사 열의 모순은 오류다. CSV 식별자는 문자열로 읽는다. 식별자 양끝 공백은 자동 정규화하지 않고 오류로 보고한다.

전체 입력 열·행·행 순서 및 exclusion_reason을 보존한다. 수집 실패·미실행·본문 누락·위성 결측을 0으로 바꾸지 않는다. 관측된 실제 0건은 적격이면 학습과 점수 산출에 포함한다. standalone 입력은 기존 분석 필수 열과 total_population을 요구한다. join 감사 열이 제공되면 district/AOI/수집/위성/Census 상태, 면적 상한, 인구 합계 및 중복 지리 식별자도 확인한다. 감사 열 생략은 upstream 매칭·수집 기준을 완화할 수 있는 허가가 아니다.

```text
article_count ~ log_flood_area + log_population + year_c
log_flood_area = log1p(flood_area_km2)
log_population = log(total_population / 1_000_000)
year_c = start_date.year - 2020
Var(Y|X) = mu + alpha * mu^2
```

절편을 포함한다. 기존 `fit_nb()`를 재사용하여 statsmodels formula `negativebinomial(..., loglike_method="nb2", missing="raise")` 최대우도로 beta와 alpha를 추정한다. alpha를 고정하지 않는다. Census 2011 총인구는 피해·노출 인구가 아니며 계수를 추정한다. 인구 offset도, 고정 14일 관측창에 대한 기간 offset도 없다. 도시화율, income_group, 주/district/source 고정효과, MSS/PSS, 기사 수에서 파생한 변수는 기대량 모형에 넣지 않는다.

전체 적격 표본이 단일 연도이면 모든 fold에서 연도 항을 동일하게 제외한다. 다년 표본의 train fold에 단일 연도만 있으면 rank 결손으로 실패하며 해당 fold만 식을 바꾸지 않는다. 계수 부호에 따라 표본 또는 모형을 선택하지 않는다.

## 재현 가능한 그룹 OOF

적격 행을 문자열 `(source_record_id, event_district_id)` 순으로 정렬하고 `GroupKFold(n_splits=5)`를 적용한다. 같은 source의 모든 state/district는 같은 fold에 들어간다. train/test source 교집합이 없고 각 적격 행이 정확히 한 번 test로 배정됨을 실행 중 검사한다. 각 fold의 beta/alpha는 train에서만 추정한다. held-out y는 해당 fold의 mu/alpha에 영향을 주지 않는다. 라이브러리 버전이 같은 환경에서 입력 순서를 바꿔도 키별 결과가 같다.

| 운영 설정 / CLI | 기본값 |
| --- | --- |
| `--min-rows` | 적격 50행 |
| `--min-sources` | 적격 source 10개 |
| `--min-train-rows` | train 30행 |
| `--min-train-sources` | train source 5개 |
| `--rows-per-parameter` | 추정 모수당 5행 |
| `--tail-threshold` | 0.05 |
| n_splits | 5, 고정 |

train 최소 행 수는 `max(min_train_rows, rows_per_parameter × 모수 수)`이다. 절편과 NB2 alpha를 모수 수에 포함한다(다년 주 NB2는 5개). 기존 `fit_nb()`의 최소 20행/모수당 5행 및 outcome variation 검사도 유지되므로 운영값을 낮춰도 기존 수치 안정성 제한을 우회하지 않는다. 최소 source 수는 분할 수 이상이어야 한다. 이는 조정 가능한 보수적 운영 기준이며 통계적 검정력 보장이 아니다. 모든 설정은 summary에 저장한다.

수렴, full rank, 유한 계수·공분산, 양의 alpha, 유한 양의 예측 및 유한 점수·진단을 검사한다. 적합/수치 실패는 fold별 사유로 남긴다. 주 NB2 실패를 전체 표본 적합값이나 Poisson으로 대체하지 않는다. 설명용 전체 표본 최종 적합은 수행하지 않는다.

## 점수와 이산 꼬리확률

유효 OOF 예측만 다음 값을 갖는다.

```text
expected_article_count_oof = mu
coverage_difference = y - mu
coverage_ratio = y / mu
pearson_residual = (y - mu) / sqrt(mu + alpha * mu^2)
n = 1 / alpha
p = 1 / (1 + alpha * mu)
p_lower = scipy.stats.nbinom.cdf(y, n, p)       # P(Y <= y)
p_upper = scipy.stats.nbinom.sf(y - 1, n, p)   # P(Y >= y), 관측값 포함
predictive_low_90, predictive_high_90 = nbinom.ppf([.05, .95], n, p)
```

- `p_lower <= tail_threshold AND y < mu`: `relative_under_candidate`
- `p_upper <= tail_threshold AND y > mu`: `relative_over_candidate`
- 나머지 성공 OOF: `within_expected_range`
- 제외·자료 부족·적합 실패: `not_scored`

Pearson 잔차는 정규 z-score가 아니며 ±1.96으로 분류하지 않는다. 이산 CDF를 연속 백분위처럼 해석하지 않는다. 작은 mu와 y=0에서 높은 CDF는 과대보도 근거가 아니다. 상측 꼬리는 `sf(y-1)`이며 0건에서는 1이다. 예측구간은 **개별 count의 중앙 90% plug-in 예측구간**이며 평균의 confidence interval이 아니다. 이산성 때문에 실제 포함률은 정확히 90%일 필요가 없다. beta/alpha 추정 불확실성을 추가 반영하지 않는다. 후보는 다중검정 보정된 발견이나 확정 판정이 아니며 양쪽 후보 비율을 같게 하거나 일정 비율을 선발하지 않는다.

`extrapolation_flag`는 주 모형 설명변수 중 하나라도 해당 train의 주변 최소/최대 범위 밖이면 True이다. 성공 점수에만 기록하고 나머지는 결측이다. 결합 설명변수 공간의 support 검사가 아니며 이 flag로 자동 제외하지 않는다.

## 예측 검증과 민감도

동일 표본·fold·설명변수 Poisson은 진단용 비교만 수행한다. NB2와 Poisson 모두 성공한 test 행에서만 성능을 비교하고 공통 행 수·source 수·전체 적격 대비 비율을 명시한다. 모형별 독립 가용 지표도 별도 저장하여 혼동을 방지한다. fold별 train/test 크기, source 목록/수, 수렴, alpha, 경고, 실패 이유 및 계수를 summary에 저장한다.

각 가용 모형과 공통 비교 범위에 MAE, 평균 negative log predictive probability, 중앙 90% 구간 포함률·평균 폭, 실제 0건 비율·평균 예측 P(Y=0)을 보고한다. 행별 동일 가중 평균(`row_weighted`)과 source 내 평균을 낸 후 source를 동일 가중한 평균(`source_macro`)을 구분한다. 후자는 source 합산 count에 대한 likelihood가 아니다. OOF 예상량의 최대 10개 quantile 구간별 N/범위/실제 평균/예상 평균을 `calibration`에 저장한다. 동일 예상량은 같은 구간에 두고 중복 경계는 제거한다. 실제-vs-예상 및 calibration 그림은 주 NB2 가용 행을 사용한다. marginal 분산 > 평균만으로 조건부 과산포를 입증했다고 주장하지 않는다.

`--sensitivity-no-population`은 같은 적격 표본과 같은 fold에서 log_population만 뺀 NB2를 추가한다. `no_population_` 접두사의 별도 점수 열, 모형별 fold 상태·진단 및 공통 성공 범위를 남긴다. 민감도 summary는 두 signed Pearson 잔차의 Spearman 순위 상관, 잔차 부호 변화율, 후보 라벨 변화율과 전이 건수를 보고한다. 실패한 민감도 결과는 결측/`not_scored`이다. 주 점수와 공식은 변경하지 않으며 유리한 결과로 모형을 선택하지 않는다.

## 실행과 출력

```bash
python src/score_coverage.py
python src/score_coverage.py --input data/results/district_flood_articles.csv \
  --results-dir /tmp/cvnd-scoring-audit/results \
  --output-dir /tmp/cvnd-scoring-audit/outputs --sensitivity-no-population
bash scripts/run_pipeline.sh --dry-run
```

pipeline은 기존 H1/H2 분석 다음 scorer를 실행한다. `SKIP_ANALYSIS=1`이면 두 분석을 모두 생략한다. 기존 `--dry-run`은 실행 계획·오프라인 preflight만 수행하며 적합·외부 접근·산출물 교체가 없다. scorer 자체는 외부 쿼리, 연구자료 다운로드 또는 인증을 수행하지 않는다.

| 파일 | 내용 |
| --- | --- |
| `data/results/coverage_scores.csv` | 모든 원래 열·행·제외 사유 + fold_id, scoring_status, scoring_reason, expected_article_count_oof, alpha_oof, coverage_difference, coverage_ratio, pearson_residual, p_lower, p_upper, predictive_low_90, predictive_high_90, coverage_class, extrapolation_flag |
| `data/results/coverage_oof_diagnostics.csv` | 성공한 model × test 행별 fold, 키, 관측/예상/alpha, 오차, 음의 log 확률, 구간·포함 여부·폭, 관측 0·예측 0 확률 |
| `outputs/coverage_scoring_summary.json` | 공식·변환·설정, 읽은 입력 바이트 SHA-256, 가능할 때 Git SHA, 라이브러리 버전, N/source, 결측·제외·실패 사유, fold, OOF 비교·calibration·한계 |
| `outputs/coverage_scoring_report.md` | 가용성, 설정/출처, 진단, fold, 해석 한계 |
| `outputs/coverage_scoring_actual_vs_expected.png`, `coverage_scoring_calibration.png` | 별도 주 NB2 OOF 그림; N=0이면 명시적 가용성 안내 |

`scoring_status`는 `scored` 또는 `not_scored`이다. `scoring_reason`은 input 제외, 자료 부족, 구체적 fold 실패 또는 OOF 성공을 기록한다. summary 상태는 전체 최소조건 미달 `insufficient_data`, 전부 성공 `available`, 일부 주 fold 성공 `partially_available`, 적합 가능한 크기이나 주 fold 전부 실패 `unavailable`이다. Poisson/민감도 가용성은 각 모형 상태로 구분한다. JSON 비유한 값은 null, CSV 결측은 빈 셀이다.

N=0이면 적합하지 않고 전체 행을 보존하며 모든 예상량·점수·확률·구간은 결측이다. 실증 성능·계수·지역 순위를 만들지 않는다. 재실행 시작 시 scorer 소유 6개 산출물만 무효화하고 새 결과로 교체한다. 입력/실행 오류 시 불완전 출력도 제거하고 `status=error` summary를 기록하며 비정상 종료한다. raw/intermediate 및 기존 H1/H2 산출물은 변경하지 않는다. 동시에 같은 출력 경로를 쓰는 실행은 지원하지 않는다.

## 검증

`tests/test_coverage_scoring.py`는 NB2 합성자료에서 계수/alpha 회복, source 분리와 정확히 한 번의 OOF, held-out y 변경 불변성, 행 순서 재현성, 결측과 0 구분, 분포 변환·양쪽 꼬리·0 경계, 자료 부족·공선성·수렴/공분산 실패, 부분 실패와 공통 비교, source 평균, 민감도 분리, CLI/JSON null/오래된 출력 제거, 그림 생성 및 pipeline skip/dry-run 계약을 검증한다. 합성자료는 테스트 임시 디렉터리에만 사용한다. 실제 joined table 검증과 전체 테스트 결과는 `docs/implementation_validation.md`에 별도로 기록한다.
