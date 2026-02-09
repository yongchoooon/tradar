# T-RADAR 개발 가이드

본 문서는 운영 환경에서 멀티모달 상표 검색을 구현·유지하기 위한 기술 정보를 정리합니다. 더 세부적인 단계별 설명은 `markdown/` 디렉터리를 참고하세요.

## 아키텍처 개요

```
사용자 입력 (이미지, 상표명)
          │
          ▼
  FastAPI /search/multimodal
          │  (WorkerBridge)
          ▼
  WebSocket /ws/worker
          │  (outbound, Desktop Worker)
          ▼
SearchPipeline (Desktop GPU Worker)
 ├─ ImageEmbedder (MetaCLIP2 + DINOv2)
 ├─ TextEmbedder  (MetaCLIP2)
 ├─ TextVariantService → LLM 유사어
 ├─ pgvector (image_embeddings_dino, image_embeddings_metaclip, text_embeddings_metaclip)
 ├─ OpenSearch (BM25)
 └─ PostgreSQL tradar.trademarks 메타데이터
```

## Desktop GPU Worker (신규)
주의: `docker-compose.desktop.yml`은 **db/opensearch 컨테이너를 생성하지 않습니다.**  
db 컨테이너가 안 뜨는 것은 정상이며, **기존 compose 스택을 먼저 실행**해야 합니다.

- 운영 환경에서는 ECS 백엔드가 `/ws/worker` WebSocket으로 데스크톱 GPU 워커에 작업을 위임합니다.
- 워커는 **기존 데스크톱의 Postgres(pgvector) + OpenSearch 컨테이너**에만 연결해 검색을 수행합니다.
- 운영에서는 **presigned URL 방식만 사용**합니다. base64 fallback은 기본 비활성입니다.
  - 브라우저는 `/media/presign`으로 업로드 URL을 받은 뒤 S3에 직접 업로드하고,
    `/search/multimodal`에는 `image_ref`(presigned GET URL)만 전달합니다.
  - CloudFront는 큰 POST 바디를 차단할 수 있으므로 base64 전송은 운영에서 금지합니다.
- 검색 결과 썸네일은 **워커가 로컬 파일을 읽어 작은 data URL로 만들어 반환**합니다.
  (ECS 백엔드는 데스크톱 파일을 직접 접근할 수 없으므로 `/media?path=...`를 운영에서 사용하지 않습니다.)

필수 환경 변수 (워커):
- `WORKER_WS_URL` (예: `wss://<api-cloudfront-domain>/ws/worker`)
- `WORKER_TOKEN` (SSM `/tradar/prod/desktop-worker-token` 값)
- `WORKER_ID` (기본값 `desktop-1`)
- `DATABASE_URL`, `OPENSEARCH_URL`
- `WORKER_REQUIRE_GPU` (기본값 `true`)
- `DESKTOP_COMPOSE_NETWORK` (Mode A 네트워크 이름)
- `ALLOW_BASE64_FALLBACK` (기본값 `false`)
- `BASE64_MAX_IMAGE_BYTES` (기본값 `204800`, 200KB)
- `TRADAR_DATA_BUCKET`, `TRADAR_IMAGE_PREFIX`, `TRADAR_PRESIGN_TTL_SECONDS` (S3 presign 설정)
- `TRADAR_DISABLE_S3` (개발용: `true`면 S3 업로드 시도 자체를 비활성)
- `WORKER_THUMB_ENABLED` (기본값 `true`)
- `WORKER_THUMB_MAX_SIZE` (기본값 `256`)
- `WORKER_THUMB_MAX_BYTES` (기본값 `65536`)
- `WORKER_THUMB_QUALITY` (기본값 `70`)
- `WORKER_THUMB_FORMAT` (기본값 `jpeg`)

