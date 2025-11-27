# T-RADAR 개발 가이드

본 문서는 운영 환경에서 멀티모달 상표 검색을 구현·유지하기 위한 기술 정보를 정리합니다. 더 세부적인 단계별 설명은 `markdown/` 디렉터리를 참고하세요.

## 아키텍처 개요

```
사용자 입력 (이미지, 상표명)
          │
          ▼
  FastAPI /search/multimodal
          │
          ├─ ImageEmbedder (MetaCLIP2 + DINOv2)
          ├─ TextEmbedder  (MetaCLIP2)
          ├─ TextVariantService → LLM 유사어
          │
          ├─ pgvector (image_embeddings_dino, image_embeddings_metaclip, text_embeddings_metaclip)
          ├─ OpenSearch (BM25)
          └─ PostgreSQL tradar.trademarks 메타데이터
```

- **PostgreSQL + pgvector**: 모든 임베딩과 상표 메타데이터를 보관합니다.
- **OpenSearch**: BM25 텍스트 후보 확장을 담당합니다.
- **OpenAI GPT-4o-mini**: 상표명 유사어를 생성합니다 (`TRADEMARK_LLM_ENABLED=true` 일 때).
- **FastAPI**: `/search/multimodal`에서 이미지·텍스트 결과를 각각 Top-K로 반환합니다.
- **LangGraph + KIPRIS REST**: `/simulation/run`에서 선택된 선행상표의 의견제출통지서/거절결정서를 호출하고 에이전트 기반으로 등록 가능성을 평가합니다.

### 시뮬레이션 파이프라인 요약

1. 프런트엔드에서 기본 이미지/텍스트 상위 5건(최대 40건) 출원번호를 `/simulation/run`으로 전송합니다.
2. 백엔드는 `KIPRIS_ACCESS_KEY`로 IntermediateDocument OP/RE API를 호출하여 거절사유/추가사유/이미지/최종변동일자를 수집합니다.
3. 수집된 텍스트를 LangGraph(심사관→출원인→심사관 재답변→리포터→채점자) 에이전트에 주입하고 OpenAI(`SIMULATION_LLM_MODEL`, 기본 gpt-4o-mini)로 대화/요약/위험 분석을 생성합니다.
4. 유사도 기반 휴리스틱 점수와 에이전트 결과를 묶어 프런트엔드 패널에 요약과 상위 후보별 노트를 보여 줍니다. LangGraph 호출은 내부적으로 최대 4개 워커로 병렬 실행되어 지연을 줄입니다.

### 비동기 처리

- `/simulation/run`은 요청을 큐에 넣고 `job_id`를 반환합니다. FastAPI `BackgroundTasks`가 별도 스레드에서 KIPRIS 호출 → LangGraph 실행을 수행합니다.
- 클라이언트는 `/simulation/stream/{job_id}` SSE 스트림 또는 `/simulation/status/{job_id}`를 통해 `pending/running/complete/failed` 상태와 결과(`SimulationResponse`)를 확인합니다.
- 작업 정보는 메모리 내 `SimulationJobManager`가 관리하며, 서버 재시작 시 초기화되므로 장기 저장이 필요한 경우 외부 스토리지를 추가해야 합니다.

필수 환경 변수:
- `.env`에 `KIPRIS_ACCESS_KEY`, `OPENAI_API_KEY`를 설정하고 FastAPI가 자동으로 `load_dotenv()`로 읽어옵니다.
- 선택적으로 `SIMULATION_LLM_MODEL`, `SIMULATION_LLM_TEMPERATURE`, `SIMULATION_LLM_TEMPERATURE`로 모델/온도를 조정할 수 있습니다.

참고: 시뮬레이션 호출은 외부 REST API를 동기적으로 호출하므로, 한 번에 많은 상표를 선택하면 응답 시간이 길어질 수 있습니다. 네트워크 탭과 FastAPI 로그(`simulation` 로거)를 통해 진행 상황을 확인할 수 있습니다.

