# District analysis contract

`data/intermediate/event_districts.csv`가 유일한 event×district 레지스트리다. `source_record_id`는 공식 EM-DAT flood를 연결하고 `event_district_id`는 결정적 관측 키다. 명시적 district 근거가 없는 행은 QC를 위해 보존하지만 분석 관측으로 추론하지 않는다. 행정구역 변경은 외부 근거가 있는 crosswalk만 허용한다.

## 위성 관측

위성창과 뉴스창은 분리한다. 위성은 onset 후 14일, primary 뉴스는 30일, sensitivity 뉴스는 14일이다.

- 유일하게 매칭된 India/state/district GAUL2 AOI만 측정한다.
- post `[onset,onset+14d)`, pre `[onset-30d,onset)`이며 `MeasurementSpec` hash가 다른 캐시는 재사용하지 않는다.
- JRC permanent water, slope `<5°`, India boundary mask와 10 m grid를 모든 경로에 동일하게 적용한다.
- 기본 `s1_then_s2` routing은 모든 AOI에 S1을 먼저 실행하고 S1 면적이 결측인 키에만 S2 NDWI를 실행한다.
- S1의 유한한 0은 성공이다. AOI 실패는 S2 fallback 대상이 아니다.
- 선택 순서는 S1 관측 → S2 관측 → 결측이며 `satellite_source`와 `route_reason`을 기록한다.
- Track B/SITS는 `SATELLITE_TRACK=both SATELLITE_ROUTING=sits_primary`로만 사용하는 별도 opt-in 경로다.

결측 flood measurement는 NA다. 관측된 0과 빈/실패 reduction을 구별한다.

## 기사 관측

30일 후보 corpus에서 district와 state의 명시적 근거를 요구한다. state mention만으로 district coverage를 만들지 않는다. URL×district는 가장 가까운 eligible onset에 결정적으로 배정한다.

multilingual flood heuristic을 통과한 후보만 LLM-QA로 전달한다. LLM 결과는 같은 후보에서 30일 primary와 14일 sensitivity count로 집계한다. `complete`와 `partial`은 유효 관측이며 partial은 lower-bound flag를 유지한다. `incomplete`는 정상 결측이다. 자세한 provenance와 resume 규칙은 [article_qa.md](article_qa.md)에 있다.

## Join과 분석

`analysis_eligible`은 식별된 district, 유효 AOI, 유한한 비음수 flood area, 유효한 article 관측, Census covariate, onset을 요구한다. 모든 registry 행과 `exclusion_reason`을 보존하며 결측을 0으로 채우지 않는다.

Primary Model 2는 다음 NB2 모형이다.

```text
log E[article_count_ed] = beta_0 + beta_flood log(1 + flood_area_km2_ed)
                                + beta_urban urban_population_share_d
Var(Y_ed) = mu_ed + alpha mu_ed^2
```

Model 1은 urbanization을 제외하고 Model 3은 year fixed effects를 추가한다. `IRR_10pp=exp(0.1*beta_urban)`을 보고한다. 가능한 경우 state-clustered inference를 함께 제공한다. 이는 관측 flood area에 조건부인 연관이며 인과 또는 의도를 뜻하지 않는다.