### 이미지 업로드 (운영 권장 플로우)
1. 프론트 → `POST /media/presign` (파일명, content-type 전달)
2. 프론트 → presigned `upload_url`로 S3 `PUT`
3. 프론트 → `/search/multimodal` 호출 시 `image_ref`에 presigned `read_url` 전달

S3 버킷 CORS에 `PUT` 허용이 필요합니다.

### GPU 요구사항
- NVIDIA Container Toolkit 필요
- 점검: `nvidia-smi`, `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`
- 워커는 시작 시 GPU 사용 가능 여부와 디바이스를 로그로 출력합니다.
- `WORKER_REQUIRE_GPU=true`이면 GPU 미탐지 시 즉시 종료합니다.

### 썸네일/이미지 경로
- 워커는 검색 결과의 `image_path`를 이용해 **로컬 파일에서 썸네일을 생성**합니다.
- 따라서 워커 컨테이너 안에서 DB에 저장된 `image_path`가 실제로 존재해야 합니다.
- 기본 `docker-compose.desktop.yml`은 `${TRADAR_IMAGE_ROOT:-../tradar-data}`를 `/data/images`로 마운트합니다.
  DB의 `image_path`가 `/data/images/...` 형식인지 확인하거나, 경로가 다르면 마운트를 맞춰주세요.

### Mode A: 기존 docker-compose 네트워크에 붙이기 (권장)
정의: 기존 compose 스택(db/opensearch)이 **이미 실행 중**이어야 합니다. 워커는 db/opensearch를 생성하지 않습니다.

필수 선행 단계:
1. 기존 db/opensearch 컨테이너가 실행 중인지 확인합니다.
2. 해당 compose가 만든 네트워크 이름을 확인합니다.
3. `DESKTOP_COMPOSE_NETWORK`를 올바르게 설정합니다.
4. desktop-worker compose를 실행합니다.

네트워크 이름 확인 방법:
- `docker network ls`
- `docker network inspect <project>_default`
- 자동 확인: `bash scripts/find_compose_network.sh` (출력값을 `DESKTOP_COMPOSE_NETWORK`로 사용)

워커 전용 컴포즈 실행:
```bash
export WORKER_WS_URL=wss://<api-cloudfront-domain>/ws/worker
export WORKER_TOKEN=<shared-token>
export DESKTOP_COMPOSE_NETWORK=<project>_default
docker compose -f docker-compose.desktop.yml up --build
```
- 기본 네트워크 이름은 `tradar_default` 입니다. 프로젝트 이름이 다르면 `DESKTOP_COMPOSE_NETWORK`로 지정하세요.

### Mode B: 호스트 포트( localhost:5432 / 9200 )로 접속 (fallback)
정의: 워커가 호스트 포트로 접속합니다. 기존 컨테이너가 호스트 포트에 바인딩되어 있어야 합니다.
```bash
export WORKER_WS_URL=wss://<api-cloudfront-domain>/ws/worker
export WORKER_TOKEN=<shared-token>
export DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/tradar
export OPENSEARCH_URL=http://localhost:9200
docker compose -f docker-compose.desktop.yml up --build
```
호스트에서 직접 실행하려면:
```bash
export WORKER_WS_URL=wss://<api-cloudfront-domain>/ws/worker
export WORKER_TOKEN=<shared-token>
export DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/tradar
export OPENSEARCH_URL=http://localhost:9200
python -m worker.main
```

### 트러블슈팅
- 네트워크 이름 불일치: `DESKTOP_COMPOSE_NETWORK`를 실제 `<project>_default`로 맞춥니다.
- 기존 compose 미실행: db/opensearch 컨테이너가 떠 있어야 합니다.
- 연결 실패: 워커 시작 시 DB/opensearch 연결성 체크 로그를 확인하세요.

### 운영 체크리스트
- CloudFront(tradar-api-cf): `/ws/*` behavior 분리, 캐시 비활성, Origin request policy는 AllViewer 계열, HTTPS only.
- CloudFront(tradar-api-cf): `/search*`, `/media*`는 POST가 필요하므로 허용 HTTP 메서드에 POST/OPTIONS 포함.
- ALB idle timeout 300~600초로 상향.
- ECS desired count=1 유지(워커 registry는 메모리 기반).

