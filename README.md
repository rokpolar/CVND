# CVND: Urbanization Disparities in Flood News Coverage in India: Combining Satellite-observed Inundation and LLM-Based Article Verification

본 연구는 홍수로 인한 침수 피해가 비슷한 지역에서 도시화 정도에 따라 뉴스 보도량이 달라지는지 살펴보고자 한다. 
인도의 홍수 사건을 대상으로 Sentinel-1/2 위성 영상에서관측한 침수 면적과 지역별 관련 기사 수, 도시 인구 비율을
연결하는 분석 방법을 제안한다. 기사는 키워드 필터링과 LLM QA를 통하여 해당 재해 사건과 지역을 연관성을 판별한다. 
이후 침수 면적과 보도량의 관계, 침수 면적을 고려한 도시 인구 비율과 보도량의 관계를 회귀분석으로 검토한다.

## 사용 데이터 
### 재해 사건
  -재난 데이터베이스 EM-DAT에 기록된 2015년부터 2025년까지의 인도 지역의 홍수 사건을 대상
  -단위는 지역(district) 단위를 사용 
  -동일한 홍수가 여러 지역에 영향을 준 경우 지역별로 별도의 관측치를 구성
  -도시화 수준은 인도의 인구총조사국이 2011년 수행한 Census of India의 도시인구와 총인구를 사용

### 침수 면적
-Sentinel-1을 기본으로 사용
-사건 전후 Sentinel-2 영상이 존재하고, 사건전 각 시점에서 구름 없는 면적이 50% 이상,구름 없는 화소가 행정구역 분석 가능 면적의 40%이상인 지역은 Sentinel-2 기반 SITS-Extreme
-VAE와 NDWI로 산출
-Sentinel-1 관측이 없는 지역은 NDWI로 산출

### 보도량
-보도량은 GDELT 2.0 GKG에서 수집
-LLM 질의응답(LLM-QA)에 GPT-5.6-Luna를 사용
- 연도에 따른 뉴스 수집 능력의 발달을 고려하여 연도에 따른 모델을 별도로 구성


## 실행

```bash
# 외부 호출 없이 명령과 캐시 계약 검사
bash scripts/run_pipeline.sh --dry-run

# 전체 검증
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests scripts
bash -n scripts/run_pipeline.sh

# 인증된 실제 실행: Track A(S1 -> S1 결측에만 S2) -> 동결 기사 join/분석
SETUP_DEPS=1 ARTICLE_PIPELINE_MODE=frozen bash scripts/run_pipeline.sh

# 위성 캐시 재사용, 동결 기사 provenance 검증 후 재분석
SKIP_GEE=1 ARTICLE_PIPELINE_MODE=frozen bash scripts/run_pipeline.sh
```

## 산출물

```text
data/results/primary_30d/          # 30일 join, model, OOF scoring
data/results/sensitivity_14d/      # 14일 join, model, OOF scoring
data/results/track_b_35_sensitivity/ # 35구역 Track B 측정/병합/비교 입력
outputs/primary_30d/               # primary 보고서, 그림, final package
outputs/sensitivity_14d/           # sensitivity 보고서와 그림
outputs/track_b_35_sensitivity/    # Track A 대비 Track B robustness 보고서
```

기사 운영 절차는 [Article QA operations](docs/article_qa.md), 세부 관측 규칙은 [District methodology](docs/district_methodology.md), 상대 coverage score는 [Scoring methodology](docs/coverage_scoring_methodology.md)를 참고한다.

## 해석 제한

결과는 **관측된 침수 면적이 비슷한 district 사이의 뉴스 가시성 연관**만 설명한다. 의도적 방치, 차별 또는 인과효과를 증명하지 않는다. Census 2011·GAUL 2015·사건 당시 경계의 불일치, EM-DAT 날짜 보정, GDELT 위치 추출, 원문 생존과 LLM 판정, 위성 가용성이 선택 편향을 만들 수 있다. 결측은 0으로 대체하지 않으며 모든 제외 사유를 남긴다.
