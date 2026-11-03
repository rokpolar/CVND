# CVND: Urbanization Disparities in Flood News Coverage in India, Combining Satellite-observed Inundation and LLM-Based Article Verification

홍수로 인한 침수 피해가 비슷한 지역에서 도시화 정도에 따라 뉴스 보도량이 달라지는지가?
Does the volume of news coverage vary with the degree of urbanization across regions experiencing similar levels of flood inundation?

## Overview
&nbsp;&nbsp;본 연구는 홍수로 인한 침수 피해가 비슷한 지역에서 도시화 정도에 따라 뉴스 보도량이 달라지는지 살펴보고자 한다. 인도의 홍수 사건을 대상으로 Sentinel-1/2 위성 영상에서 관측한 침수 면적과 지역별 관련 기사 수, 도시 인구 비율을 연결하는 분석 방법을 제안한다. 기사는 키워드 필터링과 LLM QA를 통하여 해당 재해 사건과 지역을 연관성을 판별한하고, 이후 침수 면적과 보도량의 관계, 침수 면적을 고려한 도시 인구 비율과 보도량의 관계를 회귀분석으로 검토한다.
<br><br>
&nbsp;&nbsp;This study investigates whether the volume of news coverage varies with the degree of urbanization across regions experiencing similar levels of flood inundation. Focusing on flood events in India, we propose an analytical framework that integrates inundation areas derived from Sentinel-1/2 satellite imagery, the number of relevant news articles, and regional urban population ratios. News articles are identified and linked to specific flood events and affected regions through keyword-based filtering and large language model based question answering (LLM-QA). <br>&nbsp;&nbsp; We then employ regression analysis to examine the relationship between inundation area and news coverage, as well as the association between urban population ratio and news coverage while controlling for inundation area.


#### Published at...

#### ICCJ 2026, International Conference on Climate Justice, CHRIST(deemed to be University) Bangaluru, India
#### 한국정보처리학회 ACK 2026

## Architecture
<img width="893" height="275" alt="스크린샷 2026-10-28 오후 1 40 33" src="https://github.com/user-attachments/assets/d46f6255-1239-47ac-a869-6ed3ea374f88" />

## Datasets
### 재해 사건
&nbsp;&nbsp;-재난 데이터베이스 EM-DAT에 기록된 지역(district) 단위의 2015~2025년까지의 인도 지역의 홍수 사건을 대상<br>
&nbsp;&nbsp;-EM-DAT의 발생일로 사건을 구분, 사건 x district 단위로 분석 데이터를 구성<br>
&nbsp;&nbsp;429개의 district x 160개의 재해 이벤트 -> 1,191개 관측치를 구성
&nbsp;&nbsp;-도시화 수준은 인도의 인구총조사국이 2011년 수행한 Census of India의 district 별 (도시인구 수)/(총 인구) 로 산출

### 침수 면적
&nbsp;&nbsp;-Google Earth Engine에서 Sentinel-1 SAR영상의 VV편파를 사용하여 침수면적을 산출<br>
&nbsp;&nbsp;-Sentinel-1에는 Otsu threshold를 적용하여 관측값이 없으면 Sentinel-2의 NDWI를 활용<br>
&nbsp;&nbsp;-Sentinel-2는 녹색광(B3)와 근적외선(B8)을 이용하여 NDWI를 계산하고 사건 전후 수역 변화를 비교

### 보도량
&nbsp;&nbsp;-보도량은 GDELT 2.0 Global Knowledge Graph(GKG)의 BigQuery 데이터를 사용<br>
&nbsp;&nbsp;-홍수 관련 GKG title tag와 인도 현지 언어를 이용하여 기사 후보를 검색<br>
&nbsp;&nbsp;-기사 원문을 수집한 후 키워드 기반 heuristic filter를 사용하여 LLM 검증 대상 기사 선정<br>
&nbsp;&nbsp;-LLM 질의응답(LLM-QA)은 gpt-5.6-luna를 사용하여 '기사 a가 지역 l의 재해 d를 보도하는가?'를 y/n로 판단<br>
&nbsp;&nbsp;-연도에 따른 뉴스 수집 능력의 발달을 고려하여 기본 회귀모형과 연도 고정효과를 포함한 모형을 비교


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

## 결론
<img width="405" height="286" alt="스크린샷 2026-11-03 오전 10 51 40" src="https://github.com/user-attachments/assets/e1f782f7-8d71-4647-820b-809530b8b604" />
<br>
&nbsp;&nbsp;도시화율이 10%p 증가할 때 기대 보도량은 약 15.2% 증가하였다. (IRR=1.152, 95% CI 1.047-1.267, p=0.005). 
연도별  차이를 고려한 모델에서도 도시화 효과가 거의 동일하게 유지되었다. (IRR=1.151, 95% CI 1.0246-1.266,p=0.006).
같은 모형에서 침수 면적의 효과는 유의하지 않았다 (IRR=1.009, 95% CI 0.861-1.181, p=0.913). 
이는 침수면적을 통제한 이후에도 도시화 수준과 보도량 사이의 양의 연관성이 나타났음을 보여준다.
재해 발생 후 보도량 수집 기간을 14일로 제한한 민감도 분석에서도 도시화 효과는 양의 방향을 보였다. 
도시화율이 10%p 증가할 때 기대 보도량은 7.3% 증가하였으나 (IRR=1.073, 95% CI0.998-1.207, p=0.054) 유의수준 0.05에 도달하지 않았다. 
침수 면적은 민감도 분석에서도 유의한 관계가 나타나지 않았다.
도시화 수준이 높은 지역에서 더 많은 보도가 나타난다는 연관성은 통계적으로 확인되었으나 침수면적이 증가할수록 보도량이 증가하지는 않았다.

## 해석 제한

&nbsp;&nbsp;결과는 관측된 침수 면적이 비슷한 district 사이의 뉴스 가시성 연관만 설명한다. 의도적 방치, 차별 또는 인과효과를 증명하지 않는다. Census 2011·GAUL 2015·사건 당시 경계의 불일치, EM-DAT 날짜 보정, GDELT 위치 추출, 원문 생존과 LLM 판정, 위성 가용성이 선택 편향을 만들 수 있다. 결측은 0으로 대체하지 않으며 모든 제외 사유를 남긴다.
