> **Historical state pipeline reference.** The current primary workflow is event × district. See [README](../README.md) for the runnable sequence and [district methodology](district_methodology.md) for observation rules.

# CVND Use Cases

CVND 파이프라인(홍수 침수 면적과 헤리스틱 기사 수 집계)의 유스케이스 정리.
상세 알고리즘은 [README](../README.md)와 각 `src/*.py` 모듈 문서를 참고.

## 액터

| 액터 | 종류 | 역할 |
| --- | --- | --- |
| 연구자 (Researcher) | 주 액터 | 파이프라인 실행, 파라미터(SKIP 플래그) 설정, 결과 해석 |
| Google Earth Engine | 외부 시스템 | Sentinel-1/2 영상 및 침수 탐지 연산 |
| 로컬 GPU/CPU | 로컬 시스템 | SITS-VAE 추론으로 패치 점수 생성 |
| GDELT BigQuery | 외부 시스템 | 다국어 기사 URL·메타데이터 제공(본문 미포함) |
| EM-DAT | 외부 데이터 | 재난 목록 |

## Use Case Diagram

```mermaid
flowchart LR
  R(["연구자"])
  GEE(["Google Earth Engine"])
  LOCAL(["Local SITS"])
  BQ(["GDELT BigQuery"])
  EMDAT(["EM-DAT"])

  subgraph SYS["CVND Pipeline"]
    UC1(["UC-01 이벤트 데이터 구축"])
    UC2(["UC-02 위성 침수 탐지"])
    UC3(["UC-03 침수 면적 통합"])
    UC4(["UC-04 이벤트 침수 면적 산출"])
    UC5(["UC-05 GDELT 수집·본문 다운로드"])
    UC6(["UC-06 헤리스틱 기사 분류"])
    UC7(["UC-07 면적·기사수 조인"])
    UC8(["UC-08 파이프라인 일괄 실행"])
  end

  R --- UC8
  R --- UC1
  R --- UC5
  R --- UC6

  UC8 -. include .-> UC3
  UC8 -. include .-> UC4
  UC8 -. include .-> UC7
  UC8 -. extend .-> UC2

  UC1 --- EMDAT
  UC2 --- GEE
  UC2 --- LOCAL
  UC3 --- LOCAL
  UC5 --- BQ
  UC6 --- BQ
```

## Use Case Specification

### UC-01 이벤트 데이터 구축

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자, EM-DAT |
| 목적 | EM-DAT 홍수 레코드를 주·지구 단위 분석 이벤트로 변환 |
| 사전조건 | `data/raw/EM-DAT-BASE.xlsx` |
| 주 흐름 | 홍수·연도 필터 → 주 단위 분해 → bbox 할당 → 이벤트 ID 부여 |
| 결과 | `data/raw/events.csv` |
| 구현 | `src/build_emdat_events.py` |

### UC-02 위성 침수 탐지 (선택, `SKIP_GEE=0`)

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자, Google Earth Engine, 로컬 GPU/CPU |
| 목적 | 이벤트별 침수 범위 산출, 로컬 H5 보존 및 SITS 점수 생성 |
| 사전조건 | GEE 인증, `.env`의 `GEE_PROJECT_ID` |
| 주 흐름 | Track A(S1/S2 Otsu) → `flood_extent.csv`; Track B → 로컬 H5 영구 저장 → 로컬 추론 → `sits_scores/` |
| 예외 | 구름 과다 시 광학 대신 레이더(S1) 경로 사용 |
| 구현 | `src/satellite.py`, `src/run_sits_inference.py` |

### UC-03 침수 면적 통합

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자 |
| 목적 | SITS·NDWI·S1 결과를 이벤트별 단일 침수 면적으로 결합 |
| 사전조건 | `flood_extent.csv` + `sits_scores/` |
| 주 흐름 | 품질 게이트(Youden J) → 융합/전구역 NDWI 선택 → 구름 라우팅(≥60%면 S1) |
| 결과 | `data/intermediate/flood_combined.csv` |
| 구현 | `src/merge_results.py` |

### UC-04 이벤트 침수 면적 산출

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자 |
| 목적 | 통합 침수 면적을 이벤트별 표로 정리 |
| 사전조건 | `flood_combined.csv`, `events.csv`, `state_area.csv` |
| 주 흐름 | 주 이름 정규화 → `adjusted_flood_area_km2` 등 면적 컬럼 산출 |
| 결과 | `data/intermediate/severity_raw.csv` |
| 구현 | `src/compute_population.py` |

### UC-05 GDELT 수집·본문 다운로드 (선택)

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자, GDELT BigQuery |
| 목적 | 이벤트 창에 맞는 GDELT URL 메타데이터와 원문 본문 확보 |
| 사전조건 | 공식 `events.csv`, Google ADC(실행 시) |
| 주 흐름 | BigQuery SQL 생성/실행 → `gdelt_bq.articles.jsonl.gz` → `download_articles.py` |
| 결과 | `data/raw/gdelt_bq.json`, `data/raw/gdelt_bq.articles.sqlite` |
| 구현 | `src/collect_gdelt.py`, `src/download_articles.py` |

### UC-06 헤리스틱 기사 분류

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자 |
| 목적 | 다운로드 본문에서 홍수 키워드 매칭으로 이벤트별 기사 수 산출 |
| 사전조건 | `gdelt_bq.articles.sqlite`, `events.csv` |
| 주 흐름 | 후보 확장 → 키워드 필터 → `export` (기본 heuristic) |
| 결과 | `data/results/event_article_counts.heuristic.csv` |
| 구현 | `src/classify_event_articles.py` (LLM 경로는 선택적 QA용으로 유지) |

### UC-07 면적·기사수 조인

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자 |
| 목적 | 이벤트·주 단위로 침수 면적과 헤리스틱 기사 수를 한 테이블로 결합 |
| 사전조건 | `severity_raw.csv`, `event_article_counts.heuristic.csv` |
| 주 흐름 | event_id 조인 → 주별 합계 산출 |
| 결과 | `data/results/event_flood_articles.csv`, `data/results/state_flood_articles.csv` |
| 구현 | `src/join_flood_articles.py` |

### UC-08 파이프라인 일괄 실행

| 항목 | 내용 |
| --- | --- |
| 액터 | 연구자 |
| 목적 | 캐시된 산출물 기반으로 침수 면적·조인까지 한 번에 재현 |
| 사전조건 | `venv/`, 캐시 데이터(`flood_combined` 또는 `flood_extent`), heuristic counts |
| 주 흐름 | UC-03 → UC-04 → UC-07 순차 실행 (선택: UC-02, UC-05–06) |
| 확장 | `SKIP_GEE=0`이면 UC-02 포함, `SKIP_ARTICLES=0`이면 GDELT 재수집 |
| 구현 | `scripts/run_pipeline.sh` |
