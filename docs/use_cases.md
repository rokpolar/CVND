# CVND Use Cases

## UC-01 event×district 레지스트리

`src/build_emdat_events.py`가 `data/raw/EM-DAT-BASE.xlsx`를 읽어 `data/intermediate/event_districts.csv` 하나만 기록한다. structured administrative evidence를 우선하며 모호한 행은 audit용 결측으로 보존한다.

## UC-02 위성 침수 관측

`SKIP_GEE=0`이면 AOI를 확인한 뒤 모든 키에 S1을 실행하고 S1 면적 결측 키에만 S2를 실행한다. 관측 0은 성공이며 AOI 실패는 fallback하지 않는다. `src/merge_results.py --routing s1_then_s2`가 S1 → S2 → missing 순서로 단일 면적을 선택한다. 전체 파이프라인은 Track B/SITS를 사용하지 않는다.

## UC-03 기사 heuristic → LLM-QA

기존 30일/14일 LLM-QA count를 lower-bound 자료로 동결한다. 기본 `ARTICLE_PIPELINE_MODE=frozen`은 provenance가 `llm_complete`일 때만 재사용하고 수집·본문·heuristic·LLM 단계를 실행하지 않는다.

## UC-04 join과 분석

`src/join_district_flood_articles.py`가 flood area, article count, Census covariate를 event×district 키로 결합한다. 분석과 OOF scoring은 먼저 `data/results/primary_30d/`와 `outputs/primary_30d/`, 다음으로 `sensitivity_14d/`에 기록한다. `window_days`가 없거나 섞인 입력은 분석하지 않는다.

## UC-05 전체 실행

```bash
bash scripts/run_pipeline.sh --dry-run
SKIP_GEE=0 ARTICLE_PIPELINE_MODE=frozen bash scripts/run_pipeline.sh
```

실제 GEE·BigQuery·OpenAI 작업은 인증된 명시적 실행에서만 수행한다. 기본 dry-run은 외부 호출이나 산출물 교체 없이 계약을 검사한다.