## 데이터 시딩

### 전체 임베딩 적재
```bash
python scripts/vector_db_prepare.py \
  --metadata /data/trademarks.json \
  --images-root /data/images \
  --database-url postgresql://postgres:postgres@localhost:5432/tradar \
  --truncate \
  --image-backend torch \
  --text-backend torch \
  --metaclip-model /home/work/workspace/models/metaclip \
  --dinov2-model /home/work/workspace/models/dinov2 \
  --embed-device cuda:0
```
- `trademarks` 메타데이터와 세 가지 임베딩 테이블을 모두 덮어씁니다.
- 이미지/텍스트가 없는 레코드는 실패로 간주됩니다.
- 더미 해시 임베딩 백엔드는 더 이상 제공되지 않습니다. Torch 모델 경로가 유효해야 하며, 벡터 차원(1536/1280)이 DB 스키마와 일치합니다.

### 텍스트 임베딩만 추가 적재
```bash
python scripts/vector_db_prepare_text_only.py \
  --metadata /data/append.json \
  --database-url postgresql://postgres:postgres@localhost:5432/tradar \
  --text-backend torch \
  --metaclip-model facebook/metaclip-2-worldwide-giant \
  --embed-device cuda:0
```
- 기존 이미지 임베딩은 유지한 채 `trademarks`, `text_embeddings_metaclip`만 업데이트합니다.
- 자세한 사용법은 `markdown/text-only-ingest.md` 참조.

### OpenSearch 동기화
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tradar \
OPENSEARCH_URL=http://localhost:9200 \
bash scripts/sync_opensearch.sh
```
- `trademarks`의 기본 필드를 `OPENSEARCH_INDEX`(기본 `tradar_trademarks`)로 밀어 넣습니다.

## 유사도 평가

- 1:1 검증: `scripts/evaluate_similarity_pairs.py --pairs-json published_similar_pair_data_i_have.json`
- 1:N 검증: `scripts/evaluate_similarity_pairs_ylist.py --pairs-json published_similar_pair_data_i_have_appearance_similarity_2125.json`

두 스크립트 모두 FastAPI 검색 파이프라인을 직접 호출해 랭크 정보를 CSV/JSON으로 저장합니다. 특히 `evaluate_similarity_pairs_ylist.py`는 `y_list` 안의 여러 후보 중 가장 높은 랭크를 찾아 점수를 계산합니다.

```
python scripts/evaluate_similarity_pairs_ylist.py \
  --pairs-json published_similar_pair_data_i_have_title_similarity_2125.json \
  --k 100 \
  --max-pairs 50 \
  --debug-dump-dir debug_runs/title_eval \
  --ks 1 5 10 20 50 100 \
  --experiment-name title_eval
