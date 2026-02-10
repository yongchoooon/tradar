# T-RADAR 레포 요약 (상세, 2026-02-08)

이 문서는 **레포 내 코드/문서/구성 파일을 직접 확인한 내용만**으로 정리한 상세 요약입니다.

## 1) 프로젝트 개요
- 상표 **이미지 + 텍스트**를 입력 받아 유사 선행상표를 찾고, 선택 후보에 대해 **KIPRIS 문서 기반 AI Agent 시뮬레이션** 리포트를 생성하는 통합형 상표 검색 시스템
- **검색 → 재검색 → 후보 선택 → 시뮬레이션 → 리포트** 흐름을 하나의 UI에서 제공
- 구성: **FastAPI 백엔드 + Vite/React 프런트엔드 + Desktop GPU 워커(WebSocket) + PostgreSQL/pgvector + OpenSearch + LangGraph**

## 2) 레포 구조 (핵심 경로)
- `app/`: FastAPI 백엔드 핵심 코드
- `api/`: 라우터 (`/search/multimodal`, `/goods/search`, `/media`, `/media/presign`, `/ws/worker`, `/simulation/*`)
  - `pipelines/`: 검색 파이프라인 (`search_pipeline.py`)
  - `services/`: 임베딩/검색/LLM/시뮬레이션/DB 유틸
  - `schemas/`: 요청/응답 스키마
- `frontend/`: Vite + React SPA
- `scripts/`: 데이터 시딩, OpenSearch 동기화, 평가 스크립트
- `data/`: 상표 메타데이터 JSON
- `markdown/`: 상세 설계/운영 문서
- `ecs/`: ECS 태스크 정의

## 3) 백엔드 아키텍처
### 3-1. 엔드포인트
- `POST /search/multimodal`: 이미지/텍스트 멀티모달 검색 (워커로 오프로딩)
- `GET /goods/search`: 상품/서비스류 검색
- `GET /media`: 로컬 이미지 파일 프록시 제공(개발용)
- `POST /media/presign`: S3 presigned URL 발급
- `WS /ws/worker`: 데스크톱 워커 등록/작업 채널
- `POST /simulation/run`: 시뮬레이션 작업 생성
- `GET /simulation/status/{job_id}`: 상태 조회
- `GET /simulation/stream/{job_id}`: SSE 스트림
- `POST /simulation/cancel/{job_id}`: 작업 취소

### 3-2. 환경 변수/환경 제약
- `APP_ENV=prod`이면 `DATABASE_URL`, `OPENSEARCH_URL`, `OPENAI_API_KEY`(유사어), `GEMINI_API_KEY`(시뮬레이션), `KIPRIS_ACCESS_KEY`, `DESKTOP_WORKER_TOKEN` 필수
- `CORS_ALLOWED_ORIGINS`는 운영 환경에서 필수
- 개발 환경에서는 기본값을 세팅하도록 처리

### 3-3. 워커 오프로딩 요약
- `/search/multimodal`은 `worker_bridge`를 통해 `/ws/worker`로 작업을 전송합니다.
- 데스크톱 워커가 로컬 Postgres/pgvector + OpenSearch에서 검색을 수행하고 결과를 반환합니다.

## 4) 검색 파이프라인 상세
### 4-1. 입력 스키마 (`SearchRequest`)
- `image_ref`(권장), `image_b64`(선택), `text`(선택)
- `goods_classes`, `group_codes` (선택)
- `image_prompt`, `image_prompt_mode`
- `text_prompt`, `text_prompt_mode`
- `variants`(재검색 시 유사어 재사용)
- `use_llm_variants`
- `k`(Top-K, 기본 20)

### 4-2. 이미지 검색
- **임베딩 모델**: MetaCLIP2 + DINOv2
- **벡터 검색**: pgvector ANN (워커 컨테이너 내부에서 실행)
- **Top-N 기본값**: 100
- **스코어 블렌딩**: DINO:MetaCLIP = 0.5:0.5 고정
- **이미지 프롬프트**: MetaCLIP 이미지 벡터와 텍스트 프롬프트 벡터를 프리셋(90/10~10/90)으로 블렌딩

