# T-RADAR

멀티모달 상표 검색 레퍼런스 구현입니다. 이미지와 텍스트를 동시에 받아 MetaCLIP2/DINOv2 임베딩과 OpenSearch BM25를 결합해 유사 상표를 찾아 주며, 상표 메타데이터·상품/서비스류 정보를 함께 제공합니다.

## 아키텍처 한눈에 보기

- **FastAPI + React**: 단일 포트에서 API와 UI를 동시에 제공
- **PostgreSQL + pgvector**: 이미지/텍스트 임베딩과 상표 메타데이터 저장
- **OpenSearch**: BM25 텍스트 후보 확장, 재검색 프롬프트 필터링
- **PyTorch 백엔드**: MetaCLIP2 · DINOv2 임베딩 생성 (CUDA/CPU 선택)
- **LLM 보조 기능**: 상표명 유사어·프롬프트 해석(선택)으로 검색 보정
- **AI Agent 시뮬레이션**: KIPRIS REST API + LangGraph 기반 에이전트가 등록 가능성과 충돌 위험을 분석

전체 플로우와 운영 가이드는 [`README_dev.md`](README_dev.md)에 상세히 정리되어 있습니다.

## 빠른 시작

```bash
# 1. 의존성 설치 및 초기 시딩
bash scripts/bootstrap_seed.sh \
  data/trademarks_real_2125.json \
  data/images

# 2. API/프런트엔드 실행
bash scripts/run_api.sh

# 3. (선택) 텍스트만 추가 시딩
python scripts/vector_db_prepare_text_only.py --metadata data/trademarks_append.json
```

기본 설정은 `.env` 또는 환경변수 `DATABASE_URL`, `OPENSEARCH_URL`, `METACLIP_MODEL_NAME`, `DINOV2_MODEL_NAME`, `EMBED_DEVICE` 등으로 제어합니다. 프런트엔드는 `http://localhost:8000`에서 곧바로 확인할 수 있습니다.

## 검색 파이프라인 요약

1. 업로드된 이미지 → MetaCLIP2/DINOv2 임베딩 생성 → pgvector ANN → 정확도 재계산 → DINO/MetaCLIP 0.5:0.5 블렌딩
2. 상표명 + (선택적) LLM 유사어 + 프롬프트 → 텍스트 임베딩 → pgvector ANN + BM25 → 필터 적용·가중 합산
3. 이미지/텍스트 결과를 각각 Top-K로 노출하고, 디버그 패널에서 후보별 점수와 프롬프트 메시지를 확인

LLM 기반 유사어와 프롬프트 해석은 UI 토글로 온/오프할 수 있으며, 모든 동작은 `markdown/search-pipeline.md`에 그림과 함께 설명되어 있습니다.

## AI Agent 기반 등록 가능성 시뮬레이션

검색 결과 카드에서 기본으로 선택된 이미지/텍스트 상위 5건(최대 40건까지 조정 가능)을 기준으로 다음 단계를 수행합니다.

1. 선택된 출원번호를 이용해 KIPRIS REST API(의견제출통지서/거절결정서, 추가 거절 내용, 이미지 등)를 호출합니다.
2. 수집된 문서 내용을 정규화한 뒤 LangGraph 위에 구성한 `심사관 → 출원인 → 심사관 재응답 → 리포터 → 채점자` 에이전트 체인에 전달합니다.
3. 에이전트가 생성한 대화/요약/위험 평가와 유사도 기반 점수를 조합해 `/simulation/run` API 응답을 구성하고, 프런트엔드 패널에서 요약/상세 정보를 보여 줍니다.
4. `/simulation/run`은 비동기 작업을 생성해 `job_id`를 반환하며, 프런트엔드는 `/simulation/stream/{job_id}`(SSE) 또는 `/simulation/status/{job_id}`로 완료 여부와 결과를 확인합니다.

### 필요한 환경 변수

- `KIPRIS_ACCESS_KEY`: KIPRIS IntermediateDocument REST API 키
- `OPENAI_API_KEY`: LangGraph 에이전트가 사용할 LLM 키 (기본 `gpt-4o-mini`)
- `SIMULATION_LLM_MODEL`, `SIMULATION_LLM_TEMPERATURE` (선택): 에이전트 모델/온도 조정
- 시뮬레이션은 백그라운드로 실행되므로, 브라우저는 상태 조회 API를 통해 진행 상황을 확인합니다.

상세 플로우와 사용 방법은 [`README_dev.md`](README_dev.md)와 [`markdown/agent_simulation.md`](markdown/agent_simulation.md)에 정리되어 있습니다.

## 문서 모음

- [`README_dev.md`](README_dev.md): 운영/배포/데이터 시딩 전체 가이드
- [`markdown/search-pipeline.md`](markdown/search-pipeline.md): 검색 단계, 점수 산정, 응답 스키마
- [`markdown/session-bootstrap.md`](markdown/session-bootstrap.md): 세션 부팅/복구 절차
- [`markdown/text-only-ingest.md`](markdown/text-only-ingest.md): 텍스트 추가 적재 시나리오

## 라이선스

별도 고지 사항이 없는 한 회사 내부 용도로만 사용됩니다.