```

- `--k`는 파이프라인에서 가져올 후보 수이므로, 평가하고 싶은 가장 큰 K(예: 100) 이상으로 지정하세요.
- `--max-pairs`를 지정하면 상위 N개 레이블만 빠르게 돌려 디버깅할 수 있습니다 (생략 시 전체 사용).
- `--debug-dump-dir`를 주면 각 x→y_list 케이스마다 검색 결과/디버그 정보를 JSON으로 저장하므로, 실제 Top-K가 어떻게 나왔는지 손쉽게 확인할 수 있습니다 (상대 경로는 `--output-dir` 기준).
- `--ks`는 요약 통계에 포함할 K 리스트이며 기본값이 `1 5 10 20 50 100`입니다.
- 결과 CSV/요약 JSON은 `evaluation/` 디렉터리에 `similar_ylist_eval_*`(혹은 `similar_pairs_eval_*`) 이름으로 저장됩니다.

## 검색 파이프라인 요약

이미지와 텍스트는 분리된 Top-K 리스트로 반환됩니다. 자세한 단계는 `markdown/search-pipeline.md`에 기록되어 있습니다.

### 이미지 흐름 (기본 N=100, K=20)
1. 입력 이미지를 MetaCLIP2/DINOv2로 임베딩 (임베딩 결과는 LRU 캐시에 저장돼 동일 이미지 재검색 시 재사용)
2. pgvector에서 각각 ANN Top-N 후보 검색
3. 각 후보에 대해 누락된 공간의 임베딩을 다시 읽어 코사인 유사도 계산
4. 기본 스코어 가중치는 DINO:MetaCLIP = 0.5:0.5로 고정되며, 재검색 프롬프트를 사용해도 최종 점수 비율은 변하지 않고 MetaCLIP 질의 벡터만 프리셋(90/10 · 70/30 · 50/50 · 30/70 · 10/90)에 맞춰 섞입니다.
5. 이미지 프롬프트가 제공되면 MetaCLIP 이미지 벡터와 프롬프트 텍스트 임베딩을 가중 평균해 새 질의를 구성합니다.
6. Top-K를 선정합니다. 추후 `goods.is_adjacent`를 활용해 인접/비인접 그룹으로 재구성할 예정이며, 현재는 단일 리스트로 반환됩니다.

### 텍스트 흐름
1. 상표명 → TextVariantService → GPT-4o-mini 유사어 생성 (활성화 시)
2. 텍스트 프롬프트가 있으면 LLM 기반 `PromptInterpreter`가 추가 키워드/필터(접두어, 포함/제외 토큰)를 추출하며, 실패 시 프롬프트 문장을 보조 키워드로만 사용한다고 디버그 메시지로 알려줍니다.
3. 원본 질의, 유사어, 프롬프트 키워드를 MetaCLIP2 텍스트 임베딩으로 변환한 뒤 90/10 · 70/30 · 50/50 · 30/70 · 10/90 가중치 프리셋에 맞춰 재결합합니다. 첫 입력 상표명은 다른 유사어보다 더 큰 가중치(1.5배)를 부여해 영어 입력이 한글 변형에 묻히지 않도록 합니다. 프런트엔드의 “LLM 유사어” 토글은 기본적으로 꺼져 있으며, 사용자가 켜면 LLM 유사어 10개를 생성해 이 단계에 포함하고 끄면 원문만 사용합니다 (`use_llm_variants`).
4. 재결합된 벡터로 pgvector ANN Top-N 검색을 수행하고, LLM에서 생성한 필터(예: 접두어)는 결과 재정렬 단계에서 적용합니다.
5. 용어를 공백으로 결합해 OpenSearch BM25 Top-N 검색
6. BM25 전용 후보는 텍스트 임베딩을 DB에서 읽어 코사인 유사도 계산 (동일하게 `<#>` 결과의 부호를 보정)
7. MetaCLIP 유사도와 프롬프트 필터를 반영해 Top-K를 선택합니다. 향후 선택한 상품 분류 정보를 활용한 그룹화가 추가될 예정입니다.

### 프롬프트 재검색
- 프런트엔드에서 "최우선"/"우선"/"균형"/"프롬프트 우선" 프리셋을 제공하며, 각각 90/10 · 70/30 · 50/50 · 30/70 · 10/90 가중치로 이미지/텍스트 임베딩이 보정됩니다.
- 이미지 프롬프트는 MetaCLIP 이미지 벡터만 재가중하며 DINO 스코어 비중은 항상 0.5로 유지됩니다 (MetaCLIP 질의 벡터만 프리셋 비율로 조정).
- 텍스트 프롬프트는 LLM을 통해 추가 키워드·접두 조건을 추출하고, 실패 시 보조 검색어만 추가한 뒤 그 사실을 디버그 메시지에 남깁니다.
- 재검색 요청에 `variants` 필드를 전달하면 기존 LLM 유사어를 그대로 재사용하고 TextVariantService를 재호출하지 않습니다.
- 모든 재검색은 Top-N을 다시 질의하는 방식으로 동작하여 기존 후보에 국한되지 않습니다.