### 4-3. 텍스트 검색
- **유사어 생성**: `TextVariantService` (LLM 옵션, 비활성 시 기본 변형만)
- **임베딩**: MetaCLIP2 텍스트 임베딩
- **가중치**: 원문 4.5, 유사어 0.5
- **BM25 확장**: OpenSearch Top-N 후보 추가 (워커 컨테이너 내부에서 실행)
- **프롬프트 해석**: `PromptInterpreter`가 추가 검색어/필터(접두/포함/제외) 추출

### 4-4. 출력 구조
- 결과는 **이미지 Top-K**와 **텍스트 Top-K**를 **분리**하여 반환
- `image_misc`, `text_misc`: Top-K 외 후보 중 상태가 등록/공고가 아닌 항목 일부 노출
- 카드에 상태 배지(등록/공고/거절 등), 유사도, 썸네일 표시 (`thumb_url`은 data URL 또는 외부 URL)

## 5) 시뮬레이션(Agent) 파이프라인
- `/simulation/run` 요청 시 **인메모리 JobManager**가 작업 생성
- **KIPRIS OP/RE API** 호출 → 후보별 문서 수집
- LangGraph 에이전트 흐름: **심사관 → 출원인 → 심사관 재답변 → 리포터 → 채점자**
- 결과는 SSE로 단계별 상태(`collecting`, `simulating`, `complete` 등)와 함께 전달
- 디버그 모드에서는 `logs/simulation_debug/`에 컨텍스트와 LLM 로그 기록

## 6) 데이터/저장소 구성
### 6-1. PostgreSQL + pgvector
- `trademarks`: 메타데이터(상태, 지정상품, 이미지 경로 등)
- `image_embeddings_dino`
- `image_embeddings_metaclip`
- `text_embeddings_metaclip`

### 6-2. OpenSearch
- BM25 텍스트 후보 확장용
- `scripts/sync_opensearch.sh`로 PostgreSQL → OpenSearch 동기화

### 6-3. 로컬 데이터
- `data/`에 대규모 JSON 메타데이터 존재 (예: `data/trademarks_real_2125.json`)
- JSON에는 상태, 지정상품, 이미지 경로 등의 필드 포함
- `app/data/goods_services/`에 상품/서비스류 TSV

## 7) 프런트엔드(UI)
- Vite + React SPA
- 검색 폼(이미지/텍스트), 상품/서비스류 선택 패널, 결과 카드 그리드, 시뮬레이션 패널
- 결과 카드에 상태 배지/유사도/썸네일/출원번호 표시
- 프롬프트 재검색(이미지/텍스트 분리) 및 시뮬레이션 실행/취소 UI 제공

## 8) 배포/운영 구성
- **로컬**: Docker Compose에 Postgres/pgvector + OpenSearch + API + Frontend 포함 (또는 수동 실행)
- **운영**: ECS Fargate + CloudFront + 데스크톱 GPU 워커(WebSocket) + S3 presigned 업로드
- RDS/OpenSearch Service는 클라우드로 이동하는 경우에만 사용(현재 레포 기본 동작은 데스크톱 워커)
- `FRONTEND_DIST` 지정 시 FastAPI가 정적 프런트 서빙 가능

## 9) 로그/관측
- LLM 사용 로그: `logs/openai_usage.csv`, `logs/openai_ai_agent_usage.csv`
- 시뮬레이션 디버그 로그: `logs/simulation_debug/`

## 10) 주요 문서
- `README.md`, `README_dev.md`
- `markdown/search-pipeline.md` (검색 파이프라인 상세)
- `markdown/agent_simulation.md` (시뮬레이션 설계)
- `markdown/frontend.md` (프런트 구조)
- `markdown/tradar_setup_guide.md` (로컬~AWS 배포 가이드)