- **PostgreSQL + pgvector**: 모든 임베딩과 상표 메타데이터를 보관합니다.
- **OpenSearch**: BM25 텍스트 후보 확장을 담당합니다.
- **OpenAI GPT-4o-mini**: 상표명 유사어를 생성합니다. 기본값은 꺼져 있으며, 프런트엔드의 "LLM 유사어" 체크박스를 켜면 해당 검색에만 호출합니다.
- **FastAPI**: `/search/multimodal`에서 이미지·텍스트 결과를 각각 Top-K로 반환합니다.
- **LangGraph + KIPRIS REST**: `/simulation/run`에서 선택된 선행상표의 의견제출통지서/거절결정서를 호출하고 에이전트 기반으로 등록 가능성을 평가합니다.

### 시뮬레이션 파이프라인 요약

1. 프런트엔드에서 기본 이미지/텍스트 상위 5건(최대 20건) 출원번호를 `/simulation/run`으로 전송합니다.
2. 백엔드는 `KIPRIS_ACCESS_KEY`로 IntermediateDocument OP/RE API를 호출하여 거절사유/추가사유/이미지/최종변동일자를 수집합니다.
3. 사용자 UI에서 선택한 상품류·유사군뿐 아니라 각 유사군에 속한 지정상품 이름 목록(`user_goods_names`)과 업로드 이미지(`user_image_ref` + `user_image_mime`, 필요 시 `user_image_b64` 폴백)를 전달해 LangGraph 프롬프트가 실제 사용자의 지정상품과 외관을 참고하도록 합니다.
4. 수집된 텍스트 및 사용자 맥락을 LangGraph(심사관→출원인→심사관 재답변→리포터→채점자) 에이전트에 주입하고 OpenAI(`SIMULATION_LLM_MODEL`, 기본 gpt-5-nano)로 대화/요약/위험 분석을 생성합니다.
5. 각 후보별 결과에는 충돌 위험도(`conflict_score`), 등록 가능성(`register_score`), LLM 근거(`rationale`, `factors[]`), 대화 로그가 포함됩니다. 시뮬레이션 워커는 최대 10개까지 병렬 실행되어 지연을 줄입니다.
6. 모든 후보 평가가 끝나면 평균 점수, 고위험 건수, `overall_report`(여러 후보를 묶어 Markdown으로 정리한 최종 리포트)를 계산해 프런트엔드 상단 요약 카드에 사용합니다.

### 비동기 처리

- `/simulation/run`은 요청을 큐에 넣고 `job_id`를 반환합니다. FastAPI `BackgroundTasks`가 별도 스레드에서 KIPRIS 호출 → LangGraph 실행을 수행합니다.
- 클라이언트는 `/simulation/stream/{job_id}` SSE 스트림 또는 `/simulation/status/{job_id}`를 통해 `pending/collecting/simulating/complete/failed/cancelled` 상태와 결과(`SimulationResponse`)를 확인합니다.
- 작업 정보는 메모리 내 `SimulationJobManager`가 관리하며, 서버 재시작 시 초기화되므로 장기 저장이 필요한 경우 외부 스토리지를 추가해야 합니다.

