# CVND 프로젝트 전체 브리핑 (논문 작성용)

> **이 문서의 목적**: 논문 작성 AI에게 CVND 프로젝트 전체를 전달하기 위한 자료다.
> 모든 수치는 리포지토리의 실제 산출물 파일에서 추출한 것이며, 추정치나 예시가 아니다.
> **작성 시점: 2026-09-15 (KST).**
>
> **가장 중요한 전제**: 이 프로젝트는 **아직 주 분석 결과가 나오지 않았다.**
> 현재 분석 가능 표본은 **N = 0**이다. 자세한 내용은 §11을 반드시 먼저 읽을 것.
> 따라서 H1/H2에 대한 계수, 유의성, 방향성을 **절대 지어내면 안 된다.**

---

## 0. 한 줄 정의

**CVND**는 인도의 홍수 재난에서 **"위성으로 관측된 물리적 침수 규모가 같을 때, 행정구역(district)의 도시화 정도에 따라 뉴스 보도량이 달라지는가"** 를 검증하기 위한 재현 가능한 측정 파이프라인이다.

핵심 설계 철학은 **"측정의 출처(provenance)가 표본 크기보다 우선한다"** 이다. 표본을 늘리기 위해 측정 정의를 느슨하게 하지 않으며, 추정할 수 없으면 계수를 만들어내는 대신 `not estimable`을 반환한다.

---

## 1. 연구 질문과 가설

### 1.1 가설

- **H1**: 침수 면적이 클수록 뉴스 기사 수가 많다.
- **H2**: 관측된 침수 면적을 통제한 뒤에도, district의 **도시 인구 비율(urban population share)** 이 높을수록 추가적인 보도량이 관측된다.

반대 방향 결과나 결론 불가 결과도 명세를 바꾸지 않고 그대로 보고한다. 이는 코드에 고정되어 있다.

### 1.2 이 연구가 주장할 수 있는 것

- **"관측된 침수 규모가 비슷한 조건에서"** 보도량의 연관(association)

### 1.3 이 연구가 절대 주장하지 않는 것 (논문 서술 시 필수 준수)

- 의도적 외면, 언론의 차별 의도
- 인과관계 (causal discrimination)
- 총 피해량이 같다는 주장 (침수 면적은 모든 재난 피해를 대리하지 않는다)
- "마땅히 받아야 할 보도량(deserved coverage)"
- 1인당 보도량 — **인구 offset을 쓰지 않으므로 추정 대상은 절대 보도량**이다

---

## 2. 관측 단위와 키 구조

**주 관측 단위: 홍수 이벤트 × district (행정구역 2단계, admin-2)**

