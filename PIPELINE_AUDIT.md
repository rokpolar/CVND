# CVND 파이프라인 감사 — 방법론·코드 문제와 수정 후보

작성: 2026-07-30 · 대상 커밋 상태: `data/`, `src/`, `outputs/` 현재 산출물 기준
성격: **진단 문서.** 초기 진단 시점의 상태와 이후 반영된 수정사항을 함께 기록합니다. 각 항목은 재현 가능한 근거 수치를 함께 적었습니다.

---

## 0. 한눈에 보기

| # | 위치 | 문제 | 심각도 | 결과에 미치는 영향 |
| --- | --- | --- | --- | --- |
| [1](#1) | `src/archive/build_events_emdat.py` | 이벤트 좌표가 **주(state) bbox 중심점** → AOI가 주별로 고정된 1개 구역 | 치명 | PSS 전체가 홍수 위치와 무관한 값일 수 있음 |
| [2](#2) | `src/compute_population.py` → `compute_pss.py` | `population_exposed = 면적 × 주평균밀도` → PSS 두 성분이 사실상 동일 변수 | 치명 | "면적+인구" 가중평균이 면적 중복계산 |
| [3](#3) | `data/gdelt_bq.json` | 기사 집계창이 `onset−3d ~ end+14d`(가변) → 문서의 "onset+14d" 아님 | 치명 | y가 사건 기간에 기계적으로 비례, offset 없음 |
| [4](#4) | `src/compute_mss.py` | `S_TTFR` 164/167이 1.0(상수), `S_CD`는 사건 기간의 대리변수 | 높음 | MSS 4개 지표 중 2개가 무정보/물리량 누출 |
| [5](#5) | `src/compute_mss.py` | `S_vol`과 `S_sov`가 Spearman 1.000(완전 중복) + AHP가 둘에 0.75 | 높음 | MSS ≈ 기사수 단조변환(ρ=0.970) |
| [6](#6) | `src/compute_expected_coverage.py` | `log_ratio`는 표본 내 잔차 → "절대적 과소보도"가 아님, 0 기준선이 편향 | 높음 | "62.1% 과소보도"는 변환 인공물 |
| [7](#7) | `src/merge_results.py` | 한 변수에 4가지 관측방식 혼합(S1/NDWI/SITS+NDWI/restored) 보정 없음 | 높음 | 소스별 평균 log_ratio −0.66 ~ +0.31 |
| [8](#8) | `src/archive/build_events_emdat.py` | `income_group` 하드코딩(시킴·히마찰·우타라칸드 = Low) | 높음 | 핵심 주장(소득 격차)의 설명변수가 부정확 |
| [9](#9) | `compute_expected_coverage.attach_deaths_from_emdat` | 부분문자열 매칭 + `max()` + 결측 0 대입 | 중간 | 사망자 계수 편향, 결측 23/132 |
| [10](#10) | `src/satellite.py` | 관측창·해상도 불일치(7d/14d, 30m/10m), median 합성으로 피크 희석 | 중간 | 면적 과소추정, 지역별 편향 |
| [11](#11) | `compute_pss.py` / `compute_mss.py` | MinMax 정규화로 점수가 표본 의존 | 중간 | 이벤트 추가 시 모든 점수 변동 |
| [12](#12) | 코드 버그 모음 | `result.scale` 오용, tie rank `astype(int)`, AssertionError 위험 등 | 중간~낮음 | 진단값 오류, 런타임 중단 위험 |
| [13](#13) | 재현성 | requirements 핀 없음, SITS 채점 코드 미포함 | 중간 | 환경에 따라 결과 재현성 저하 |

---

<a id="1"></a>
## 1. [치명] 위성 AOI가 홍수 위치가 아니라 "주 중심 구역"에 고정됨

**위치**: `src/archive/build_events_emdat.py` L≈400 (`bbox_center_lat/lon`), `src/satellite.py:222 get_region()`

**현재 상태 — 해결됨**: 분석 단위를 공식 `DisNo. × state/UT`로 재정의했고
`get_region()`은 FAO GAUL level-1 주 경계를 직접 선택합니다. AOI 면적과
cloud QA도 각각 `event_aoi_area.csv`, `post_cloud.csv`로 같은 주 경계를
사용하며, 과거 district 기반 캐시는 삭제했습니다.

**문제**
`build_events_emdat.py`는 신규 이벤트의 좌표를 EM-DAT 좌표가 아니라 하드코딩된 **주 단위 bbox의 기하 중심**으로 생성합니다.

```python
new_df['lat'] = new_df['bbox'].apply(bbox_center_lat)   # bbox = STATE_BBOX[state]
new_df['lon'] = new_df['bbox'].apply(bbox_center_lon)
```

그리고 `get_region()`은 "그 좌표를 포함하는 GAUL level-2 구역"을 AOI로 씁니다. 즉 같은 주의 모든 이벤트가 **같은 구역**을 측정합니다.

**근거**
- `events.csv` 30개 주 중 **20개 주가 단일 구역**만 사용. 이벤트가 2개 이상이면서 구역이 1개인 주 19개.
- 구자라트 9건 전부 `Surendranagar`, 우타라칸드 11건 전부 `Chamoli`, 타밀나두 7건 전부 `Karur`, 서벵골 7건 전부 `Birbhum`, UP 13건은 `Sitapur`/`Bahraich` 2개.
- `flood_combined.district_km2`가 22개 주에서 주 내 유일값 → 분모도 고정.
- `events.csv`의 `district` 열(EM-DAT 텍스트에서 파싱)과 실제 측정 구역이 일치한다는 보장이 없음. J&K 이벤트의 district는 `72811`(숫자 코드)이 그대로 남아 있음(E67 quarantine).

**왜 치명적인가**
케랄라 2018 홍수와 케랄라 2021 홍수의 물리적 심각도가 동일한 Thrissur 구역의 물 면적으로만 구분됩니다. 실제 침수가 다른 구역에서 발생했다면 PSS는 신호가 아니라 노이즈이고, 기대보도량 모형의 유일한 물리 설명변수가 무의미해집니다.

**수정 후보**
- **A (권장)**: EM-DAT `Admin Units`의 `adm2_name`(구역명)을 GAUL level-2와 이름 매칭 → 매칭된 구역 폴리곤들의 **합집합**을 AOI로. 다중 구역 사건이면 구역별 측정 후 합산. 매칭 실패 이벤트는 quarantine(주 중심 대체 금지).
- **B**: 사건 단위를 **주-사건**으로 정직하게 재정의하고 AOI = 주 전체 폴리곤. 계산량은 늘지만 미디어 단위(주 단위 GDELT 질의)와 분석 단위가 일치해 오히려 정합적임.
- **C (최소 수정)**: 현 구조를 유지하되 `severity_raw`에 `aoi_is_state_centroid` 플래그를 넣고, 모형에 구역 고정효과를 넣어 "주 내 시간 변동"만 사용. 단, 주별 이벤트 수가 1–2건인 주는 소실.
- 어느 안이든 `events.csv`에 `aoi_source`(emdat_adm2 / state_centroid / manual) 컬럼을 남겨 감사 가능하게 할 것.

---

<a id="2"></a>
## 2. [치명] PSS의 "노출 인구"가 면적의 결정론적 변환 — 중복계산

**위치**: `src/compute_population.py:from_flood_combined()`, `src/compute_pss.py`

**문제**
```python
exposed = round((flood_km2 / state_area) * state_pop)
```
따라서 `population_exposed ≡ 침수면적 × (주 인구/주 면적)`. 주 안에서는 밀도가 상수이므로 인구 항은 면적 항의 단조 변환입니다. PSS는 `0.5·MinMax(log1p(면적)) + 0.5·MinMax(log1p(인구))`로 사실상 면적을 두 번 세고, 주 간 차이는 "주 평균 인구밀도"라는 상수만 반영합니다.

**근거**
- `|population_exposed − 면적×주밀도|`의 최댓값 = **0.499** (반올림 오차).
- 주별 Spearman(면적, 인구노출) 중앙값 = **1.000**, 최솟값 = 1.000.
- 전체 Pearson(`area_norm`, `pop_norm`) = 0.887, Spearman = 0.929 (주 간 밀도 차이만큼만 이탈).

**부수 문제**
- `exposure_rate`는 구역 기준 `flood_ratio`를, `population_exposed`는 주 기준 밀도를 쓰는 **기준 불일치**.
- `raw_flood_area_km2`와 `adjusted_flood_area_km2`가 primary 경로에서 항상 동일 — "adjusted"라는 이름이 잔재.

**수정 후보**
- **A (권장)**: 격자 인구 데이터(WorldPop 100m 또는 GHS-POP)를 침수 마스크와 실제로 교차. `src/archive/population.py`에 WorldPop GEE 오버레이 코드가 이미 있음 → 복원해 primary로 승격. 이때 인구 항은 면적과 독립 정보를 가짐.
- **B**: 격자 인구가 불가하면 인구 항을 버리고 PSS = 정규화된 침수면적(또는 `flood_ratio`) 단일 지표로 정직하게 축소. 대신 노출 인구는 모형의 별도 공변량(구역 인구 총량)으로 투입.
- **C**: 구역 단위 인구(센서스 2011 district population 또는 주민등록 추정)로 밀도를 구역 수준까지 내려 최소한 주 내 변동을 확보. 여전히 균등밀도 가정이지만 현재보다 개선.
- 어느 안이든 PSS 두 성분의 상관을 보고서에 명시하고, 상관이 0.9 이상이면 가중치 민감도 분석(현재 0.5/0.5 vs 0.6/0.4)은 의미가 없다는 점을 기술.

---

<a id="3"></a>
## 3. [치명] GDELT 집계창이 문서와 다르고, 사건 기간에 비례함 (offset 누락)

**위치**: `data/gdelt_bq.json`(BigQuery 질의는 리포에 없음), `src/cvnd_paths.py:MEDIA_WINDOW_DAYS`, `compute_expected_coverage.py`

**현재 상태 — 해결됨**: `collect_gdelt.py`가 모든 이벤트에 발생일부터
발생일+93일까지의 고정 창을 적용합니다. 같은 주에서 창이 겹치면 정확한 GDELT
문서 식별자를 발생일이 가장 가까운 이벤트 하나에만 배정합니다.

**문제**
문서·보고서는 일관되게 "design window onset+14d"라고 적지만, 실제 데이터의 창은 **`start_date − 3일` ~ `end_date + 14일`**입니다. `end_date`는 EM-DAT 병합으로 최대 167일까지 늘어나므로 창 길이가 이벤트마다 0일~184일로 다릅니다. 그런데 NegBin 모형에 노출(offset) 항이 없습니다.

**근거**
- `first_article_date − onset` 분포: **−3일이 162/167**, 나머지 −2(2), +12(2), +10(1).
- `last_article_date − end_date`: **+14일이 152/167**, +13(9) 등.
- corr(창 길이, 이벤트 기간) = **0.998**.
- 평균 y = 4,891건, 최대 39,317건 (`test/outputs/overdispersion_report.md`) — 14일 창의 단일 구역 홍수 보도량으로 볼 수 없는 규모.

**왜 치명적인가**
`y`가 "관측 기간이 길어서 많음"과 "주목을 많이 받아서 많음"을 구분하지 못합니다. 기간이 긴 사건은 기계적으로 과다보도로, 짧은 사건은 과소보도로 분류됩니다. 또한 같은 주·같은 해의 창이 겹치는 사건들(예: E29 2022-05-17~10-31과 E08 2022-06-15~07-05)은 기사를 이중계상합니다 — E08은 quarantine으로 막았지만 규칙화되어 있지 않습니다.

**수정 후보**
- **A (채택)**: 모든 이벤트에 **고정 창**(현재 onset~onset+93d)으로 BigQuery를 재추출. 창 길이가 모든 이벤트에서 같으므로 GLM의 기간 offset은 상수가 되어 불필요.
- **B**: 재추출이 불가하면 현 데이터에 `window_days = (last−first)+1`을 계산해 `sm.GLM(..., offset=np.log(window_days))`로 투입. 최소한 기간 교란은 제거됨.
- **C**: y를 "일평균 기사수"로 바꾸고 Gamma/음이항 대신 준포아송 사용. 단 카운트 모형의 장점을 잃음.
- 추가: 같은 주에서 창이 겹치는 이벤트 쌍을 자동 검출해 병합/제외하는 규칙을 코드화(현재 `events_quarantine.csv` 수작업).
- 추가: BigQuery 질의문(SQL)을 `src/`에 커밋. 현재 검색 키워드·언어·`SOURCEURL` 필터를 검증할 수 없음.

---

<a id="4"></a>
## 4. [높음] MSS 4개 지표 중 `S_TTFR`은 상수, `S_CD`는 물리량 누출

**위치**: `src/compute_mss.py` Step 4

**문제 4-1 — `S_TTFR`이 정보 없음**
```python
df["t_first_days"] = (df["first_date"] - df["onset_date"]).dt.days.clip(lower=0).fillna(14)
```
집계창이 onset−3일에서 시작하므로 `t_first`는 거의 항상 음수이고, `clip(lower=0)`이 이를 0으로 눌러버립니다.
- `t_first_days == 0`이 **164/167**, 따라서 `S_TTFR = exp(0) = 1.0`이 164/167.
- γ 민감도 분석(γ=0.1/0.3/0.5)은 상수에 대한 민감도라 무의미.
- 게다가 "발생 전 보도"가 164건이라는 사실 자체가, 질의창이 사건 이전을 포함하거나 EM-DAT `start_date`가 실제 발생일보다 늦다는 신호입니다.

**문제 4-2 — `S_CD`가 미디어 지표가 아님**
`coverage_days`는 언어별 최댓값을 취하는데, 그 값은 사실상 질의창 길이입니다.
- corr(`coverage_days`, 이벤트 기간) = **0.974**, corr(`S_CD`, 기간) = 0.974.
- 즉 "보도 지속기간"이라는 미디어 지표에 EM-DAT의 물리적/행정적 사건 기간이 그대로 들어옵니다(물리량 → 미디어 점수 누출).

**수정 후보**
- `S_TTFR`: **A** 고정 창(#3-A) 재추출 후 `t_first = first_article_date − onset`을 음수 허용으로 계산하고 사전보도는 별도 플래그. **B** 재추출 불가 시 지표를 삭제하고 3지표 MSS로 축소(가중치 재도출). **C** 대안 지표로 "onset 후 첫 24/48시간 기사 비중" 사용 — 단 일별 카운트가 필요.
- `S_CD`: **A** 일별 기사 카운트를 받아 "기사 ≥1인 서로 다른 날 수 / 창 길이"(정규화된 지속률)로 재정의. `coverage_days_threshold_1` 컬럼이 이미 존재하니 정의를 확인해 활용. **B** 창 길이로 나눠 비율화. **C** 지표 삭제.
- 언어별 집계는 `max`가 아니라 "합집합 일수"여야 함(현재 `max`는 가장 오래 보도한 단일 언어값).

---

<a id="5"></a>
## 5. [높음] `S_vol`과 `S_sov`가 완전 중복, AHP 가중치가 그 중복에 0.75

**위치**: `src/compute_mss.py` Step 4–5, `AHP_MATRIX`

**문제**
```python
df["S_vol"] = MinMax(log1p(total_articles))
df["S_sov"] = MinMax(total_articles / N_total)     # N_total은 상수
```
`N_total`이 상수이므로 `S_sov = MinMax(total_articles)`이고, `S_vol`은 그 단조변환입니다. 두 지표는 순위가 완전히 동일합니다.

**근거**
- Spearman(`S_vol`, `S_sov`) = **1.0000** (Pearson 0.7013 — 로그 변환 때문일 뿐).
- AHP 가중치 = **0.375 / 0.375 / 0.125 / 0.125** → 같은 양에 0.75.
- 따라서 Spearman(MSS, `total_articles`) = **0.9702**. MSS는 기사수의 단조변환에 가깝고, 독립적 구성개념이 아닙니다.
- 결과적으로 MSS는 NegBin의 종속변수 `y`와 거의 같은 변수 → `log_ratio`와 MSS의 Spearman이 0.717로 나오는 것은 발견이 아니라 구성상 필연.

**문제 5-2 — AHP 일관성 검정이 공허함**
`AHP_MATRIX`는 두 개의 동일 블록으로만 구성되어 완전 일관 행렬입니다. 따라서 λ_max = 4.0, CI = 0, **CR = 0.0000**이 나오며(`test/outputs/mss_weight_report.md`), "CR < 0.10이므로 판단이 일관적"이라는 서술은 검정력이 없습니다.

**수정 후보**
- **A (권장)**: `S_sov`를 재정의해 실제로 "점유율"이 되게 함 — 분모를 **동일 기간 인도 전체 뉴스량**(GDELT 해당 창의 전체 기사수)으로 바꿈. 그러면 시기별 미디어 총량 변동을 통제하는 독립 정보가 생김.
- **B**: `S_sov` 삭제, `S_vol`만 유지하고 가중치 재도출.
- **C**: 4지표를 유지하되 PCA/EWM처럼 상관을 흡수하는 가중을 primary로. 단 `test/outputs/mss_weight_report.md`의 EWM는 중복 지표 중 하나(`S_sov`)에 0.636을 주고 있어 해석이 어려움.
- AHP를 유지하려면 최소 3개 이상 서로 다른 강도의 비교값(1,3,5,7)을 넣어 CR이 실제로 검정되게 하고, 판단 근거(문헌·전문가)를 문서화.
- **구조적 권고**: MSS를 "종속변수 y"와 분리. 현재는 MSS ≈ y이므로 MSS를 회귀에 넣거나 MSS로 순위를 매기면 순환논리가 됩니다. MSS는 기술통계(plot1)로만 쓰고, 인과/격차 주장은 NegBin 잔차로만 하도록 문서에 못 박는 것이 안전.

---

<a id="6"></a>
## 6. [높음] `log_ratio`는 "절대적 과소보도"가 아니며 0 기준선이 편향되어 있음

**위치**: `src/compute_expected_coverage.py:main()`, `outputs/pipeline_result.md`

**문제 6-1 — 정의 오표기**
보고서는 `under_flag (log_ratio < 0)`을 "**Absolute** under-coverage"로 표기합니다. 그러나 μ̂는 **같은 표본에 적합된 값**이므로 `log_ratio`는 "표본 평균적 심각도–보도 관계 대비 상대적" 잔차입니다. 인도 홍수 보도 전체가 과소하다면 그 사실은 잔차에 나타나지 않습니다.

**문제 6-2 — 0 기준선의 체계적 편향**
로그-링크 GLM은 응답 척도에서 가중 잔차합만 0으로 만들며, `ln((y+0.5)/(μ̂+0.5))`의 평균/중위수는 0이 아닙니다(Jensen 부등식 + 우편향).
- 실측 `log_ratio` 평균 **−0.4686**, 중위수 **−0.2731**.
- `under_flag` = **82/132 = 62.1%**. 이 62%는 "과소보도가 다수"라는 발견이 아니라 변환 인공물입니다. 보고서 L29가 이를 발견처럼 제시합니다.

**문제 6-3 — 표본 내 적합값**
연도 더미 11개 + 절편 + 2개 공변량 = 13 모수를 132 관측에 적합한 뒤 그 잔차로 순위를 매깁니다. 극단값은 자기 자신의 μ̂를 끌어당겨 잔차가 축소됩니다(leverage).

**문제 6-4 — `severity_tier` 이름과 하드 실패**
`severity_tier`는 심각도 3분위가 아니라 **`log_ratio`의 3분위**입니다. 이름이 독자를 오도합니다. 또한:
```python
if low_mask.any() and not bool(out.loc[low_mask, "under_flag"].all()):
    raise AssertionError(...)
```
`log_ratio`의 P33이 0을 넘는 표본(전반적 과다보도)에서는 파이프라인이 **예외로 중단**됩니다. 검증 실패는 경고로 처리해야 할 성격입니다.

**수정 후보**
- **A (권장)**: 용어를 `relative_coverage_residual`로 바꾸고, 기준선을 표본 중위수로 재중심화(`log_ratio − median`) 하거나, 부호 기준 대신 **분위/표준화 잔차**로 순위만 사용. "절대적" 표현 삭제.
- **B**: 표본 외 기대값 사용 — LOO(leave-one-out) 또는 K-fold로 μ̂를 산출해 leverage 제거.
- **C**: 이분 라벨을 아예 버리고 연속 잔차 + 신뢰구간만 보고. 어떤 이벤트가 "통계적으로 유의하게" 과소인지는 부트스트랩(주 단위 클러스터 부트스트랩) 예측구간으로 판단.
- `severity_tier` → `residual_tertile`로 개명, AssertionError → `print("WARN ...")`.
- 소득 격차 검정은 **2단계(잔차 OLS) 대신 1단계**로: `income_group`을 NegBin에 직접 넣고 계수를 검정. 현재 2단계는 1단계 추정 불확실성을 무시해 SE를 과소평가합니다.

---

<a id="7"></a>
## 7. [높음] `combined_km2`가 4가지 관측방식의 혼합이고 보정이 없음

**위치**: `src/merge_results.py`

**문제**
한 컬럼에 서로 다른 센서·해상도·알고리즘의 값이 섞입니다. 분석 표본(132건) 구성:

| `combined_source` | n | 평균 `log_ratio` | 중위 면적(km²) |
| --- | --- | --- | --- |
| NDWI (전 구역) | 37 | −0.555 | 5.89 |
| S1(cloud) | 36 | −0.357 | 6.06 |
| S1(cloud>60) | 18 | −0.657 | 12.98 |
| SITS+NDWI (게이팅) | 34 | −0.553 | 7.80 |
| SITS+NDWI(restored) | 7 | **+0.314** | 6.82 |

소스별로 면적 수준과 잔차 평균이 다릅니다. 소스는 구름량(=몬순 강도)과 상관되므로 **측정오차가 처리변수와 상관**됩니다. 모형에는 소스 지시변수가 없습니다.

**문제 7-2 — 임계값들이 모두 임의값이고 민감도 분석이 없음**
`FLOOD_MIN_PX = 205`(5%), `MIN_POS = 20`, `J_MIN = 0.15`, restore 규칙의 `0.5`, `CLOUD_MAX_PCT = 60`. 코드 주석에 "docs historically said 30%; code threshold is 60"이라고 적혀 있어 문서와 코드가 이미 어긋난 이력이 있습니다.

**문제 7-3 — 게이트가 순환적**
SITS 점수의 임계값을 NDWI 라벨로 Youden J 최적화한 뒤, 통과하면 다시 NDWI로 면적을 계산합니다. 외부 검증이 아니므로 게이트는 독립 정보를 주지 않습니다(코드 주석도 인정). 실제로 SITS가 면적에 영향을 주는 건 41/132건뿐이며, README의 "SITS + NDWI/SAR" 서술은 소수 사례에만 해당합니다.

**수정 후보**
- **A (권장)**: 모든 이벤트를 **단일 방식**으로 측정. 전천후인 S1(SAR)을 기본으로 하고 광학은 검증용으로만. 지역·구름 편향이 사라짐.
- **B**: 혼합을 유지하되 (1) `combined_source`를 NegBin과 PSS 단계 모두에 고정효과로 투입, (2) 소스별 하위표본 재분석을 민감도로 보고, (3) 두 방식이 모두 있는 이벤트에서 교정계수(orthogonal regression)를 추정해 스케일 정렬.
- **C**: 홍수 면적을 점추정 대신 [S1, NDWI] 구간으로 다루고 오차 내포 회귀(errors-in-variables) 또는 다중대입 사용.
- 임계값 5개에 대한 격자 민감도(예: J_MIN ∈ {0.1,0.15,0.2}, CLOUD ∈ {30,45,60})를 돌려 `log_ratio` 순위 상관을 보고. `CLOUD_MAX_PCT`는 `cvnd_paths.py`에도 `merge_results.py`에도 각각 정의되어 있어(중복 상수) 하나로 통합 필요.
- 외부 검증: Sentinel Asia / UNOSAT / Copernicus EMS 홍수 델리니에이션이 있는 사건 몇 건과 면적 대조 → 최소한의 검증 근거 확보.

**상태 (2026-09-12, refactor/satellite2)**: 수정안 B의 변형으로 구현. SITS가 primary이고 Track B는 모든 district에서 필수(`sits_status` pending → NA, 조용한 S1 fallback 없음). SITS 불가 district는 S1을 SITS-NDWI 척도로 변환(`S1_TO_SITS`); 변환기 채택 여부는 `compare_tracks.py`가 사전 등록 규칙(`flood_spec.ConverterRules`)으로 판정. 7-2의 임계값은 `SPEC`으로 이관되어 바꾸면 캐시가 무효화됨. 7-3의 restore 조건은 AOI 전체 S1이 아니라 같은 usable 픽셀 위 S1과 비교. 기존 라우팅은 `legacy_*` 컬럼과 `routing_comparison.json`으로 전후 비교. 외부 검증은 후속 과제(X1). 방법은 `docs/district_methodology.md` 참조.

---

<a id="8"></a>
## 8. [높음] `income_group`이 하드코딩이고 실제 소득과 어긋남

**위치**: `src/archive/build_events_emdat.py:STATE_INCOME`

**문제**
30개 주를 High/Middle/Low로 손으로 배정했고, 출처 주석이 "consistent with existing events.csv"뿐입니다. 실제 1인당 NSDP와 배치되는 사례가 있습니다.
- **Sikkim = Low**: 인도에서 1인당 NSDP 최상위권.
- **Himachal Pradesh = Low**, **Uttarakhand = Low**: 전국 평균 이상.
- **Kerala = Middle**, **Telangana = High**, **Karnataka = High** — 기준이 무엇인지 불명.
- 표본은 Low 102 / High 37 / Middle 29로 Low에 치우쳐 있고, 위 오분류가 곧바로 "Low 소득 주가 과소보도"라는 핵심 결론(보고서: Low 평균 −0.7733, High +0.0085)에 들어갑니다.
- 아이러니하게 `src/archive/build_covariates.py`에는 `gsdp_per_capita` 수치가 이미 들어 있는데 primary 경로에서 쓰이지 않습니다.
- `income = STATE_INCOME.get(state, 'Low')` — 미등록 주가 조용히 Low가 되는 기본값도 위험.

**수정 후보**
- **A (권장)**: 연도별 1인당 NSDP(MoSPI)를 연결해 **연속 변수**로 사용. 3분류는 민감도용으로만. 사건 연도 기준 값을 쓰면 시간 변동도 반영.
- **B**: 분류를 유지하되 컷오프를 명시적 규칙으로(예: 전국 1인당 NSDP의 ±25% 밴드) 재계산하고 출처를 문서화.
- **C**: 소득 대신 미디어 인프라 지표(주별 신문 발행부수, 인터넷 보급률, GDELT 등록 매체 수)를 사용. "보도 편향"의 메커니즘에 더 직접적이며, 현재 결과가 소득이 아니라 미디어 시장 규모의 반영일 가능성을 검증할 수 있음.
- 어떤 안이든 `income_group`을 `events.csv`에 박아 넣지 말고 별도 `data/state_covariates.csv`(연도별)에서 조인. 지금은 archive에만 존재.

---

<a id="9"></a>
## 9. [중간] EM-DAT 사망자 매칭이 느슨하고 결측을 0으로 대입

**위치**: `src/compute_expected_coverage.py:attach_deaths_from_emdat()`

**문제**
```python
mask = (loc.str.contains(state, regex=False) | admin.str.contains(state, regex=False)) \
       & ((raw["start_dt"] - onset).abs().dt.days <= 45)
hits = raw.loc[mask, "Total Deaths"].dropna()
deaths.loc[i] = float(hits.max())
```
1. `Total Deaths`는 EM-DAT **레코드 전체(다중 주)** 의 사망자입니다. 그것을 개별 주-이벤트에 그대로 붙이면 다중 주 재난의 전국 사망자가 각 주에 중복 배정됩니다.
2. `max()`는 ±45일 내 여러 레코드 중 최악값을 취해 상향 편향.
3. 별칭 처리가 없어 `Odisha`/`Orissa`, `Uttarakhand`/`Uttaranchal`, `Delhi`/`NCT of Delhi` 등이 매칭 실패 → 결측이 체계적으로 특정 주에 몰림.
4. Option C로 결측을 `fillna(0)` → "사망자 0"과 "EM-DAT 기록 없음"을 동일시. 결측 **23/132**.
5. 사망자는 강한 보도 예측인자(계수 0.1569, p<0.001)이므로 이 편향은 μ̂를 직접 왜곡하고, 결측이 주와 상관되면 소득 격차 추정까지 오염됩니다.
6. `events.csv`를 만들 때 이미 `total_deaths`를 갖고 있었는데(build 단계) 최종 스키마에서 버리고, 여기서 다시 문자열 매칭으로 복원하는 구조 — 불필요한 정보 손실.

**수정 후보**
- **A (권장)**: `events.csv`에 `emdat_disno`를 보존해 **키 기반 조인**. `build_events_emdat.py`가 이미 `emdat_disno`를 만들지만 최종 컬럼에서 제외됩니다. 다중 주 레코드는 주별로 배분(예: 각 주 균등, 또는 `Admin Units` 개수 비례)하고 배분 규칙을 문서화.
- **B**: 결측을 0으로 채우지 말고 (1) 결측 지시변수를 모형에 포함, (2) 다중대입(MICE), (3) 사망자 없는 사양과 있는 사양을 모두 보고하는 3중 민감도.
- **C**: 사망자 대신 `Total Affected`나 EM-DAT의 `Total Damage`를 쓰거나, 사망자를 아예 제외하고 "물리량만으로 기대치"를 정의(해석이 더 깔끔해짐 — 사망자는 보도의 원인이자 결과일 수 있어 매개변수 통제 문제도 있음).
- 매칭을 유지하려면 `compute_population.py`의 `STATE_ALIASES`/`resolve()`를 재사용하고, 부분문자열 대신 정규화된 완전일치.

---

<a id="10"></a>
## 10. [중간] 위성 관측창·해상도가 단계마다 불일치, median 합성이 피크를 희석

**위치**: `src/satellite.py`, `post_cloud.py`, `src/merge_results.py`

**불일치 목록**

| 단계 | 관측창 | 해상도 | 합성 |
| --- | --- | --- | --- |
| Track A S1 | `[start, start+7d]` | reduceRegion `scale=30` | `median()` |
| Track A S2/NDWI | `[start, start+7d]`, pre `[-30d, 0]` | `scale=30` | `median()` |
| Track B t5 (SITS/NDWI 픽셀) | `[start, start+14d]` | 10 m (`PX_KM2=1e-4`) | `median()` |
| `post_cloud.py` 구름 판정 | `[start, start+14d]` | `scale=200` | `median()` |
| Track B 베이스라인 | 동월±1, 최근 3년 중 "가장 맑은 2개 + 가장 마른 것" | 10 m | 월 median |

- 구름 라우팅 판정 창(14일)과 라우팅 대상 면적의 창(7일)이 다릅니다.
- `merge_results`는 10 m 픽셀 기준 NDWI 면적과 30 m 기준 S1 면적을 같은 컬럼에 섞습니다(#7과 결합해 스케일 불일치).
- **median 합성**: 7~14일 내 영상이 여러 장이면 침수일이 소수일 때 중위수에서 물이 사라집니다. 홍수 최대 범위를 재려면 `max(water)` 또는 `min(VV backscatter)`가 맞습니다. 이 편향의 크기는 재방문 횟수·구름량에 의존 → 지역 편향.
- `otsu_backscatter_threshold`는 Otsu 값이 `[-20,-13]`을 벗어나면 −16 dB 고정으로 대체 → 이벤트 간 임계값 정의가 달라짐. 몇 건이 fallback인지 기록되지 않음(`otsu_threshold_db`만 저장).
- S1 경로는 JRC 영구수역·경사<5°·인도 경계 마스크를 적용하지만 **S2/NDWI 경로는 마스크가 없음**(`pre_ndwi<=0`만). 영구수역 계절변동과 산악 음영이 NDWI 면적에 남습니다.
- S1은 `orbitProperties_pass == 'DESCENDING'`만 사용 → 해당 창에 하강궤도 통과가 없는 지역은 근거 없이 결측.
- Track B의 픽셀 단위 `ndwi_flood` 계산 및 SITS 점수는 **Colab 노트북(리포에 없음)** 에서 생성됩니다. `data/sits_scores/*.npz`의 `ndwi_pre/ndwi_during/ndwi_flood` 정의를 코드로 검증할 수 없습니다.

**수정 후보**
- **A (권장)**: 관측창을 하나로 통일(예: `[onset, onset+14d]`)하고 모든 면적을 동일 `scale`(10 m 또는 20 m)로 산출. 상수를 `cvnd_paths.py`에 단일 정의.
- **B**: median → "침수 최대" 합성으로 전환(`ImageCollection.map(water_mask).max()`), 또는 개별 영상별 면적을 산출해 최댓값 사용. 부작용(구름 오탐)이 있으므로 SCL 마스크 강화 병행.
- **C**: S2 경로에도 JRC 영구수역·경사 마스크를 동일 적용(코드 3줄), 궤도 필터 해제 후 궤도를 공변량으로.
- SITS 채점 노트북과 `ndwi_flood` 정의를 리포에 커밋. 없으면 `flood_combined.csv`는 재현 불가 산출물입니다.

**상태 (2026-09-12, refactor/satellite2)**: 창·해상도·합성·마스크는 이전 단계에서 `flood_spec.SPEC`으로 통일됨. 이번 단계에서 추가로: district별 UTM 10 m 격자 하나를 Track A 축소와 Track B 다운로드가 공유(타일 좌표 중복·위도 의존 손실 제거), 면적 합은 unweighted(가중 합이 재투영 마스크의 분수 가중치 때문에 하천 주변 픽셀을 부분만 세어 Darbhanga S1이 385 vs 760 km²로 과소), 대형 AOI는 격자 정렬 하위 사각형으로 분할 합산, Track B 재개 시 `block_id`로 중복 적재 제거, baseline에서 onset 월 제외, t5는 max-water와 같은 장면(qualityMosaic). B1(max 합성의 N 의존성)은 `n_post`와 첫 획득일만 기록하고 보류(X2).

---

<a id="11"></a>
## 11. [중간] MinMax 정규화로 PSS/MSS가 표본 의존적

**위치**: `src/compute_pss.py`, `src/compute_mss.py`

**문제**
`MinMaxScaler`는 표본의 최소·최대에 의해 정의됩니다. 이벤트 1건을 추가/제거하거나 quarantine 목록을 바꾸면 **모든 이벤트의 PSS·MSS가 변합니다.** 최댓값 이벤트 하나가 전체 스케일을 지배하며, PSS는 136건, MSS는 167건, 최종 분석은 132건 — 서로 다른 표본에서 스케일된 점수가 한 표에 섞입니다.

또한 `compute_pss.py`에서 하나의 `scaler` 객체를 두 컬럼에 재사용합니다(`fit_transform`이 매번 재적합하므로 결과는 맞지만, 의도가 불분명해 오독 위험).

**수정 후보**
- **A (권장)**: 이론적 상한/하한이 있는 정규화로 교체 — 면적은 `flood_ratio`(0~1, 구역 대비 침수율), 기사수는 로그 후 z-표준화(평균·표준편차를 메타데이터로 저장해 재현).
- **B**: MinMax를 유지하되 스케일 파라미터를 JSON으로 고정 저장하고 재사용(스케일 고정 = 표본 독립).
- **C**: 순위 기반(백분위) 점수로 전환. 표본 의존은 남지만 이상치 영향이 사라짐.
- 어떤 안이든 PSS·MSS·최종 분석의 **표본을 일치**시켜야 합니다(현재 136/167/132).

---

<a id="12"></a>
## 12. 코드 수준 버그·결함 모음

| 위치 | 내용 | 수정 |
| --- | --- | --- |
| `compute_expected_coverage.py:main()` | `pearson = (y-mu)/sqrt(mu + result.scale*mu**2)` — GLM은 `alpha` 고정 family이므로 `result.scale == 1.0`(보고서 `Scale: 1.0000`)이지만 실제 추정 α̂ = 0.8279(`test/outputs/overdispersion_report.md`). 즉 분산을 `μ+μ²`로 잘못 계산 | `fit_negbin`이 `alpha`를 반환하도록 바꾸고 `mu + alpha*mu**2` 사용 |
| `compute_expected_coverage.py:fit_negbin()` | 추정된 `alpha`를 로그·산출물에 남기지 않음 → 재현 불가 | `alpha`를 CSV/보고서 메타에 기록 |
| `compute_expected_coverage.py:choose_severity_proxy()` | 후보마다 α를 따로 추정한 뒤 AIC를 비교 — 분산함수가 다른 모형 간 AIC 비교는 부적절. 또한 선택 후 같은 데이터로 추론(post-selection inference) | α를 고정해 비교하거나, 두 사양을 모두 보고(민감도). 애초에 #2를 고치면 두 후보가 사실상 동일 변수라 선택 자체가 무의미 |
| `compute_expected_coverage.py:main()` | `severity_tier=='low' ⊄ under_flag`일 때 `raise AssertionError` → 데이터에 따라 파이프라인 중단 | 경고 출력으로 강등 |
| `compute_expected_coverage.py:write_markdown_report()` | 매개변수 `include_deaths`를 받지만 사용하지 않음 | 제거 또는 보고서에 사양 기록 |
| `compute_expected_coverage.py:income_cluster_robust()` | 기준범주를 "알파벳순, 보통 High"로 가정 | `pd.Categorical(categories=INCOME_ORDER)`로 기준을 명시 고정 |
| `compute_expected_coverage.py` | 29개 주 클러스터에 13 모수 — 소표본 클러스터 보정(HC3/CR2, 또는 wild cluster bootstrap) 없음 | `cov_kwds={'use_correction': True}` 또는 부트스트랩 |
| `build_analysis_frame()` | `mss` 좌조인 후 `dropna` → GDELT에 **없는 이벤트가 조용히 탈락**(E125). "0으로 대입하지 않는다"는 방침 때문에 정작 보도가 전무한 사건(가장 과소보도 사례)이 표본에서 사라지는 선택편향 | 질의 결과가 "0건"인지 "질의 누락"인지 구분되는 로그를 남기고, 전자는 0으로 포함 |
| `compute_pss.py`, `compute_mss.py` | `rank(ascending=False).astype(int)` — 동순위 `.5`가 잘림 → 순위 안정성 진단이 왜곡 | `method="min"` 지정 후 `astype(int)` |
| `compute_mss.py:print_entropy_weights()` | `X / X.sum(axis=0)`에 0 분모 가드 없음(`entropy_weights`에는 있음) | 동일 가드 추가 |
| `compute_mss.py` | `event_agg`를 `["event_id","state"]`로 그룹 — 같은 event_id에 state 표기가 다르면 행 분할 | `event_id`만으로 그룹 후 state는 `events.csv`에서 조인 |
| ~~`compute_population.py`, `merge_results.py`, `post_cloud.py`, `district_area.py`~~ | **해결됨** — `cvnd_layout.data_path()`와 state-AOI `aoi_km2` 스키마로 통일 | 완료 |
| `merge_results.py` vs `cvnd_paths.py` | `CLOUD_MAX_PCT`가 양쪽에 각각 정의(둘 다 60이지만 동기화 보장 없음) | 단일 출처로 통합 |
| `visualize.py:plot_pss_mss_scatter()` | PSS와 MSS에 `y=x` 대각선을 그림 — 서로 다른 가중·정규화 척도라 "PSS=MSS"는 의미 없는 비교 | 대각선 제거 또는 순위-순위 산점도로 변경 |
| `visualize.py:plot_coverage_map()` | Natural Earth `name` ↔ `state` 문자열 조인. 불일치 시 조용히 결측(`missing_kwds`로 회색 처리)되어 **누락을 알 수 없음** | 조인 후 미매칭 주 목록을 반드시 출력/검증 |
| `visualize.py:plot_coverage_map()` | `vmax = 90th percentile(|mean|)`로 색상 스케일이 데이터 의존 + 클리핑을 범례에 표기하지 않음 | 고정 스케일 또는 범례에 "clipped at ±x" 명시 |
| `visualize.py:plot_coverage_map()` | 주별 평균을 `n_events` 무관하게 동일 색으로 표시(1건 vs 12건) | 투명도/해칭으로 n 반영, 또는 축소추정(shrinkage) 평균 |
| `visualize.py:plot_log_ratio_by_income()` | 오차막대가 단순 SEM(클러스터 무시) — 제목에 언급은 있으나 그림은 오해 유발 | 클러스터 로버스트 CI로 교체 |
| `satellite.py:detect_flood_baseline()` | `combined = s2_area if s2_area>0 else area_km2` — 크기 무관하게 S2 우선. `flood_extent.affected_area_km2`는 이제 아무도 안 쓰는 유령 컬럼 | 컬럼 삭제 또는 `merge_results`와 규칙 통일 |
| `run_pipeline.sh` | `SKIP_ARTICLES=0`이면 `src/archive/news.py`를 실행하지만 그 출력은 MSS에 쓰이지 않음(스크립트도 이를 출력으로 인정) | 옵션 제거 |
| ~~`run_pipeline.sh` AOI/cloud 보조 단계 누락~~ | **해결됨** — full GEE 실행에 `event_aoi_area.py`와 `post_cloud.py` 포함, 불완전 캐시는 오류 처리 | 완료 |
| ~~기존 `build_events_emdat.py`의 수동 시드·district 파싱~~ | **해결됨** — 공식 워크북 기반 `build_emdat_events.py`로 교체 | 완료 |

---

<a id="13"></a>
## 13. [중간] 재현성 결함

- **해결됨 — 공식 이벤트 단일화**: `data/raw/EM-DAT-BASE.xlsx`의 공식 레코드만 이벤트 원본으로 사용합니다. `build_emdat_events.py`는 각 `DisNo.`를 명시된 인도 주/UT별로 전개하며, 서로 다른 `DisNo.`를 합치거나 수동 시드를 추가하지 않습니다. 모든 레지스트리 행은 공식 `source_record_id`를 보존합니다.
- **해결됨 — GDELT SQL 재현성**: `collect_gdelt.py`가 공식 EM-DAT 이벤트에서
  기간·flood theme·위치·언어·도메인·URL 중복 제거·겹치는 사건 배정 규칙을
  포함한 `data/raw/gdelt_emdat_query.sql`을 생성하고 실행 메타데이터에 SQL 및
  이벤트 레지스트리 SHA-256, BigQuery 작업 ID와 처리 바이트를 기록합니다.
- **SITS 추론 노트북 미포함** → `sits_scores/*.npz`(scores, ndwi_flood)의 생성 로직이 리포 밖입니다.
- **`requirements.txt` 버전 핀 없음**(17개 패키지 전부 무버전). `statsmodels`/`sklearn` 버전 차이로 결과가 바뀔 수 있습니다.
- **남은 문서-코드 불일치**: `CLOUD_MAX_PCT` 문서 30 vs 코드 60, README의 "SITS + NDWI/SAR"(실제 SITS 관여 41/132), 보고서의 "Absolute under-coverage". 미디어 창은 `MEDIA_WINDOW_DAYS=93` 고정 창으로 해결했습니다.
- **`src/ingest/`, `src/flood/`, `src/indices/`** 에는 `__pycache__`만 남아 있고 소스가 없습니다(삭제된 모듈의 잔재).

**남은 수정 후보**: SQL과 노트북 커밋 · `pip freeze`로 핀 고정 · 문서 수치를 코드 상수로부터 생성(현재 `cvnd_layout`에 상수는 있으나 README는 수동).

---

## 14. 권장 처리 순서

1. **#1 (AOI)** — 이걸 고치지 않으면 PSS·NegBin·log_ratio·모든 그림의 물리적 의미가 성립하지 않습니다. 최우선.
2. **#3 (미디어 창/offset)** — 종속변수의 기계적 교란 제거. #1과 독립적으로 즉시 착수 가능.
3. **#2 (인구 노출)** — 격자 인구 도입 또는 PSS를 단일 지표로 축소.
4. **#8 (소득 지표)** — 핵심 주장의 설명변수 교체. 데이터만 붙이면 되므로 비용 대비 효과 큼.
5. **#6 (잔차 해석·용어) + #12 코드 버그** — 논문 서술 교정과 저비용 코드 수정.
6. **#4, #5 (MSS 재설계)** — #3 재추출과 함께 처리하면 효율적. MSS는 기술통계로 격하하는 것이 안전.
7. **#7, #10 (측정 통일 + 민감도)** — 재계산 비용이 크므로 마지막. 최소한 소스 고정효과와 임계값 민감도는 즉시 추가 가능.
8. **#13 (재현성)** — 병행.

## 15. 즉시 추가할 만한 검증 스크립트 (제안)

- `test/test_measurement_consistency.py` — `population_exposed == area × state_density` 항등식, PSS 두 성분 상관, 주별 AOI 유일성, `combined_source`별 면적 분포 검사. 위 항목 중 임계 위반 시 실패.
- `test/test_media_window.py` — `first_article_date − onset`, `last − end`, 창 길이 vs 이벤트 기간 상관을 검사해 문서화된 창 정의와 대조.
- `test/test_residual_calibration.py` — `log_ratio` 평균·중위수가 0에서 얼마나 벗어나는지, LOO 잔차와 표본 내 잔차의 순위 상관을 보고.
# Historical audit note

This document predates the district-only refactor. References to removed
state-level scripts are historical findings; use `docs/implementation_validation.md`
and `docs/district_methodology.md` for the supported pipeline.