필수 환경 변수:
- 운영(`APP_ENV=prod`)에서는 `DATABASE_URL`, `OPENSEARCH_URL`, `OPENAI_API_KEY`, `KIPRIS_ACCESS_KEY`, `CORS_ALLOWED_ORIGINS`, `DESKTOP_WORKER_TOKEN` 값을 반드시 OS 환경 또는 AWS SSM Parameter Store에서 주입해야 합니다. 값이 하나라도 비어 있으면 FastAPI가 즉시 종료합니다.
- 검색은 워커가 처리하지만 **백엔드는 기동 체크 때문에 `DATABASE_URL`/`OPENSEARCH_URL`이 필요**합니다.
- 로컬 개발(`APP_ENV!=prod`)에서는 `.env`가 있으면 자동으로 로드하고, `DATABASE_URL`/`OPENSEARCH_URL`은 각각 `postgresql://postgres:postgres@localhost:5432/tradar`, `http://localhost:9200`로 기본값을 채웁니다.
- `CORS_ALLOWED_ORIGINS`는 콤마로 구분된 허용 Origin 목록입니다. 기본값은 `http://localhost:5173`이며, 운영 환경에서는 `https://<cloudfront-domain>`처럼 구체적인 도메인을 지정해야 합니다.
- 시뮬레이션 LLM 모델(`SIMULATION_LLM_MODEL`)은 환경 변수로 조정할 수 있고, 온도는 코드 상에서 1.0으로 고정되어 별도 설정이 필요 없습니다.

참고: 시뮬레이션 호출은 외부 REST API를 동기적으로 호출하므로, 한 번에 많은 상표를 선택하면 응답 시간이 길어질 수 있습니다. 네트워크 탭과 FastAPI 로그(`simulation` 로거)를 통해 진행 상황을 확인할 수 있습니다.

## 프런트엔드 개발 환경 (Vite)
- `frontend/` 디렉터리는 Vite 기반 React SPA입니다. `npm install` 한 번이면 모든 의존성이 설치됩니다.
- 로컬 개발 시에는 `npm run dev`로 Vite Dev Server(기본 `http://localhost:5173`)를 띄우고, `bash scripts/run_api.sh`로 FastAPI를 별도로 구동합니다. API 호출은 항상 `import.meta.env.VITE_API_BASE_URL`을 통해 절대 경로로 전송됩니다. 로컬에서 직접 실행할 때는 `frontend/.env.local`에 `VITE_API_BASE_URL=http://localhost:8000`을 지정하세요. Docker Compose 환경에서는 `VITE_API_BASE_URL=/api`로 두고, Vite dev proxy(기본 `http://api:8000`)를 사용합니다.
- 운영/테스트 배포에서는 SPA를 별도 S3/CloudFront에 올리고 FastAPI는 API 전용으로 실행합니다. 빌드 전에 `VITE_API_BASE_URL`을 백엔드 공개 주소(예: `https://api.tradar.com`)로 주입해야 하며, CloudFront 도메인에서는 모든 API 요청이 해당 절대 경로로 전송됩니다. `FRONTEND_DIST` 환경 변수를 직접 지정한 경우에만 정적 자산을 서빙하므로, 로컬에서 `npm run build` 결과를 확인하고 싶을 때 `FRONTEND_DIST=frontend/dist uvicorn app.main:app` 형태로 실행하면 됩니다.
- Docker나 AWS 배포 파이프라인도 백엔드와 프런트엔드를 분리합니다. 백엔드 이미지는 `app/` 코드와 Python 의존성만 포함하고, 프런트 배포는 `frontend/dist`를 S3에 업로드하거나 CloudFront에 연결된 버킷으로 동기화하세요.
- `docker-compose.yml`은 개발 편의용으로만 제공합니다. `.:/app` 볼륨 마운트, 로컬 Postgres/OpenSearch 컨테이너 등은 프로덕션에서 사용하지 말고, **ECS 백엔드 + 데스크톱 워커(WebSocket) + S3 presign** 구성에 필요한 환경 변수는 모두 OS 환경이나 AWS SSM Parameter Store에서 주입하세요.
- `frontend/src/index.css`는 `--viewport-scale`, `--space-scale` 같은 루트 변수를 통해 창 너비에 따라 글꼴/패딩/갭을 자동으로 조절합니다. 큰 모니터에서는 100% 크기로, 14~16인치 노트북에서는 약 80%까지 자연스럽게 축소되므로, 레이아웃 변경 시 해당 변수를 먼저 고려하세요.