| 키 | 의미 |
|---|---|
| `event_id` | EM-DAT 상위(parent) 이벤트 ID (E### 형식) |
| `source_record_id` | EM-DAT 공식 DisNo. — 같은 공식 홍수에 속한 state/district를 묶음 |
| `event_district_id` | 이벤트 × district 결정론적(deterministic) 키 |

**엄격한 규칙**: state 단위 값은 district 관측의 근거가 될 수 없다. state 침수 면적과 state 기사 수는 결코 district 관측으로 확장(expand)되지 않는다. state-only 진입점은 코드에서 제거되었다.

인도의 주(state)는 대도시 district와 농촌 district를 동시에 포함하므로, state 단위 비교로는 도시/농촌 차이를 분리할 수 없다. 이것이 district 단위를 고수하는 이유다.

PSS/MSS 등 복합 점수는 사용하지 않는다.

---

## 3. 데이터 소스 전체 목록

| 소스 | 용도 | 비고 |
|---|---|---|
| **EM-DAT** (CRED/UCLouvain) | 홍수 이벤트 레지스트리 | 공식 워크북 `EM-DAT-BASE.xlsx`, 75개 source record |
| **Census of India 2011** | district 총/도시/농촌 인구 | 640개 district, 원본 바이트와 SHA-256 보존 |
| **FAO GAUL 2015 level-2** | district AOI 폴리곤 (1차) | |
| **geoBoundaries gbOpen India ADM2** | AOI 복구 (2차) | 발행자 기준 2021년 기준, ODbL 1.0 |
| **OpenStreetMap relations** | AOI 복구 (3차, 5건) | admin_level=5, LGD 코드 확인, ODbL 1.0 |
| **Sentinel-1 (SAR)** | 침수 면적 측정 (Track A 주력) | VV, Otsu 임계값 |
| **Sentinel-2 (광학)** | NDWI 침수 면적 | L2A(SR) 및 L1C+s2cloudless |
| **JRC Global Surface Water** | 상시 수역 제외 마스크 | occurrence ≥ 50% |
| **India LSIB** | 국경 마스크 | |
| **ESA WorldCover** | 건물/농경지 층화(strata) | 변환기(converter)에 사용 |
| **GDELT GKG (BigQuery)** | 기사 메타데이터 | 과거 색인 |
| **SITS 모델 체크포인트** | 시계열 위성 추론 | 로컬 234MB, 체크섬 검증, 파이프라인이 다운로드하지 않음 |

---

## 4. 이벤트 레지스트리 구축

### 4.1 규모

| 항목 | 값 |
|---|---|
| EM-DAT source record | 75개 (워크북), 현재 레지스트리에 72개 반영 |
| 상위(parent) 이벤트 | **190개** |
| 이벤트 × district 행 | **1,630행** (감사 산출물 기준) |
| 고유 district | **556개** |
| 고유 state | **31개** |
| 발생일 범위 | **2015-03-20 ~ 2025-10-03** |

> ⚠️ **수치 불일치 주의**: 현재 `event_districts.csv` 파일은 **1,623행**이고, 모든 QC·분석 산출물(`district_qc.json`, `coverage_summary.json`, `district_flood_articles.csv`)은 **1,630행** 스냅샷 기준이다. 레지스트리 재생성이 진행 중이기 때문이다.
> **논문에는 1,630 기준으로 일관되게 쓰고, 최종 제출 전 재확인이 필요하다고 명시할 것.**

### 4.2 district 복구 매핑

사용자가 공급한 exhaustive recovery 파일에서 **maximal candidate를 모두 수용**해 두 파일로 변환했다.

- `district_recovery_mapping.csv`: 1,374행, 154개 이벤트 커버. 이벤트 정체성, 표준 district명, 출처 메타데이터, 증거 텍스트 저장. **recovery confidence / tier 열은 저장하지 않는다.**
- `district_recovery_aliases.csv`: **40건** (문서에는 33건으로 적혀 있으나 실제 파일은 40행 — **파일이 기준**). 철자 교정, 복합명 분리, 비-district 항목 제거. ID 생성 **전에** 적용.
  - 경계 크로스워크(boundary-crosswalk) 동작은 **제외**했다. 현재 이름이 Census 2011 경계 동등성을 입증하지 못하기 때문이다.

### 4.3 제외된 14개 이벤트

district 후보가 하나도 없어서 `events.csv`와 `event_districts.csv` 양쪽에서 제외:

`E006, E007, E011, E018, E043, E062, E063, E083, E102, E105, E123, E147, E149, E155`

### 4.4 district 출처 분포 (현재 파일 1,623행 기준)

| `district_source` | 행 수 |
|---|---|
| external_recovery | 1,303 |
| gadm | 67 |
| admin_units\|gadm | 48 |
| external_recovery\|location | 46 |
| admin_units | 37 |
| location | 32 |
| gadm\|location | 31 |
| admin_units\|gadm\|location | 26 |
| 기타 조합 | 33 |

구조화된 GADM/Admin Units 필드를 우선하고, 보수적으로 파싱한 자유 텍스트 Location 증거는 **별도로 식별 가능하게** 유지한다. 미해결 district는 감사(audit) 행으로 남기며, 주도(capital)나 퍼지 매칭으로 대체하지 않는다.

### 4.5 날짜 정밀도 (중요한 한계)

| `date_precision` | 행 수 |
|---|---|
| start:day \| end:day | 1,379 |
| start:month \| end:day | 228 |
| start:month \| end:month | 16 |

→ **244행(15.0%)의 발생일이 월 단위로만 확정**되어 있다. 이 행들의 14일 뉴스 관측창은 타이밍 불확실성을 가진다. 논문의 limitation에 반드시 포함할 것.

---

## 5. 행정구역 경계(AOI) 해결과 복구

### 5.1 왜 중요한가

district마다 고유 폴리곤을 확정하는 것이 물리적 측정의 **결정적 제약(binding constraint)** 이다. 폴리곤이 없으면 침수 면적이 없다.

### 5.2 복구 결과

| 단계 | 값 |
|---|---|
| GAUL 2015 1차 조회 후 미매칭 | **464행** |
| 복구 성공 | **458행 (98.7%)** |
| └ geoBoundaries ADM2 | 173개 district명 / 451행 |
| └ OSM relation | 5개 district명 / 7행 |
| 최종 상태 | **OK 1,549 / NO_IMAGERY 75 / ERROR 6** |
| 기존 성공 행 (변경 없음) | 1,172행 |

### 5.3 매칭 안전장치

- **퍼지 최근접 이름 매칭 없음.** state 범위 별칭(state-scoped alias)과 수동 검토된 개명만 허용.
- 상위 district나 state로의 fallback **금지**.
- 후보 폴리곤 검증: 유효성, 고유 정체성, 해당 state 레이어와 **≥90% 중첩**, 같은 ADM2 레이어 내 이웃과 **>1% 중첩 없음**.
- 이는 **내부 일관성 검사**이며, 역사적 측량 경계에 대한 검증이 아니다.
- OSM 선택은 명시적 relation ID, `admin_level=5`, state 일치, LGD district 코드를 요구. 4건은 공표 면적과 10% 이내 일치.
  - **Shamator 거부 사례**: OSM 약 193 km² vs district 웹사이트 469 km² → 불완전으로 판단해 거부.
  - **Tamulpur**: 검증된 공표 면적 비교가 없어 다른 4건보다 신뢰도 낮음.

### 5.4 ⚠️ 비가산성(non-additivity) — 논문에서 반드시 다룰 것

복구는 커버리지를 얻는 대신 **혼합 기준연도(mixed reference vintage)** 데이터셋을 만들었다. GAUL 2015 상위 폴리곤과 2021 ADM2 레이어가 공존하므로, 오래된 상위 폴리곤이 신설 하위 district와 겹칠 수 있다.

| 항목 | 값 |
|---|---|
| 같은 이벤트 내 중첩 쌍 (>1%) | **422쌍** |
| 관련 이벤트 수 | **101개** |
| 그중 서로 다른 출처 간 쌍 | 419쌍 |

**→ district 침수 면적을 더해서 이벤트 총합을 만들면 안 된다.** 유효한 이벤트 총합은 공통의 비중첩 지리 또는 픽셀 단위 침수 마스크의 합집합을 요구한다.

**정확한 기하 중복 3건** (레지스트리 표기만 다름): E056 Bara Banki/Barabanki, E081 West Karbi-Anglong/West Karbi Anglong, E154 Ri-Bhoi/Ri Bhoi. 원본 행은 보존하되 고유 district 집계에서 이중 계수하지 않도록 플래그 처리.

### 5.5 미해결 6건 (0이 아니라 명시적 미해결)

| district | 사유 |
|---|---|
| Itanagar Capital Region | 검토 레이어에 적합한 district 폴리곤 없음 |
| Jogbani | 자치시(municipality) — Araria district를 쓰면 요청 면적이 확대됨 |
| Chengannur | 읍/taluk — Alappuzha district를 쓰면 면적 확대 |
| Mumbai | 레지스트리상 시(city) vs 교외(suburban) district 범위 모호 |
| Chumoukedima | 공표 면적 충돌, 보조 폴리곤 미검증 |
| Shamator | 보조 폴리곤이 공식 면적 대비 불완전 |

### 5.6 출처 표기 필드

각 행이 보유: `aoi_source`, `geometry_id`, `aoi_match_method`, `aoi_boundary_year`, `aoi_historical_boundary_verified`, `aoi_match_evidence`, `aoi_boundary_note`.

**핵심 해석**: 매칭 성공은 *"폴리곤이 명시적으로 선택되었다"* 는 뜻이지, *"그 경계가 사건 당일의 경계와 같다"* 는 뜻이 아니다.

### 5.7 재현성

- geoBoundaries 고정 리비전 `9469f09`, India ADM2 SHA-256 `8bef6929fd65...46db40`
- 공표 ADM2 단위 수는 736이지만 실제 다운로드된 GeoJSON은 **735개 피처** → 공표 수치가 아니라 **파일의 SHA-256**을 재현성 기준으로 사용

---

## 6. Census 2011 커버리엇

### 6.1 변수

`urban_population_share = urban_population / total_population` — **연속 변수로 유지**. 임의의 도시/농촌 절단점은 주 모형에 들어가지 않는다.

### 6.2 매칭 결과

| 항목 | 값 |
|---|---|
| Census 매칭 성공 | **1,488 / 1,630 행 (91.3%)** |
| 연결된 지역 | 506 / 566 (39건 추가 복구) |
| 미연결 지역 | 60개 지역 / 128 행 |
| 모호(ambiguous) 판정 | 14행 (7개 동일 이벤트 별칭 쌍) |

### 6.3 분포 (n = 1,502)

| 통계량 | 값 |
|---|---|
| 평균 | 0.2214 |
| 표준편차 | 0.1976 |
| 최소 | 0.0 |
| 25% | 0.0892 |
| **중앙값** | **0.1502** |
| 75% | 0.2863 |
| 최대 | 1.0 |

**3분위 절단점** (선택 QC 전용, 고유 district 기준): `[0.1377, 0.2687]`

### 6.4 복구 방법 (2가지만 허용)

- `census_name_link`: 명시적으로 인용된 이름 동등성 또는 역사적 state 소속을 통해 원본 2011 PCA district에서 인구 취득
- `official_retabulation`: 원래 Census 지리 이후 신설된 district에 대해 **정부 공표 2011년 총/농촌/도시 인구표** 사용

**금지**: state 평균 대체, 면적 가중, 상위 district 프록시. 인구 합계는 정확히 일치해야 하며 불일치는 검증 실패.

재표(retabulated) 단위는 `retabulated:` 접두사 식별자를 쓰며, **가짜 Census 2011 숫자 코드를 만들지 않는다.**

### 6.5 주요 출처 사례

- **Telangana 2016년 9월 이벤트**: 2016년 10월 재편 **이전**의 원래 Andhra Pradesh PCA 지리 사용 (Karimnagar, Medak, Warangal). 이후 Telangana 항목은 정부 2023 Outlook, Annexure 18 사용.
- **Assam**: Statistical Abstract 2021, Table 1.02
- **Meghalaya**: Statistical Handbook 2023 (2024년 9월 최종본), Table 1.03 — district 웹사이트의 상충하는 잠정치 대신 사용
- **Namsai, Balod**: district 정부 표. Balod는 농촌 = 총 − 도시로 도출.

### 6.6 미해결 사례 (자동 조정하지 않음)

- **Morbi**: district 웹페이지의 총인구와 도시+농촌 합계가 3명 차이
- **Palghar**: 정부 출처들이 총계와 도시 비율을 상충되게 보고
- 일부 공식 PDF 엔드포인트 타임아웃 → 사용 불가/상충 증거는 **0으로 취급하지 않음**

### 6.7 한계

2011년 인구 기준이며 홍수 발생 시점의 인구 추정치가 아니다. 이름과 보고된 행정 면적이 일치한다고 해서 **위성 폴리곤과 동일함이 입증되지는 않는다.** 즉 도시화율은 **사전(pre-period) 고정 공변량**이다.

---

## 7. 위성 측정 명세 (MeasurementSpec)

### 7.1 동결(frozen) 명세와 해시 무효화 — 이 프로젝트의 핵심 기여

모든 위성 면적은 **단 하나의 `MeasurementSpec`** (`src/flood_spec.py`) 아래에서 생산된다. 이 명세는 해시되어 `spec_version`으로 식별되며, **모든** Track A 행, HDF5 패치, 점수 아카이브, 병합 행, 면적 테이블 행에 각인된다.

```python
SPEC = MeasurementSpec()
SPEC_VERSION = 'fs1-' + sha256(payload).hexdigest()[:12]
```

**→ 명세를 수정하면 모든 위성 캐시가 설계상 무효화된다. 낡은 행은 폐기되며, 결코 조용히 재사용되지 않는다.**

무효화는 `stale_spec_mask(frame, expected=SPEC_VERSION)`가 강제한다. `spec_version`이 없거나 다른 행은 모두 stale로 표시되고, 캐시 전체가 `expected {SPEC_VERSION}. Regenerate satellite caches.` 메시지와 함께 재생성을 요구한다.

> ⚠️ **실제로 지금 이 상태다.** 현재 코드가 선언하는 `SPEC_VERSION`은 **`fs1-3016a20fd3ad`** 이지만, 작업 복사본의 위성 캐시 `data/cache/district/flood_extent.csv`(2행)는 **`fs1-8d55f7c25c28`** 을 갖고 있다. 즉 명세가 그 캐시 생성 이후 변경되었고, 해당 행들은 stale로 폐기된다. **이것은 §11의 N=0을 설명하는 두 번째 독립적 원인이며, 메커니즘이 실제로 작동한다는 검증 가능한 증거다.**

같은 메커니즘이 이벤트 레지스트리에도 적용된다. 레지스트리 fingerprint를 모든 파생 산출물과 기사 수집 manifest가 보유한다. **§11의 N=0 상황이 바로 이 메커니즘이 작동한 결과다.**

### 7.2 명세 세부

| 요소 | 정의 |
|---|---|
| **Post 창** | `[onset, onset + 14일)` — **뉴스 관측창과 동일** |
| **Pre 창** | `[onset − 30일, onset)`, 픽셀별 중앙값 |
| **Post 합성** | max-water 합성: speckle 필터링된 S1 VV의 픽셀별 **최솟값**, S2 NDWI의 픽셀별 **최댓값**. 추정 대상은 "뉴스 창 안에서 관측된 최대 침수 범위". 구름 그림자가 최대 합성에서 살아남을 수 있으므로 S2 장면 분류 구름 마스크는 계속 켜두고, `median` post 합성을 명세 민감도로 제공 |
| **침수 정의** | `water(post) AND NOT water(pre) AND eligible` — 모든 센서에 동일 |
| └ S1 | 양쪽 궤도 방향, Otsu 임계값을 **[−20, −13] dB로 클램프**, fallback 플래그 기록 |
| └ S2 | NDWI > 0 |
| └ SITS | SITS 타일 위의 NDWI |
| **적격성 마스크** | JRC 상시 수역 아님(occurrence ≥ 50%) AND 경사 < 5° AND 인도 LSIB 내부 — **모든 경로에 동일 적용** |
| **격자** | district당 하나의 픽셀 격자: AOI 중심의 UTM 존, **10 m 정사각 픽셀**, 640 m SITS 타일 격자에 스냅. Track A 축약(`crs`+`crsTransform`)과 Track B 다운로드(`crs_transform`+`dimensions`)가 같은 격자를 사용 → **Track A 픽셀과 Track B 픽셀이 동일 픽셀**, 타일은 모든 위도에서 정확히 64 px |
| **면적** | 해당 격자 위 `ee.Image.pixelArea()`의 **비가중(unweighted) 합** |

### 7.3 비가중 합이 중요한 이유 (논문에 쓸 만한 구체 사례)

재투영된 JRC/LSIB 마스크는 역사적으로 습한 지역을 따라 **약 19%의 픽셀에 분수(fractional) 마스크 가중치**를 갖는다. 가중 합은 이 픽셀들을 부분적으로만 계수했다.

> **Darbhanga 사례**: S1 신규 수역이 **가중 385 km² vs 비가중 760 km²**. 다운로드된 Track B 픽셀은 비가중 계수와 **0.15% 이내로 일치**.

`bestEffort`는 어떤 축약에도 사용하지 않는다. Earth Engine 한계를 초과하는 전체 AOI 축약은 격자 정렬된 하위 사각형들로 나눠 합산하며(같은 픽셀, 같은 스케일), 지속적 실패는 `error_kind`로 기록한다. 대규모 축약은 공유 4-worker 분할 풀을 사용한다.

### 7.4 기록되는 footprint

`eligible_km2`, `optical_observed_km2` (적격이면서 두 합성 모두에서 S2가 관측한 픽셀 — NDWI 신규 수역이 0이 아닐 수 있는 **유일한** 픽셀), `s1_on_optical_km2`, 두 값의 중첩, WorldCover 건물/농경지 층, 센서별 첫 post 취득일. AOI 기반 `flood_ratio` 옆에 적격 면적을 분모로 하는 `flood_ratio_eligible`도 기록.

---

## 8. 측정 트랙과 라우팅

### 8.1 Track A (현재 기본값)

Sentinel-1 / Sentinel-2 직접 측정. `SATELLITE_TRACK=A`가 명시적 기본값.

### 8.2 Track B (SITS)

district별 SITS HDF5 패치 준비 → 로컬 체크포인트로 CPU/GPU 추론 → provenance를 담은 NPZ 산출. HDF5 입력은 추론 후에도 보존. 체크포인트는 체크섬 검증되며 파이프라인이 다운로드하지 않는다.

### 8.3 라우팅 모드 2가지

#### (a) `s1_interim` — **현재 기본값**

Track B가 모든 district를 덮고 변환기가 결정될 때까지, **모든 district를 Track A Sentinel-1 신규 수역으로만** 측정한다.

- `satellite_source = S1`, `route_reason = interim_s1_only`
- 모든 district에 **단일 센서** → 센서 혼합 없음, Track B 진척도에 의존하지 않음
- S1 pre/post 영상이 없는 district는 NA (`no_s1`)
- SITS 열은 Track B가 존재하는 곳에 참고용으로만 채움

#### (b) `sits_primary` — 설계상의 목표 상태

SITS가 주 측정. district마다 `sits_status` 부여:

| `sits_status` | 처리 |
|---|---|
| `pending` | Track B 미실행/미완료(H5 생성 시 `.blocks.json` 마커 존재 ~ 마지막 블록까지)/미추론 → 면적 **NA** (`sits_pending`). **결코 조용한 S1 값으로 대체하지 않음** |
| `unavailable` | pre/post 영상 없음, 맑은 기준선 없음, 보존 타일 없음 → 자료 조건 |
| `ok` | SITS 게이트 통과 |

점수는 패치를 **위치 지정**하고 NDWI가 물을 **정량화**한다. **플래그된 패치 범위 자체는 결코 면적이 아니다.** 게이트 통과 시 플래그된 타일 내부 NDWI를 사용하되, 게이팅이 물의 절반 미만만 남겼고 **동일한 사용 가능 픽셀 위의 S1**이 더 큰 범위를 확인해줄 때만 모든 보존 타일로 복원. 게이트 실패 시 모든 보존 타일의 NDWI 사용.

> NDWI 보정은 **내부 광학 신호와의 일치**이지 지상 실측(ground-truth) 검증이 아니다.

### 8.4 변환기 (S1 → SITS-NDWI 스케일)

SITS가 측정할 수 없는 district(`unavailable`, 또는 사용 가능 픽셀이 적격 AOI의 `sits_usable_min_frac` 미만)는 S1 신규 수역을 SITS-NDWI 스케일로 변환(`satellite_source = S1_TO_SITS`).

변환기는 `src/compare_tracks.py`가 **사전 등록된 규칙**(`flood_spec.ConverterRules`, `rules_version`으로 해시)에 따라 **쌍(paired) footprint C** 위에서 결정한다. C = 적격 ∧ AOI 내부 ∧ 모든 SITS 시점에서 맑음 ∧ NDWI pre/post 관측됨 ∧ 보존 타일 위.

| 결정 | 규칙 | 효과 |
|---|---|---|
| `insufficient` | 쌍 district < 30개 (A_ndwi(C) ≥ 1 km²) 또는 state < 5개 | S1_TO_SITS 행 **NA** |
| `identity` | TOST: 로그비 중앙값의 90% state-클러스터 부트스트랩 CI가 ±log 1.2 이내; 이질성 p > 0.10; 통합 IoU ≥ 0.5 | 변환값 = S1, 라벨 유지 |
| `linear` | 비동등, 동질적, Deming 기울기 95% CI 폭 ≤ 0.5 | log-log Deming; LOSO-CV 오차 보고 |
| `stratified` | 그 외, 건물/농경지 비율 포함 로그선형 모형의 LOSO-CV 중앙 오차 ≤ 1.25배 | 층화 변환 |
| `excluded` | 그 외 | S1_TO_SITS 행 **NA**; S1 결과는 민감도 전용 |

**이질성 검정**: C 위에서 로그비를 건물/농경지 비율, S1 post 영상 수, 궤도, 연도 ≥ 2022, 구름 비율, Otsu fallback에 대해 결합 검정. **HC3 공분산 + F 기준** 사용 (20개 state의 state-클러스터 CR1-F). **HC1 + χ²는 기각**했다 — 이 표본 크기에서 명목 10% 수준일 때 순수 잡음을 **20–37%** 확률로 기각하기 때문.

변환 전 **정체성 검사**: Track A의 AOI 전역 NDWI 신규 수역을 다운로드된 Track B 블록 픽셀(`block_stats`)로 재구성. 상대 차이가 **1% 초과**하거나 중복 타일/중복 블록이 있으면 버그로 표시하고 해당 district를 변환기 적합에서 제거.

### 8.5 센서 차이 (limitation)

SAR는 식생 아래와 건물 지역(double bounce)의 물을 놓친다. McFeeters NDWI는 일부 건물 표면을 물로 표시한다. 위성 출처 고정효과, 출처별/SITS-only 부분표본은 **민감도 분석이지 보정이 아니다.**

### 8.6 legacy 라우팅 비교

리팩터 이전 라우팅(SITS 미실행 시 항상 S1, 60% 구름 절단)은 `legacy_*` 열로 보존. `data/results/routing_comparison.json`이 (a) legacy, (b) 현재 주 라우팅, (c) SITS 출처만, (d) Track A 명세 변형(`pre_same_season_3y`, `jrc_seasonal_10`, `mndwi`)을 라우팅된 센서의 상대 변화로 적용한 결과에 대해 Model 2를 적합한다. legacy 결과는 도시화 계수 차이가 (b)의 95% CI 폭의 **절반 미만**일 때 강건(robust)하다고 부른다.

**현재 상태**: `verdict = "not assessable: legacy or primary Model 2 not estimated"` (N=0이므로)

---

## 9. Sentinel-2 가용성 프로브 (Phase −1) — **완료된 실증 결과**

`src/sits_feasibility.py`, Earth Engine 쿼리만 사용. **이것은 실제로 완료된 결과이므로 논문에 자신 있게 쓸 수 있다.**

| 항목 | 값 |
|---|---|
| probe_version / spec_version | `feas-1` / `fs1-3016a20fd3ad` |
| 프로브 대상 행 | 495 |
| AOI 매칭됨 | **255** (미해결 152, 실패 88) |

### 9.1 가용성 비교

| 지표 | **L2A (SR)** | **L1C + s2cloudless** |
|---|---|---|
| 불가용 행 | **162 (63.53%)** | **103 (40.39%)** |
| └ post 영상 없음 | 148 | 91 |
| └ pre 영상 없음 | 10 | 5 |
| └ 보존 타일 없음 | 4 | 5 |
| └ 맑은 기준선 없음 | 0 | 2 |
| 사용 가능 타일 비율 중앙값 | **0.2831** | **0.0950** |
| 10% 분위 | 0.0535 | 0.0013 |
| 90% 분위 | 0.7214 | 0.6142 |
| 보존 타일 수 | 450,358 | 584,536 |
| HDF5 용량 (현재 레이아웃) | 156.8 GB | 203.5 GB |
| HDF5 용량 (계획 레이아웃) | **92.3 GB** | **119.7 GB** |
| 추정 추론 시간 | **40.3 시간** | **59.4 시간** |
| 쌍 표본 (district/state) | 65 / 12 | **98 / 14** |

구름 마스크: SR은 `SCL exclude [3, 8, 9, 10, 11]`, L1C는 `s2cloudless probability < 40`.

### 9.2 연도별 SR 불가용률 — **핵심 발견**

| 연도 | n | 불가용률 |
|---|---|---|
| 2015 | 43 | **1.000** |
| 2016 | 41 | **1.000** |
| 2017 | 66 | 0.924 |
| 2018 | 10 | 0.900 |
| 2019 | 36 | 0.167 |
| 2020 | 12 | 0.083 |
| 2021 | 22 | **0.000** |
| 2022 | 4 | **0.000** |
| 2023 | 7 | 0.143 |
| 2024 | 9 | **0.000** |
| 2025 | 5 | **0.000** |

→ SR 불가용 행의 **95.06%가 2018년 이하**에 집중 (마지막 gap year = 2018). Sentinel-2가 2015–2016년 인도를 거의 촬영하지 않았고, SR은 2018년 말 이전에는 희소하다.

### 9.3 L1C 구제 효과

| 항목 | 값 |
|---|---|
| SR 불가용 | 162 |
| L1C가 구제 | **59 (36.42%)** |

### 9.4 게이트 판정

```
verdict: "consider_l1c"        ← 무조건 전환이 아니라 "검토하라"
basis_source: l1c
sr_unavailable_rate: 0.6353
max_unavailable_rate: 0.30     ← 목표 상한
l1c_unavailable_rate: 0.4039
l1c_still_above_max: true      ← L1C도 여전히 목표 초과
converter_sample: "expected_sufficient"
paired_districts: 98 (최소 30), paired_states: 14 (최소 5)
```

**해석**: L1C는 가용성을 높이지만 사용 가능 타일 비율 중앙값이 0.283 → 0.095로 떨어진다. **장면 수는 늘고 장면의 질은 떨어지는 교환(trade)** 이다. 그래서 게이트가 무조건 전환이 아니라 `consider_l1c`를 반환한다.

> 주의: 타일 수량은 더 거친 격자를 640 m 타일로 평균한 **추정치**이며, Track B를 재현한 것이 아니다.

---

## 10. 기사(뉴스) 측정

### 10.1 수집 정의

- **소스**: GDELT GKG 과거 메타데이터 (BigQuery)
- **관측창**: `start_date ≤ article_date < start_date + 14일` (UTC, **반열린 구간**). 사전 기간(anticipation period) 없음.
- **필수 증거**: 구조화된 위치 증거가 **district를 명시적으로 식별**하고 **state를 명확히 구분**해야 함
- **state 언급만으로는 district 보도를 만들 수 없다** ← 절대 규칙
- 선택적 제목 증거는 district와 state를 모두 명시해야 하며 기록됨
- 다중 district 매칭은 **각각 명시적 증거가 있을 때만** 허용
- 중복 제거: 정규화된 URL/state/district 기준, 가장 가까운 발생일 선택(결정론적 동점 처리)
- 같은 URL이 명시적으로 언급한 여러 district에 계수될 수 있음
- 분류 결과는 district 관측에 붙어 있으며, URL을 중첩된 상위 이벤트로 재확장할 수 없음

### 10.2 관련성 판정

1차 판정은 성공적으로 취득된 본문에 대한 **기존 다국어 홍수 키워드 heuristic** (`src/district_heuristics.py`)이다.

- 이는 **사건별 의미적 관련성을 입증하지 않는다.**
- 발생일 근접성은 **결정론적 할당 규칙**이지 진실이 아니다.
- 향후 사람 검증이 district, 언어, 시간, 도시화별 오차를 추정해야 강한 과학적 결론이 가능하다.

### 10.3 0 vs 결측 구분 (매우 중요)

| 상황 | 값 |
|---|---|
| 쿼리 성공 + 일치 후보 0건 | **관측된 0** (이 수집 정의 하의 참 0) |
| 미실행 / 실패 / 불완전 수집 | **결측 (NA)** |
| 원본 페이지 취득 실패 | 키워드 음성 본문과 **별도로** 표현 |

계수는 "확인되고 접근 가능하며 heuristic 양성인 GDELT 기사"를 의미하며, **모든 보도를 의미하지 않는다.**

### 10.4 ⚠️ state 코퍼스 재사용 실패 — **완료된 음성 결과, 논문의 핵심 기여 중 하나**

기존 state 단위 코퍼스가 district 수집을 대체할 수 있는지 시험했다. `src/reuse_state_articles.py`가 기존 state JSONL과 SQLite 본문 DB를 **BigQuery 쿼리나 페이지 다운로드 없이** 읽는다.

감사 결과 (`data/intermediate/state_article_reuse_audit.json`):

| 항목 | 값 |
|---|---|
| 입력 행 | **507,076** |
| 이벤트 정체성/state/관측창 선택 통과 | **127,252 (25.1%)** |
| **district 배정 성공** | **762** |
| district 미해결 | **126,557** |
| 관측창 밖 또는 정체성 불일치 | 379,824 |
| LLM 상태 | `not_submitted` |

**→ 전체 코퍼스의 0.15%, 관측창 내 후보의 0.6%만 district로 해소된다.**

**결론: state 단위 코퍼스는 지름길이 아니다.** district 명시 수집 또는 기사별 판정이 불가피하다. 이 경로로 얻은 계수는 **후보(candidate)이지 연구 관측치가 아니다.**

> 참고: `PROJECT_CONTEXT.md`에는 더 오래된 수치(126,885 / 750 / 126,202 / 380,191)가 있다. **JSON 감사 파일의 수치가 최신이므로 위 표를 사용할 것.**

### 10.5 기사 QA 운영 파이프라인 (3단계)

현재 범위: `local_state_plus_targeted_bigquery`. **표적 보완은 일부 로컬 후보가 있는 모든 district의 완전한 커버리지를 확립할 수 없다.**

**1단계 — 무과금 준비**
```
article_qa.py prepare / counts
```
state JSONL과 SQLite는 읽기 전용. `requests.jsonl`은 district 후보를 담은 기사/이벤트 요청 1건씩, `pending.jsonl`은 누락/실패 본문 유지. **confidence 필드는 방출하지 않는다.**

**2단계 — 표적 보완 (BigQuery)**
```
article_qa.py supplement --maximum-tib 0.25          # dry-run 추정, 과금 아님
article_qa.py supplement --execute --maximum-tib 0.25
article_qa.py download-new
```
30일 창에서 사용 가능한 로컬 district 증거가 없는 district를 대상으로, 엄격한 테마, district/state 증거, 풍부한 메타데이터, 제목 fallback 사용. **하나의 결합 쿼리**가 모든 공백을 덮으므로 상한이 전체 실행에 적용된다. URL이 적게 반환된다고 스캔량이 작다는 뜻은 아니다. 성공한 0-결과 쿼리도 기록된다.

**3단계 — LLM Batch QA** (문서상 `LLM_QA_MODEL=gpt-5.6-luna`)
```
article_qa.py submit --execute / status / collect / counts
article_qa.py run-batches --execute      # 60초 폴링, Ctrl-C 시 원장 보존
```
샤드당 최대 1,000 요청 / 4 MB JSONL, 동시 활성 배치 1개.

**무결성 규칙**:
- 모든 후보가 구조화된 응답에 **정확히 한 번** 나타나야 함. 미지/중복/누락 ID는 요청 실패.
- 관련 증거는 **제공된 텍스트의 정확한 발췌**여야 함.
- **기사 내용은 신뢰할 수 없는 입력이며, 결코 분류기에 대한 지시가 아니다.** (프롬프트 인젝션 방어)
- 제출 확인이 유실되면 러너가 먼저 제공자 배치 메타데이터를 검색. 해소 불가한 제출은 명시적 재시도까지 중단하며, 첫 시도가 거부되었다고 **가정하지 않는다.**

**산출**: `counts_14d.csv`가 주 조인에 투입. `counts_30d.csv`는 별도 민감도 테이블(`district_flood_articles_30d.csv`)로 분리 — **위성 post 창은 14일로 유지된다.**

실패한 요청은 자동 진행을 중단시킨다. 누락 텍스트와 불확실 판정은 미관측으로 남고, 해당 district의 최종 계수는 **NA**가 된다.

---

## 11. ⚠️ 현재 상태: 결과 대기 중 (반드시 읽을 것)

### 11.1 현재 분석 가능 표본 = 0

`outputs/paper_results.md` 및 `outputs/coverage_summary.json` 기준:

```
N = 0 district-event observations; 0 districts; 0 parent events; 0 source floods.
Excluded: 1630 of 1630 registry rows.
Spearman rho = None; p = None.
conclusion_candidate: "Insufficient valid data or stable model fits to assess H1 and H2.
                       No empirical conclusion is available."
```

### 11.2 단계별 QC (1,630행 기준)

| 단계 | 성공 | 비율 |
|---|---|---|
| district 정체성 추출 | 1,630 / 1,630 | **1.000** |
| Census 2011 매칭 | 1,488 / 1,630 | **0.913** |
| district AOI 매칭 | 0 / 1,630 | **0.000** |
| 위성 관측 | 0 / 1,630 | **0.000** |
| GDELT 수집 | 0 / 1,630 | **0.000** |
| 기사 관측 | 0 / 1,630 | **0.000** |
| **최종 분석 가능** | **0 / 1,630** | **0.000** |

### 11.3 왜 0인가 — 버그가 아니라 설계된 동작

**(1) 위성 산출물이 레지스트리 재생성으로 무효화됨**

위성 캐시는 실제로 **OK 1,549행**에 도달했었다(§5.2). 그러나 이벤트 레지스트리가 재생성되면서 fingerprint가 바뀌었고, §7.1의 무효화 메커니즘이 이전 레지스트리에 대해 생산된 파생 위성 산출물을 **정확하게 폐기**했다.

`data/intermediate/registry_cache_migration.json`:
```
old_registry_sha256: a5a029cc...9d34866
registry_sha256:     33bff3b5...b4e754a468af9f
status: "derived_outputs_stale"
district_aoi:            previous 1,630 → retained 1,616
district_flood_extent:   previous 1,630 → retained   455
```
변경되지 않은 ID, 정체성, 기하 ID만 migration에서 살아남는다. **서로 다른 참조의 기하 값은 결코 결합되지 않는다.** 낡은 기사 manifest는 레지스트리 해시 검사에 실패하며 재생성되어야 한다.

**(2) 측정 명세(spec) 해시가 캐시와 불일치**

현재 코드 `SPEC_VERSION = fs1-3016a20fd3ad` vs 캐시 `flood_extent.csv`의 `fs1-8d55f7c25c28`. `stale_spec_mask`가 이 행들을 stale로 표시해 폐기한다 (§7.1 참조). 레지스트리 무효화와 **독립적인 두 번째 원인**이다.

**(3) district 기사 수집이 미완료**

LLM-QA 요청이 아직 제출되지 않았다(`state_article_reuse_audit.json`의 LLM 상태 = `not_submitted`).

`district_gdelt.manifest.json`은 **이 작업 복사본에 존재하지 않는다.** `PROJECT_CONTEXT.md`는 이 파일이 spatial unit `district`, window 14일, collection status `incomplete` 상태였다고 기록하지만, 현재 `data/intermediate/`에는 없다. **파일의 부재 자체가 district 수집이 현재 레지스트리 하에서 실행되지 않았다는 더 강한 증거다.**

### 11.3.1 ⚠️ 이 작업 복사본 vs 전체 데이터 트리 (혼동 방지)

`C:\CVNDrefact`는 **코드와 감사 산출물의 스냅샷**이며 전체 데이터 트리가 아니다. 대용량 원시 파일은 포함되어 있지 않다.

| 자산 | `PROJECT_CONTEXT.md` 기록 | 이 작업 복사본 |
|---|---|---|
| `gdelt_bq.articles.jsonl` | 507,076행, 약 280 MB | **없음** |
| `gdelt_bq.articles.sqlite` | 약 1.9 GB 본문 DB | **없음** |
| SITS 체크포인트 | 약 234 MB | **없음** |
| SITS HDF5 패치 | 상태 레벨 `E043.h5` 약 1.37 GB | **`E082%3A%3Adarbhanga.h5` 1건만** |
| `flood_extent.csv` | 1,630행 → migration 후 455행 보존 | **2행 (stale spec)** |
| `district_gdelt.manifest.json` | status `incomplete` | **없음** |

**→ §10.4의 507,076 / 127,252 / 762 수치는 `state_article_reuse_audit.json` 감사 파일에 기록된 실제 결과이므로 유효하다.** 원본 코퍼스가 이 복사본에 없다는 사실이 그 수치를 무효화하지 않는다. 다만 **재현하려면 전체 데이터 트리가 필요하다**는 점을 논문에 명시할 것.

### 11.4 모든 모형의 현재 상태

| 모형 | 상태 |
|---|---|
| `model_1` | `insufficient sample: N=0 < 20` |
| `model_2` | `insufficient sample: N=0 < 20` |
| `model_3` | `insufficient sample: fewer than two years` |
| `model_2_source_fe` | `insufficient source variation: fewer than two satellite sources` |
| `source_event_robustness` | `insufficient sample: 0 multi-district source events, 0 rows; require ≥10 groups and ≥5*(groups+3) rows` |
| `exposed_population_robustness` | `not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used` |

`coverage_oof_diagnostics.csv`는 **헤더만 있고 데이터 행이 0개**다.

### 11.5 선택 편향 점검 — 현재 제외는 균일하다

| 도시화 그룹 | 행 | 제외 | 제외율 |
|---|---|---|---|
| high | 411 | 411 | 1.000 |
| medium | 399 | 399 | 1.000 |
| low | 692 | 692 | 1.000 |
| unknown | 128 | 128 | 1.000 |

→ **현재 결손은 파이프라인 상태이지 차등적(differential) 결손이 아니다.** 이는 논문에서 중요한 방어 논점이다.

### 11.6 무엇을 기다리고 있는가 (다음 단계)

1. **현재 레지스트리 fingerprint 및 현재 `SPEC_VERSION` 하에서 district 위성 측정 재실행**
   - `SKIP_GEE=0`으로 Track A 재측정 (Earth Engine 인증 + `GEE_PROJECT_ID` 필요)
   - 기존 캐시는 stale spec(`fs1-8d55f7c25c28`)이므로 전량 재생성 대상
   - 필요 시 boundary recovery 재적용: `scripts/run_boundary_recovery.py --workers 8`
   - 전체 데이터 트리(원시 GDELT 코퍼스, SITS 체크포인트) 복원 필요 (§11.3.1)
2. **district 명시 GDELT 수집 완료**
   - BigQuery ADC + `GDELT_BILLING_PROJECT` 필요
   - 표적 보완 → 본문 다운로드 → LLM Batch QA
3. **조인 및 주 분석 재실행** → 이때 비로소 H1/H2 계수가 산출된다
4. Sentinel-2 라우팅 결정 (`consider_l1c` 게이트에 대한 판단)

**→ 논문 작성 AI에게: 위 단계가 완료되기 전까지 `beta_flood`, `beta_urban`, p값, IRR, Spearman rho는 존재하지 않는다. 어떤 값도 만들어내지 말 것.**

### 11.7 테스트 상태

| 항목 | 값 |
|---|---|
| 발견된 테스트 | **218개** |
| 통과 | 215개 |
| 오류 | **3개** (`tests/test_coverage_disparity.py`) |

오류 원인: `src/analyze_coverage_disparity.py`의 `result.model.data.design_info` 접근 — 설치된 statsmodels 버전에 해당 속성이 없음. 요구사항은 `statsmodels>=0.14.6,<0.15`. district recovery, EM-DAT builder, district article, district join 테스트 그룹은 **모두 통과**.

---

## 12. 통계 명세 (사전 등록된 상태)

### 12.1 주 모형

```
Y_ed ~ NegativeBinomial2(mu_ed, alpha)
log(mu_ed) = beta_0 + beta_flood * log(1 + flood_area_km2_ed)
                    + beta_urban * urban_population_share_d
Var(Y_ed) = mu_ed + alpha * mu_ed^2
```

| 모형 | 식 |
|---|---|
| Model 1 | `article_count ~ log_flood_area` |
| **Model 2 (주 모형)** | `article_count ~ log_flood_area + urban_population_share` |
| Model 3 | `article_count ~ log_flood_area + urban_population_share + C(year)` |
| (민감도) model_2_source_fe | `+ C(satellite_source)` |

- **alpha는 최대우도로 추정**하며 1로 고정하지 않는다. statsmodels `negativebinomial(..., loglike_method="nb2", missing="raise")` 사용 — 고정 alpha를 쓰는 GLM family와 **다르다**.
- M1/M2/M3은 **동일한 적격 완전사례 표본**을 사용한다.
- **인구 offset 없음**, 14일 고정 관측창에 대한 기간 offset도 없음 → 추정 대상은 절대 보도량.
- 인구 밀도, 소득 그룹, 합성 노출 변수는 모형에 들어가지 않는다.
- 도시화 효과는 `exp(0.1 * beta_urban)` (10%p당)로 보고. 계수, SE, p값, 계수 CI, IRR, IRR CI 모두 보고.
- 침수 IRR은 `log(1 + km²)` 1단위 증가당.

### 12.2 추정 가능성 게이트 (사전 고정, 결과 방향에 무관)

| 조건 | 기준 |
|---|---|
| 최소 표본 | **N ≥ 20** |
| 모수당 관측치 | **≥ 5** |
| 설계 행렬 | full rank |
| 수렴 | 안정적 |
| 위 조건 불충족 시 | **typed `not estimable` 상태 반환** |

**클러스터 추론 게이트**: state 클러스터 공분산 + 유한표본 보정 + `t(G−1)` 추론은 **G ≥ 20 이고 N > 2G** 일 때만 추가. 그 외에는 독립성 가정을 명시적 한계로 서술.

**2차 source-flood 고정효과**: 다중 district 홍수 **≥10개**와 충분한 행 수 필요. 그 외 `insufficient sample` 보고.

**노출 인구 강건성**: **미구현**. 검증된 flood-mask × 격자 인구 입력 계약이 없기 때문. **면적 × 평균 밀도는 결코 노출 인구 대리변수로 쓰지 않는다.**

### 12.3 결정 규칙 (사전 고정)

양(+) 계수 AND 양측 p < 0.05 → 해당 방향 가설 지지. 반대·불확실 결과는 명시적으로 서술. 사전 지정된 클러스터 규칙이 충족되면 state 클러스터 추론을 선호.

**이 게이트, 적합 적격성, 보고 문구는 가설을 본 뒤가 아니라 코드에 사전 고정되어 있다.**

### 12.4 적격성(`analysis_eligible`) 요건

식별된 district AND 매칭된 district AOI AND 유한·비음수이며 AOI 면적 이하인 관측 침수 면적 AND 완전한 기사 관측과 비음수 정수 계수 AND 매칭된 공식 2011 커버리엇(유효 총계) AND 유효한 발생일.

모든 실패는 `exclusion_reason`을 가진다. **이 조건들에 대해 대체(imputation)나 0 채우기를 사용하지 않는다.**

### 12.5 현재 제외 사유별 행 수

| 사유 | 행 수 |
|---|---|
| district_aoi_unmatched | 1,630 |
| satellite_missing_or_invalid | 1,630 |
| aoi_area_invalid | 1,630 |
| article_collection_incomplete | 1,630 |
| article_count_missing_or_invalid | 1,630 |
| census_unmatched | 142 |
| census_invalid | 128 |
| census_population_inconsistent | 128 |
| ambiguous_duplicate_census_district_code | 14 |

### 12.6 그림

- **Figure 1**: `log1p(area)` vs `log1p(count)` 산점도 → `outputs/flood_area_vs_articles.png` (300 dpi)
- **Figure 2**: 침수 면적을 중앙값에 고정하고 관측된 도시화 범위에서 Model 2 기대 계수 + **기대 평균의 95% 신뢰구간**. → `outputs/urbanization_adjusted_coverage.png`
  - ⚠️ **개별 관측치 예측 구간이 아니다.** 논문에서 혼동하지 말 것.
- 3분위는 **선택 QC 전용**이며 고유 district 기준, 절단점을 보고한다.

---

## 13. 부가 모듈: 상대 보도량 스코어링 (H1/H2와 별개)

`src/score_coverage.py` — **정답 라벨을 학습하는 분류기가 아니다.**

### 13.1 모형

```
article_count ~ log_flood_area + log_population + year_c
log_flood_area = log1p(flood_area_km2)
log_population = log(total_population / 1_000_000)
year_c        = start_date.year - 2020
Var(Y|X)      = mu + alpha * mu^2
```

인구는 **추정 계수**를 가지며 offset이 아니다. Census 2011 총인구는 피해·노출 인구가 아니다. 도시화율, income_group, 고정효과, MSS/PSS, 기사 수 파생 변수는 기대량 모형에 넣지 않는다.

### 13.2 OOF 설계

적격 행을 `(source_record_id, event_district_id)` 문자열 순으로 정렬 후 **`GroupKFold(n_splits=5)`**. 같은 source의 모든 state/district가 같은 fold에 들어간다. train/test source 교집합 없음, 각 적격 행이 정확히 한 번 test 배정됨을 실행 중 검사.

| 운영 설정 | 기본값 |
|---|---|
| `--min-rows` | 적격 50행 |
| `--min-sources` | 적격 source 10개 |
| `--min-train-rows` | train 30행 |
| `--min-train-sources` | train source 5개 |
| `--rows-per-parameter` | 5 |
| `--tail-threshold` | 0.05 |
| n_splits | 5 (고정) |

**주 NB2 실패를 전체 표본 적합값이나 Poisson으로 대체하지 않는다.** Poisson은 진단 전용.

### 13.3 후보 판정

```
p_lower = nbinom.cdf(y, n, p)        # P(Y <= y)
p_upper = nbinom.sf(y - 1, n, p)     # P(Y >= y), 관측값 포함
predictive_low_90, high_90 = nbinom.ppf([.05, .95], n, p)
```

| 조건 | 라벨 |
|---|---|
| `p_lower ≤ 0.05 AND y < mu` | `relative_under_candidate` |
| `p_upper ≤ 0.05 AND y > mu` | `relative_over_candidate` |
| 나머지 성공 OOF | `within_expected_range` |
| 제외/자료 부족/적합 실패 | `not_scored` |

**해석 한계**: 이는 측정된 GDELT 보도량에 대한 **탐색적 경보**이며, 마땅한 보도량이나 인과적/의도적 외면이 아니다. 중앙 90% 계수 예측 구간은 **모수 불확실성을 제외한 plug-in 근사**다.

---

## 14. 파이프라인 실행 구조

### 14.1 지원 러너

`scripts/run_pipeline.sh` — `.env`를 로드하고 NumPy/pandas가 있는 Python 인터프리터를 선택.

**기본값**:
```
SETUP_DEPS=0  SKIP_GEE=1  SKIP_ARTICLES=1  SKIP_COVARIATES=0  SKIP_ANALYSIS=0
SATELLITE_TRACK=A  SATELLITE_ROUTING=s1_interim  REUSE_STATE_ARTICLES=0
```

### 14.2 11단계 순서

1. `build_emdat_events.py` — EM-DAT 상위 레지스트리 + 이벤트×district 레지스트리
2. `build_district_covariates.py` — Census 2011 총/도시/농촌 인구, 도시 비율
3. `event_aoi_area.py` + `satellite.py --track ...` — AOI 조회 및 위성 측정 (SKIP_GEE=1이면 생략)
4. `run_sits_inference.py` — track이 B 또는 both일 때
5. `compare_tracks.py` — `SATELLITE_ROUTING=sits_primary`일 때
6. `merge_results.py` — 위성 후보 라우팅
7. `build_flood_area_table.py` — 최종 district 침수 면적 테이블
8. 기사 단계 — 로컬 재사용(`REUSE_STATE_ARTICLES=1`) 또는 district BigQuery 수집 + 본문 다운로드
9. `district_articles.py --counts-only` — 로컬 재사용 단계를 쓰지 않은 경우
10. `join_district_flood_articles.py` — 정체성 검사, 조인, 제외, QC
11. `analyze_coverage_disparity.py` + `score_coverage.py` — 분석 (SKIP_ANALYSIS=1이면 생략)

### 14.3 오프라인 명령

```bash
bash scripts/run_pipeline.sh --dry-run          # 외부 호출 없이 명령 계획 + 스키마 감사
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests
```

### 14.4 핵심 원칙

**어떤 단계도 관측치를 만들어내지 않는다.** 쿼리 성공 + 후보 0건 = 관측된 0. 미실행/실패/불완전 = 결측. 필수 파일 누락은 실패하며, **skip은 관측치를 제조하지 않는다.**

### 14.5 외부 서비스 요구사항

| 환경변수 | 용도 |
|---|---|
| `GEE_PROJECT_ID` | Earth Engine |
| `GDELT_BILLING_PROJECT` | BigQuery 과금 |
| `OPENAI_API_KEY` | LLM 기사 QA |
| `EMDAT_API_KEY` | 선택적 EM-DAT API 수집기 |

---

## 15. 주요 소스 모듈

| 모듈 | 역할 |
|---|---|
| `build_emdat_events.py` | EM-DAT 상위 레지스트리, 이벤트×district 레지스트리 |
| `district_recovery.py` | 공급된 복구 매핑 병합, `event_district_id` 중복 제거 |
| `build_district_covariates.py` | Census 2011 인구, 도시 비율 |
| `event_aoi_area.py` | district AOI 조회, 면적 메타데이터 |
| `boundary_recovery.py` | 원본 파일 체크섬 검증, 메타데이터/Track A/Track B에 동일 폴리곤 해결 |
| `satellite.py` | Track A S1/S2 측정, Track B SITS 패치 준비 |
| `run_sits_inference.py` | 로컬 SITS 체크포인트 추론 |
| `sits_feasibility.py` | SITS 가용성/타당성 점검 |
| `merge_results.py` | 위성 후보 라우팅 |
| `compare_tracks.py` | 변환기 결정 |
| `build_flood_area_table.py` | 최종 district 침수 면적 테이블 |
| `gdelt_backend.py` | BigQuery SQL, GDELT 쿼리 헬퍼 |
| `district_articles.py` | district 기사 메타데이터 쿼리, 본문 인식 heuristic 계수, manifest |
| `district_heuristics.py` | 다국어 홍수 키워드 분류기 |
| `reuse_state_articles.py` | 오프라인 state→district 후보 재사용 (레거시 provisional export) |
| `article_qa.py` | 재개 가능한 QA 워크플로 (prepare/supplement/submit/collect/counts) |
| `download_articles.py`, `article_fetcher.py`, `article_extractor.py` | 본문 취득/추출/저장 |
| `repair_article_database.py` | 기사 DB 복구 |
| `join_district_flood_articles.py` | 정체성 검사, 조인, 제외, QC |
| `analyze_coverage_disparity.py` | 기술통계, Spearman, NB2, 그림, 보고서 |
| `score_coverage.py` | source-group OOF NB2 기사 수 스코어링 |
| `pipeline_preflight.py` | 산출물/명세 검사 |
| `cvnd_layout.py` | 논리적 데이터/출력 경로 |
| `flood_spec.py` | **동결된 위성 측정 명세 + 해시** |
| `district_keys.py` | 보수적 지리 정규화 및 키 생성 |

---

## 16. 주요 산출 경로

```
data/intermediate/event_districts.csv
data/intermediate/district_covariates.csv
data/intermediate/district_aoi.csv
data/intermediate/aoi_matching_final.csv          # 최종 행별 대응표
data/intermediate/aoi_remaining_unresolved.csv    # 미해결 사유
data/intermediate/event_aoi_overlap_audit.csv     # 중첩 감사
data/intermediate/reference_recovery_verification.json
data/intermediate/state_article_reuse_audit.json
data/intermediate/registry_cache_migration.json
data/cache/district/flood_extent.csv
data/cache/district/sits_patches/  ·  sits_scores/
data/intermediate/district_flood_area.csv
data/intermediate/district_gdelt.articles.jsonl.gz  ·  district_gdelt.manifest.json
data/results/district_article_counts.heuristic.csv
data/results/district_flood_articles.csv          # 이벤트-district당 1행(제외 행 포함)
data/results/district_analysis_exclusions.csv  ·  district_qc.json  ·  district_selection_bias.csv
data/results/coverage_model_results.csv  ·  coverage_predictions.csv
data/results/coverage_scores.csv  ·  coverage_oof_diagnostics.csv
data/results/sits_feasibility.csv  ·  sits_feasibility_summary.json
data/results/routing_comparison.json
outputs/paper_results.md  ·  coverage_summary.json
outputs/flood_area_vs_articles.png  ·  urbanization_adjusted_coverage.png
outputs/coverage_scoring_report.md  ·  coverage_scoring_summary.json
```

---

## 17. 논문 작성 AI에게 주는 지시사항

### 17.1 반드시 지킬 것

1. **H1/H2의 수치 결과를 만들어내지 말 것.** 현재 N=0이며 모든 모형이 `not estimable`이다. 계수·p값·IRR·Spearman rho는 존재하지 않는다.
2. **§5(경계 복구), §9(Sentinel-2 프로브), §10.4(state 코퍼스 재사용 실패), §11(현재 상태)의 수치는 실제 완료된 결과**이므로 자신 있게 사용할 것.
3. 모든 결론 문장은 **"관측된 침수 규모가 비슷한 조건에서"** 라는 한정을 유지할 것.
4. 의도·인과·차별·"마땅한 보도량"을 함의하는 표현 금지.
5. district 면적을 합산하지 말 것 (§5.4).
6. 1,630 vs 1,623 행 수 불일치를 인지하고 일관되게 1,630으로 쓰되, 최종 확인 필요를 명시할 것.
7. **문서(`PROJECT_CONTEXT.md`, `README.md`)와 실제 파일이 충돌하면 항상 실제 파일이 기준이다.** 확인된 충돌: alias 33 vs 40행, state 재사용 감사 수치(구 126,885/750 vs 신 127,252/762), `spec_version`(코드 vs 캐시), `district_gdelt.manifest.json` 존재 여부.

### 17.2 권장 논문 프레이밍

현재 상태에서 쓸 수 있는 논문은 **결과 논문이 아니라 측정 인프라 + 타당성(feasibility) 논문**이다. 핵심 논지:

> 이 파이프라인이 산출한 가장 중요한 결과는 계수가 아니라, **잘못된 측정을 거부한 기록**이다.
> - state 코퍼스를 재사용했다면 → district 타당성이 전혀 없는 127,252행이 나왔을 것
> - 재생성 이전 위성 캐시를 재사용했다면 → 더는 존재하지 않는 레지스트리에 대해 측정된 1,549개 면적이 나왔을 것
> - stale spec 행을 재사용했다면 → 현재 명세와 다른 정의로 측정된 면적이 섞였을 것
> - 추정 가능성 게이트가 없었다면 → 살아남은 무엇에든 NB2를 적합했을 것
>
> 넷 다 방어 가능한 엔지니어링 지름길이고, 넷 다 **출판 가능해 보이는 계수**를 냈을 것이다. N=0을 보고하는 것이 이 넷을 모두 거부한 대가이며, **계수가 아니라 그 거부가 이전 가능한(transferable) 결과다.**

### 17.3 반드시 포함할 limitation

- Census 2011은 대부분의 이벤트보다 앞서며, 도시화는 사전 고정 공변량이다
- 경계 참조는 혼합 기준연도이며 사건 당일 행정 지리에 대해 검증되지 않았다
- GAUL 2015 / geoBoundaries 2021 / Census 경계가 서로 다를 수 있다
- 244행의 발생일이 월 단위로 대체되어 14일 창에 타이밍 불확실성이 있다
- GDELT 색인된 district 명시 보도는 전체 보도의 부분집합이며, 언어와 색인 동작 자체가 도시화와 상관될 수 있다 — **설계가 기록하되 해결하지는 못하는 위협**
- 침수 면적은 모든 재난 피해, 매체 가용성, 인구 규모, 미디어 접근성을 통제하지 않는다
- 같은 source flood 내 district 행과 반복 district는 종속적일 수 있으며, state 클러스터링은 부분적 보정일 뿐이다
- 인구 규모는 의도적으로 주 명세에서 통제하지 않았으므로, 연관에 대한 잠재적 설명으로 남는다
- SAR는 식생 아래/건물 지역 물을 놓치고, NDWI는 일부 건물 표면을 물로 표시한다

### 17.4 인용 가능한 외부 레퍼런스

- Eisensee & Strömberg (2007), *QJE* 122(2):693–728 — 뉴스와 재난 구호
- Leetaru & Schrodt (2013) — GDELT
- CRED/UCLouvain — EM-DAT
- Torres et al. (2012), *RSE* 120:9–24 — Sentinel-1
- Drusch et al. (2012), *RSE* 120:25–36 — Sentinel-2
- Otsu (1979), *IEEE Trans. SMC* 9(1):62–66
- McFeeters (1996), *IJRS* 17(7):1425–1432 — NDWI
- Pekel et al. (2016), *Nature* 540:418–422 — JRC Global Surface Water
- Gorelick et al. (2017), *RSE* 202:18–27 — Google Earth Engine
- Runfola et al. (2020), *PLoS ONE* 15(4):e0231866 — geoBoundaries
- Hilbe (2011), *Negative Binomial Regression*, 2nd ed., Cambridge UP
- Cameron & Miller (2015), *J. Human Resources* 50(2):317–372 — 클러스터 강건 추론
- Tellman et al. (2021), *Nature* 596:80–86 — 위성 홍수 노출
- Census of India 2011, Office of the Registrar General

### 17.5 라이선스 / 귀속

- geoBoundaries ADM2: ODbL 1.0 (geoBoundaries / William & Mary geoLab; Pathways Data Pvt. Ltd.; lgdirectory.gov.in)
- ADM1 검증 레이어: DataMeet India / Election Commission of India, CC BY 2.5 India
- OSM 보조 기하: © OpenStreetMap contributors, ODbL 1.0
- Nominatim 조회는 소규모·단일 스레드·캐시 기반으로 OSMF 정책을 준수한 **일회성 연구 헬퍼**였으며, 공개 지오코딩 기능이나 주기적 작업이 아니다

---

## 18. 용어집

| 용어 | 뜻 |
|---|---|
| **district** | 인도 행정구역 2단계 (admin-2). 이 연구의 주 관측 단위 |
| **AOI** | Area of Interest — district의 측정 폴리곤 |
| **Track A** | Sentinel-1/2 직접 측정 경로 |
| **Track B** | SITS(위성 영상 시계열) HDF5 패치 준비 + 로컬 모델 추론 경로 |
| **SITS** | Satellite Image Time Series |
| **MeasurementSpec** | 동결된 위성 측정 명세. 해시(`spec_version`)로 식별 |
| **spec_version** | 명세 해시. **현재 코드 = `fs1-3016a20fd3ad`**, 작업 복사본 캐시 = `fs1-8d55f7c25c28` (stale) |
| **registry fingerprint** | 이벤트 레지스트리의 SHA-256. 파생 산출물 무효화에 사용 |
| **NB2** | Negative Binomial 2 — `Var = mu + alpha*mu^2` |
| **IRR** | Incidence Rate Ratio |
| **OOF** | Out-of-fold (교차검증 홀드아웃 예측) |
| **GKG** | GDELT Global Knowledge Graph |
| **LSIB** | Large Scale International Boundaries (미 국무부 경계 데이터) |
| **JRC** | EU Joint Research Centre (Global Surface Water) |
| **GAUL** | FAO Global Administrative Unit Layers |
| **LGD** | Local Government Directory (인도 행정구역 코드 체계) |
| **TOST** | Two One-Sided Tests (동등성 검정) |
| **LOSO-CV** | Leave-One-State-Out 교차검증 |
| **HC3 / CR1-F** | 이분산 강건 / 클러스터 강건 공분산 추정량 |

---

## 19. 리포지토리 정보

- 저장소: `https://github.com/rokpolar/CVND.git` (브랜치 `main`)
- 로컬 작업 디렉터리: `C:\CVNDrefact`
- 최근 커밋: `3ad4e97 Add targeted GDELT and LLM QA pipeline`
- 주요 커밋 흐름: district 레지스트리 및 커버리지 분석 추가 → district AOI 라우팅 → state 진입점 제거 → 로컬 SITS 추론 통합 → OOF 스코어링 → 단일 격자 위성 측정 리팩터 + SITS-primary 라우팅 → SITS 타당성 프로브 → 오프라인 state 기사 재사용 → district recovery → 표적 GDELT + LLM QA 파이프라인