### 응답 필드
- `image_top`, `text_top`: 각각 Top-K 리스트 (기본 20)
- `image_misc`, `text_misc`: Top-K 이외 후보 중 `등록`/`공고`가 아닌 상태를 가진 항목(최대 10)
- `SearchResult`: `trademark_id`, `title`, `status`, `class_codes`, `app_no`, `image_sim`, `text_sim`, `thumb_url`
- `QueryInfo`: `k`, `text`, `goods_classes`, `group_codes`, `variants` (`goods_classes`/`group_codes`는 향후 인접군 분류를 위해 예약된 필드이며 현재 점수에는 영향을 주지 않음)
- `DebugInfo.messages`: 재검색 가중치, 프롬프트 LLM 해석, 폴백 여부 등 텍스트 메시지를 배열로 반환합니다.

## 세션 부팅

- `scripts/bootstrap_seed.sh`: 신규 세션, 시스템 및 의존성 설치 + 데이터 시딩
- `scripts/bootstrap_session.sh`: 재개 세션, PostgreSQL 스냅샷 복원, OpenSearch 번들 확인, `sync_opensearch.sh` 실행
- 상세 절차는 `markdown/session-bootstrap.md` 참조

## 운영 팁

- **LLM 사용**: `.env`에 `OPENAI_API_KEY`, `TRADEMARK_LLM_ENABLED=true` 설정. 비용 로그는 `logs/openai_usage.csv`에 누적됩니다.
- **프롬프트 LLM**: 재검색 프롬프트 전용 모델을 조정하려면 `PROMPT_LLM_MODEL`, `PROMPT_LLM_TEMPERATURE` 환경 변수를 사용하세요 (기본값은 `TRADEMARK_LLM_MODEL`/`0.1`).
- **임베딩 모델 경로**: 기본값은 `/home/work/workspace/models/{metaclip,dinov2}`. 변경 시 `METACLIP_MODEL_NAME`, `DINOV2_MODEL_NAME` 환경변수를 사용하세요.
- **장비**: GPU가 없다면 `EMBED_DEVICE=cpu` 및 `BOOTSTRAP_*` 변수로 조정 가능합니다.
- **백엔드 선택**: FastAPI와 모든 시딩/부팅 스크립트는 Torch 백엔드를 기본 사용합니다. 더미(해시) 백엔드는 제거되었으며, 모델이 없을 경우 스크립트가 즉시 실패합니다.
- **임베딩 캐시**: `PIPELINE_EMBED_CACHE_SIZE`(기본 128) 환경 변수로 이미지·텍스트 임베딩 LRU 캐시 크기를 조절해 재검색 성능을 최적화할 수 있습니다.
- **.env 로딩**: FastAPI 기동 시 `python-dotenv`가 프로젝트 루트의 `.env`를 자동 로드합니다. `KIPRIS_ACCESS_KEY`, `OPENAI_API_KEY` 등 시크릿은 이 파일에 정의하면 됩니다.

## 개발 지침

1. **문서 우선**: 파이프라인 변경 시 `README_dev.md`, `markdown/search-pipeline.md`를 반드시 갱신합니다.
2. **테스트 데이터**: 더미 데이터나 OCR 샘플은 사용하지 않습니다. 실제 상표 데이터 기준으로 동작을 검증하세요.
3. **코드 스타일**: `python -m compileall`로 최소 문법 검사를 수행하고, 주요 변경점은 PR/커밋 메시지에 서술합니다.
4. **보안/비용**: OpenAI 키는 `.env` 등 비공개 파일에서만 관리하고, 사용 로그를 주기적으로 점검하세요.

## 참고 문서
- `markdown/search-pipeline.md`: 검색 단계, 점수 계산, 응답 예시
- `markdown/frontend.md`: 프런트엔드 구조와 API 연동 포맷
- `markdown/session-bootstrap.md`: KT Cloud 부팅/복구 체크리스트