### 로컬/운영 API 연동 확인 방법
1. **로컬**
   - `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (또는 `bash scripts/run_api.sh`) 로 백엔드를 실행합니다.
   - 로컬에서 직접 실행할 때는 `frontend/.env.local` 에 `VITE_API_BASE_URL=http://localhost:8000` 를 지정하고 `npm run dev` 를 실행합니다. Docker Compose 환경에서는 `VITE_API_BASE_URL=/api`로 설정하면 Vite dev proxy가 `/api` 요청을 백엔드(`http://api:8000`)로 전달합니다.
   - 브라우저에서 상품/서비스류 검색이나 `/search/multimodal` 요청이 모두 JSON으로 응답하는지 확인하세요.
2. **운영**
   - 프런트 배포 파이프라인에서 `VITE_API_BASE_URL=https://<백엔드-도메인>` 으로 빌드합니다.
   - CloudFront 도메인으로 접속 후 개발자 콘솔에서 API 요청이 CloudFront가 아닌 백엔드 도메인으로 향하고, 응답이 JSON(`content-type: application/json`)인지 확인합니다.

## 데이터 시딩

> **참고**: 아래 스크립트(`scripts/vector_db_prepare*.py`, `scripts/sync_opensearch.sh`)는 FastAPI 기동 시 자동 실행되지 않습니다. 데이터나 인덱스를 새로 준비해야 할 때 CLI에서 수동으로 호출하세요.

