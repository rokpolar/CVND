# CVND: flood extent and district news visibility

CVND는 EM-DAT 홍수의 event×district 단위에서 위성 관측 침수 면적과 뉴스 가시성의 관계를 분석한다. 기본 분석은 **발생일부터 30일간의 뉴스 반응(primary)**이며, 같은 후보 집합의 **14일 뉴스 반응(sensitivity)**을 함께 산출한다. 위성 노출은 별도의 사전 지정된 **발생 후 14일 관측창**이다. 따라서 핵심 분석 정의는 “14일 침수 강도에 대한 30일 뉴스 반응”이다.

## 관측 계약

- 레지스트리: `data/intermediate/event_districts.csv`만 권위 있는 event×district 레지스트리로 사용한다. 모호한 지역은 결측/audit 행으로 보존하고 state 값을 district로 확장하지 않는다.
- 위성: 모든 유효 AOI에서 Sentinel-1(S1)을 먼저 실행한다. S1 면적이 결측인 키에만 Sentinel-2 NDWI(S2)를 실행한다. 유한한 `0 km²`는 성공한 관측이며 fallback 대상이 아니다. AOI 실패도 S2로 재시도하지 않는다. 기본 routing은 `s1_then_s2`다.
- 기사: 30일까지 GDELT 후보를 수집한 뒤 multilingual flood heuristic을 통과한 후보만 LLM-QA로 보낸다. 같은 판정으로 `counts_30d.csv`와 `counts_14d.csv`를 만든다.
- 기사 상태: `complete`와 `partial`은 분석 가능한 관측이다. `partial`은 `article_count_is_lower_bound=True`를 유지한다. `incomplete`는 정상 결측이며 파이프라인 손상으로 간주하지 않는다.
- 모델: NB2 Model 2는 `article_count ~ log1p(flood_area_km2) + urban_population_share`이다. Model 1은 urban share를 제외하고 Model 3은 year fixed effects를 추가한다.

위성 측정식은 `src/flood_spec.py`의 `MeasurementSpec`과 `spec_version`으로 고정한다. post `[onset, onset+14d)`, pre `[onset-30d, onset)`, JRC permanent-water·slope·India mask, 10 m 면적 합산을 모든 sensor 경로에 적용한다. Track B/SITS는 명시적 opt-in이며 기본 분석 경로가 아니다.

## 실행

```bash
# 외부 호출 없이 명령과 캐시 계약 검사
bash scripts/run_pipeline.sh --dry-run

# 전체 검증
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests scripts
bash -n scripts/run_pipeline.sh

# 인증된 실제 실행: S1 전체 -> S1 결측에만 S2 -> 기사 auto resume
SETUP_DEPS=1 SKIP_GEE=0 ARTICLE_PIPELINE_MODE=auto bash scripts/run_pipeline.sh

# 위성 캐시 재사용, 기사 상태를 manifest/hash로 자동 판정
SKIP_GEE=1 ARTICLE_PIPELINE_MODE=auto bash scripts/run_pipeline.sh
```

`ARTICLE_PIPELINE_MODE=auto`의 상태 전이는 다음과 같다.

1. 두 window count와 manifest가 registry/source/request/result/prompt/model hash에 맞으면 heuristic과 LLM-QA를 모두 생략한다.
2. 검증된 heuristic 산출물만 있으면 heuristic을 생략하고 LLM-QA부터 재개한다.
3. 산출물이 없거나 stale이면 GDELT 수집·본문·heuristic부터 수행한 뒤 LLM-QA를 실행한다.

`force`는 기사 파이프라인을 처음부터 재실행하고 `skip`은 기사 join·분석을 수행하지 않는다. `RUN_ARTICLE_SUPPLEMENT=1`만 targeted BigQuery supplement를 허용한다. 외부 GEE·BigQuery·OpenAI 호출은 실제 실행 옵션에서만 발생한다. `SETUP_DEPS=1`은 재현 환경인 `requirements-lock.txt`를 설치한다.

## canonical 산출물

```text
data/results/primary_30d/          # 30일 join, model, OOF scoring
data/results/sensitivity_14d/      # 14일 join, model, OOF scoring
outputs/primary_30d/               # primary 보고서, 그림, final package
outputs/sensitivity_14d/           # sensitivity 보고서와 그림
```

`outputs/primary_30d/analysis_manifest.json`은 입력 SHA-256, 행 수와 eligible 수, 실행 Git HEAD/dirty 상태, source diff hash, dependency-lock hash를 기록한다. `key_results.csv`와 `final_results_figure.png`는 두 window를 새로 적합한 결과에서 생성한다. legacy flat output이나 `sensitivity_30d`, `final_30d_primary` 별칭은 만들지 않는다.

기사 운영 절차는 [Article QA operations](docs/article_qa.md), 세부 관측 규칙은 [District methodology](docs/district_methodology.md), 상대 coverage score는 [Scoring methodology](docs/coverage_scoring_methodology.md)를 참고한다.

## 해석 제한

결과는 **관측된 침수 면적이 비슷한 district 사이의 뉴스 가시성 연관**만 설명한다. 의도적 방치, 차별 또는 인과효과를 증명하지 않는다. Census 2011·GAUL 2015·사건 당시 경계의 불일치, EM-DAT 날짜 보정, GDELT 위치 추출, 원문 생존과 LLM 판정, 위성 가용성이 선택 편향을 만들 수 있다. 결측은 0으로 대체하지 않으며 모든 제외 사유를 남긴다.
