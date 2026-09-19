# CVND: flood extent and district news visibility

CVND는 EM-DAT 홍수의 event×district 단위에서 위성 관측 침수 면적과 뉴스 가시성의 관계를 분석한다. 기본 분석은 **발생일부터 30일간의 뉴스 반응(primary)**이며, 같은 후보 집합의 **14일 뉴스 반응(sensitivity)**을 함께 산출한다. 위성 노출은 별도의 사전 지정된 **발생 후 14일 관측창**이다. 따라서 핵심 분석 정의는 “14일 침수 강도에 대한 30일 뉴스 반응”이다.

## 관측 계약

- 레지스트리: `data/intermediate/event_districts.csv`만 권위 있는 event×district 레지스트리로 사용한다. 모호한 지역은 결측/audit 행으로 보존하고 state 값을 district로 확장하지 않는다.
- 위성: 모든 유효 AOI에서 Sentinel-1(S1)을 먼저 실행한다. S1 면적이 결측인 키에만 Sentinel-2 NDWI(S2)를 실행한다. 유한한 `0 km²`는 성공한 관측이며 fallback 대상이 아니다. AOI 실패도 S2로 재시도하지 않는다. 기본값은 `SATELLITE_TRACK=A`, `SATELLITE_ROUTING=s1_then_s2`다. Track B/SITS는 명시적으로 선택할 때만 실행한다.
- 기사: 30일까지 GDELT 후보를 수집한 뒤 multilingual flood heuristic을 통과한 후보만 LLM-QA로 보낸다. 같은 판정으로 `counts_30d.csv`와 `counts_14d.csv`를 만든다.
- 기사 상태: `complete`와 `partial`은 분석 가능한 관측이다. `partial`은 `article_count_is_lower_bound=True`를 유지한다. `incomplete`는 정상 결측이며 파이프라인 손상으로 간주하지 않는다.
- 모델: NB2 Model 2는 `article_count ~ log1p(flood_area_km2) + urban_population_share`이다. Model 1은 urban share를 제외하고 Model 3은 year fixed effects를 추가한다.

위성 측정식은 `src/flood_spec.py`의 `MeasurementSpec`과 `spec_version`으로 고정한다. post `[onset, onset+14d)`, pre `[onset-30d, onset)`, JRC permanent-water·slope·India mask, 10 m 면적 합산을 모든 sensor 경로에 적용한다. Track B/SITS는 구역마다 가능 여부를 판정해, 측정할 수 있는 구역에만 쓰인다.

## 실행

```bash
# 외부 호출 없이 명령과 캐시 계약 검사
bash scripts/run_pipeline.sh --dry-run

# 전체 검증
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests scripts
bash -n scripts/run_pipeline.sh

# 인증된 실제 실행(기본 SKIP_GEE=0): Track A(S1 -> S1 결측에만 S2) -> 기사 auto resume
SETUP_DEPS=1 ARTICLE_PIPELINE_MODE=auto bash scripts/run_pipeline.sh

# 위성 캐시 재사용, 기사 상태를 manifest/hash로 자동 판정
SKIP_GEE=1 ARTICLE_PIPELINE_MODE=auto bash scripts/run_pipeline.sh
```

`ARTICLE_PIPELINE_MODE=auto`의 상태 전이는 다음과 같다.

1. 두 window count와 manifest가 registry/source/request/result/prompt/model hash에 맞으면 heuristic과 LLM-QA를 모두 생략한다.
2. 검증된 heuristic 산출물만 있으면 heuristic을 생략하고 LLM-QA부터 재개한다.
3. 산출물이 없거나 stale이면 GDELT 수집·본문·heuristic부터 수행한 뒤 LLM-QA를 실행한다.

`force`는 기사 파이프라인을 처음부터 재실행하고 `skip`은 기사 join·분석을 수행하지 않는다. `RUN_ARTICLE_SUPPLEMENT=1`만 targeted BigQuery supplement를 허용한다. 외부 GEE·BigQuery·OpenAI 호출은 실제 실행 옵션에서만 발생한다. `SETUP_DEPS=1`은 재현 환경인 `requirements-lock.txt`를 설치한다.

## 위성 트랙 분리 저장과 재병합

Track A, Track B, 병합은 각자 자기 테이블에만 쓰고, 어떤 단계도 상류 산출물을 다시 쓰지 않는다.

| 단계 | 쓰는 파일 | 읽는 것 |
|---|---|---|
| Track A (`satellite.py --track A`) | `data/cache/district/flood_extent.csv` | Earth Engine |
| Track B 패치 (`satellite.py --track B`) | `data/cache/district/sits_patches/*.h5`, `sits_patches_index.csv` | Earth Engine / CDSE |
| Track B 측정 (`run_sits_inference.py`) | `data/results/district_sits_measurements.csv` (구역당 1행, upsert), `data/cache/district/sits_scores/*.npz` (타일 상세) | H5, 체크포인트 |
| 병합 (`merge_results.py`) | `--output`만 (기본 `data/intermediate/district_flood_combined.csv`) | 위 테이블, registry, AOI, converter |
| 면적표 (`build_flood_area_table.py`) | `--output`만 | 병합 출력 |