### 전체 임베딩 적재
```bash
python scripts/vector_db_prepare.py \
  --metadata data/trademarks.json \
  --images-root data/images \
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
  --metadata data/append.json \
  --database-url postgresql://postgres:postgres@localhost:5432/tradar \
  --text-backend torch \
  --metaclip-model /home/work/workspace/models/metaclip \
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

### 이미지 흐름 (기본 N=100, K 기본 20)
1. 입력 이미지를 MetaCLIP2/DINOv2로 임베딩 (임베딩 결과는 LRU 캐시에 저장돼 동일 이미지 재검색 시 재사용)
2. pgvector에서 각각 ANN Top-N 후보 검색
3. 각 후보에 대해 누락된 공간의 임베딩을 다시 읽어 코사인 유사도 계산
4. 기본 스코어 가중치는 DINO:MetaCLIP = 0.5:0.5로 고정됩니다.
5. Top-K를 선정합니다. API 기본값은 20이지만 프런트엔드는 한 번의 호출로 최대 200건(`k=200`)을 요청해 이후 페이징/재선택에 활용합니다.

### 텍스트 흐름
1. 상표명 → `use_llm_variants=true`일 때 TextVariantService가 기본 변형(대소문자/공백 등) + (옵션) GPT-4o-mini 유사어를 생성합니다. LLM 프롬프트는 "T-RADAR-1"처럼 단순 일련번호·접미사를 붙이는 변형을 금지하도록 조정했습니다.
2. 원본 질의와 유사어를 MetaCLIP2 텍스트 임베딩으로 변환한 뒤 가중 평균해 정규화합니다. 첫 입력 상표명은 4.5배, 나머지 유사어는 0.5배로 처리해 원본 질의가 항상 가장 큰 비중을 차지하도록 했습니다.
3. 재결합된 벡터로 pgvector ANN Top-N 검색을 수행합니다.
4. 용어를 공백으로 결합해 OpenSearch BM25 Top-N 검색을 수행합니다.
5. ANN + BM25 후보 전체에 대해 MetaCLIP 코사인 유사도를 계산합니다.
6. MetaCLIP 유사도로 Top-K를 선택합니다. 기본값은 20이며, 프런트엔드는 이미지와 동일하게 200건까지 받아 자체 페이징합니다. 향후 선택한 상품 분류 정보를 활용한 그룹화가 추가될 예정입니다.

- 프런트엔드의 “LLM 유사어” 토글은 기본적으로 꺼져 있으며, 사용자가 켜면 기본 변형 + LLM 유사어(최대 10개)를 포함합니다 (`use_llm_variants`). 요청에 `variants`가 포함되면 TextVariantService를 재호출하지 않고 그대로 사용합니다.

### 재검색 참고
- 검색은 항상 Top-N을 다시 질의하는 방식으로 동작하여 기존 후보에 국한되지 않습니다.

### 응답 필드
- `image_top`, `text_top`: 각각 Top-K 리스트 (기본 20, 프런트엔드는 `k=200`으로 호출해 18개씩 페이징)
- `image_misc`, `text_misc`: Top-K 이외 후보 중 `등록`/`공고`가 아닌 상태를 가진 항목(최대 10)
- `SearchResult`: `trademark_id`, `title`, `status`, `class_codes`, `app_no`, `image_sim`, `text_sim`, `thumb_url`, `image_path`, `goods_services`
- `QueryInfo`: `k`, `text`, `goods_classes`, `group_codes`, `variants` (`goods_classes`/`group_codes`는 향후 인접군 분류를 위해 예약된 필드이며 현재 점수에는 영향을 주지 않음)
- `DebugInfo.messages`: 이미지 가중치 고정 여부, variants 재사용 여부 등 파이프라인 메시지를 배열로 반환합니다.

## 세션 부팅

- `scripts/bootstrap_seed.sh`: 신규 세션, 시스템 및 의존성 설치 + 데이터 시딩
- `scripts/bootstrap_session.sh`: 재개 세션, PostgreSQL 스냅샷 복원, OpenSearch 번들 확인, `sync_opensearch.sh` 실행
- 상세 절차는 `markdown/session-bootstrap.md` 참조

## 운영 팁

- **LLM 사용**: `.env` 또는 AWS SSM에 `OPENAI_API_KEY`만 설정하면 됩니다. 검색 화면의 "LLM 유사어" 체크박스가 켜진 요청에서만 OpenAI API를 호출하고, 검색 LLM 비용 로그는 `logs/openai_usage.csv`, AI Agent 시뮬레이션 LLM 로그는 `logs/openai_ai_agent_usage.csv`에 각각 누적됩니다. 채점자 에이전트는 Reporter Markdown 요약을 기반으로 충돌 위험도/등록 가능성을 산출하며, 모든 후보 데이터를 모아 "최종 리포터" LLM이 일관된 Markdown 요약(전체 결론/평균 점수/후속 권고/선행상표별 한 줄 요약)을 제공합니다. 디버그 모드(`시뮬레이션 실행(디버그)` 버튼)는 `logs/simulation_debug/<timestamp>` 경로에 사용자/선행상표 컨텍스트와 LLM 프롬프트/응답 로그를 생성합니다. 진행 중이라면 `실행 취소` 버튼으로 백엔드 작업을 중단할 수 있으며, 상태는 SSE 스트림에 즉시 반영됩니다.
- **임베딩 모델 경로**: 기본값은 `/home/work/workspace/models/{metaclip,dinov2}`. 변경 시 `METACLIP_MODEL_NAME`, `DINOV2_MODEL_NAME` 환경변수를 사용하세요.
- **장비**: GPU가 없다면 `EMBED_DEVICE=cpu` 및 `BOOTSTRAP_*` 변수로 조정 가능합니다.
- **백엔드 선택**: FastAPI와 모든 시딩/부팅 스크립트는 Torch 백엔드를 기본 사용합니다. 더미(해시) 백엔드는 제거되었으며, 모델이 없을 경우 스크립트가 즉시 실패합니다.
- **임베딩 캐시**: `PIPELINE_EMBED_CACHE_SIZE`(기본 128) 환경 변수로 이미지·텍스트 임베딩 LRU 캐시 크기를 조절해 검색 성능을 최적화할 수 있습니다.
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
