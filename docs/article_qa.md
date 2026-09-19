# Article QA operations

뉴스 결과의 primary window는 `[onset, onset+30 days)`이고 sensitivity는 그 안의 14일이다. 위성 post window는 별도로 14일을 유지한다. 후보는 30일까지 한 번 수집하고 heuristic을 통과한 후보만 LLM-QA에 전달한다.

## 자동 재개 계약

기본값은 `ARTICLE_PIPELINE_MODE=auto`다. `src/article_qa.py state`는 파일 존재가 아니라 다음 provenance를 검사한다.

- 현재 event×district registry와 source corpus hash
- prompt와 model
- request와 result hash, 본문 SQLite/보조 WAL hash
- district collection manifest와 두 count CSV 각각의 hash, count manifest와 QA manifest의 연결
- `counts_30d.csv`, `counts_14d.csv`, `counts.manifest.json`의 키·window·상태 계약

auto 실행은 state 판정 전에 `adopt-existing`을 호출한다. 이미 비용을 지불한 schema-1 QA는 기존 request에 속한 응답의 구조와 근거, 두 count의 키·상태를 오프라인 검증하고 감사 메타데이터와 현재 hash로 봉인한다. 이후 registry에 행만 추가되면 기존 값은 유지하고 새 행을 `incomplete`로 추가하지만, source·본문·prompt/model·응답·count 변경은 재사용하지 않는다. `ARTICLE_ADOPT_EXISTING_QA=0`으로 이 승격을 비활성화할 수 있다.

반환 상태는 다음과 같다.

- `llm_complete`: heuristic과 LLM-QA 모두 생략
- `heuristic_complete`: heuristic 생략, LLM-QA부터 재개
- `none`: stale/누락 상태이므로 GDELT·본문·heuristic부터 실행

`complete`와 `partial`은 관측값으로 join한다. `partial`은 확정 relevant 수를 lower bound로 보존한다. `incomplete`는 article count가 결측인 정상 데이터 상태다. 해결되지 않은 후보를 irrelevant 또는 0으로 대체하지 않는다.

수집 완전성은 구역별 district GDELT manifest로 판정한다. 한 구역의 미수집이 다른 구역의 관측값을 지우지 않는다. 성공적으로 완료된 구역 쿼리에 후보가 없으면 0이며, 쿼리 실패·누락이면 결측이다. 기본 source와 DB는 district corpus를 사용한다. 기존 state corpus를 사용하려면 `--source`, `--database`를 명시한다.

## 수동 실행

```bash
venv/bin/python src/article_qa.py prepare
venv/bin/python src/article_qa.py run-batches --execute
venv/bin/python src/article_qa.py counts
venv/bin/python src/article_qa.py adopt-existing
venv/bin/python src/article_qa.py state
```

`OPENAI_API_KEY`가 필요한 실제 Batch 제출은 `--execute`에서만 일어난다. 중단 후 같은 명령을 실행하면 ledger에서 재개한다. 하나의 structured response에는 모든 candidate ID가 정확히 한 번 있어야 하며, relevant evidence는 제공한 본문의 정확한 excerpt여야 한다.

선택적 targeted supplement:

```bash
venv/bin/python src/article_qa.py supplement --maximum-tib 0.25
venv/bin/python src/article_qa.py supplement --execute --maximum-tib 0.25
venv/bin/python src/article_qa.py prepare
venv/bin/python src/article_qa.py download-new
venv/bin/python src/article_qa.py prepare
```

첫 supplement 명령은 BigQuery dry-run 추정이다. 실행도 scan estimate와 cap을 먼저 확인한다. `manifest.json`, supplement/batch ledger, requests/results, provider raw output은 최종 count와 함께 보존해야 한다.

## 파이프라인

```bash
ARTICLE_PIPELINE_MODE=auto RUN_ARTICLE_SUPPLEMENT=0 bash scripts/run_pipeline.sh
bash scripts/run_pipeline.sh --dry-run
```

최종 count는 `data/intermediate/article_qa/counts_30d.csv`와 `counts_14d.csv`다. 각각 `data/results/primary_30d/`와 `data/results/sensitivity_14d/`의 join·분석·OOF scoring으로 이어진다.