병합은 Earth Engine·모델·NPZ 없이 테이블만 읽고 registry의 모든 행을 쓴다. 실행되지 않은 단계는 행 삭제가 아니라 `track_a_status`(`measured`/`error`/`not_run`), `track_b_patch_status`(`ok`/`incomplete`/`error`/`not_run`), `sits_measure_status`(`measured`/`not_run`)로 기록한다. 측정 행은 현재 디스크의 H5와 `patches_sha256`이 다르거나, RGB 전용 H5인데 `tile_selection_rule`이 현행 규칙과 다르면 쓰지 않는다. H5가 삭제된 경우에는 테이블이 측정 기록으로 남는다. 같은 측정으로 라우팅을 비교하려면 출력 파일을 나눠 병합만 다시 돌린다.

```bash
venv/bin/python src/merge_results.py --routing sits_then_track_a --output data/intermediate/district_flood_combined.sits_then_track_a.csv
venv/bin/python src/merge_results.py --routing s1_then_s2   --output data/intermediate/district_flood_combined.s1_then_s2.csv
venv/bin/python src/merge_results.py --routing sits_primary --output data/intermediate/district_flood_combined.sits.csv
```

`--recompute-from-npz`는 측정 테이블 대신 NPZ에서 Track B 값을 다시 계산한다(측정 테이블은 쓰지 않는다). `build_flood_area_table.py`는 병합 입력이 0행이면 실패하고, 기존 출력의 측정값을 NA/NONE으로 강등하는 덮어쓰기는 `--allow-demotion` 없이는 거부한다.

`SATELLITE_ROUTING=sits_primary`의 모순 조합은 실행 전에 막는다: `SKIP_GEE=0`인데 `SATELLITE_TRACK=A`인 경우, `SKIP_GEE=1`인데 `district_sits_measurements.csv`가 없거나 비어 있는 경우. 시작 배너의 `S2/SITS:` 한 줄이 이번 실행의 S2 사용 방식을 표시한다.

**Track B 사전 판정 (다운로드 없음).** Track B는 다운로드 전에 이미 사후·사전 영상 유무(B1, B2)와 맑은 기준월(B3)을 검사하지만, 남는 타일의 사용 가능 픽셀이 측정 대상 면적의 40%(`sits_usable_min_frac`)를 넘는지는 다운로드 뒤에야 알았다. 이 비율을 못 넘은 구역은 병합에서 결국 Track A로 채워진다. `--screen-only`는 B1–B3를 Track B와 같은 함수로 실행하고, 남는 타일과 사용 가능 면적을 같은 격자에서 서버 계산만으로 구해 구역별로 `data/cache/district/sits_screen.csv`에 기록한다. H5·색인·체크포인트는 건드리지 않고, 중단 후 다시 실행하면 이어서 판정하며, 오류 행은 재시도한다.

```bash
venv/bin/python src/satellite.py --track B --screen-only            # 전 구역 판정만
venv/bin/python src/satellite.py --track B --screen-only --rescreen # 이미 판정한 구역도 다시
```

`screen_result`는 `sits_expected`(다운로드하면 SITS가 쓰임) 또는 `track_a_expected`(쓰이지 않음, 이유는 `screen_reason`: `no_post_imagery`, `no_pre_imagery`, `no_clear_baseline`, `no_retained_tiles`, `no_usable_pixels`, `usable_below_min`)이며, 판정이 안 된 구역은 `error`다. 이 판정을 Track B 다운로드 대상 선정에 쓸지는 아직 연결하지 않았다.

**SITS 체크포인트.** 파이프라인은 체크포인트를 내려받지 않고 SHA-256으로 검증한다. [hfangcat/SITS-ExtremeEvents](https://github.com/hfangcat/SITS-ExtremeEvents) (commit `637423d6370a31701612fc258782615c0c82e4e9`)의 `checkpoint_vae_contrastive_42.pth`, `_43.pth`, `_44.pth`를 받아 아래 순서로 찾는 위치 중 하나에 둔다.

1. `--checkpoint PATH` (`.pth` 파일 또는 그 디렉터리)
2. 환경변수 또는 `.env`의 `CVND_SITS_CHECKPOINT=PATH` — 클론한 사용자의 기본 방법
3. 저장소 안의 `SITS-ExtremeEvents-main/checkpoints/ravaen/`
4. 저장소 옆의 `SITS-ExtremeEvents-main/checkpoints/ravaen/`

체크포인트는 다른 무엇보다 먼저 확인하므로, 추론할 패치가 없어도 체크포인트가 없으면 시도한 경로를 모두 출력하고 실패한다. `--events`를 줬는데 완성된 H5가 하나도 없으면 nonzero로 끝나며 구역별 사유를 출력한다.

```bash
CVND_SITS_CHECKPOINT=/path/to/checkpoints/ravaen venv/bin/python src/run_sits_inference.py
```

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
