# T-RADAR

T-RADAR은 상표 이미지·텍스트를 동시에 활용해 유사 상표를 찾고, 상품/서비스류 정보를 함께 제시하는 검색 시스템입니다. 저장소에는 다음과 같은 컴포넌트가 포함됩니다.

- PostgreSQL + pgvector 기반 멀티모달 벡터 저장소
- OpenSearch 기반 BM25 텍스트 검색
- MetaCLIP2 / DINOv2 임베딩을 사용하는 검색 파이프라인
- FastAPI 백엔드 + React 프런트엔드
- KT Cloud 세션 재개를 위한 부팅/복구 스크립트

자세한 개발 가이드는 `README_dev.md`와 `markdown/` 디렉터리를 참고하세요.

## 빠른 시작

### 1. 최초 부팅/시딩
```bash
bash scripts/bootstrap_seed.sh \
  /path/to/trademarks.json \
  /path/to/images
```
- PostgreSQL/pgvector, OpenSearch 설치 및 기동
- `requirements.txt` 설치
- `scripts/vector_db_prepare.py`로 이미지·텍스트 임베딩 시딩
- `trademarks.json`/이미지 경로를 생략하면 기본값으로 `data/trademarks.json`, `data/images/`를 사용합니다.
- `scripts/sync_opensearch.sh`로 BM25 인덱스 동기화 (벡터 시딩 이후 즉시 실행)

### 2. 세션 재개
```bash
bash scripts/bootstrap_session.sh
```
- PostgreSQL 서비스 및 스냅샷 복원
- OpenSearch 번들 확인 및 데이터 디렉터리 마운트
- 요구 파이썬 패키지 점검, BM25 인덱스 동기화

### 3. API 실행
```bash
bash scripts/run_api.sh
```
- `.env`가 있다면 자동으로 로드합니다.
- 기본 설정은 Torch 백엔드(`IMAGE/TEXT_EMBED_BACKEND=torch`), `METACLIP_MODEL_NAME`/`DINOV2_MODEL_NAME` 경로, `EMBED_DEVICE=cuda:0`를 사용합니다. 해시 기반 더미 백엔드는 제거되었습니다.
- pgvector 검색은 inner product 연산(`<#>`)을 사용하므로, 실제 코사인과 동일한 값이 필요할 때는 결과에 음수를 곱한 후 사용합니다. (`VectorClient`가 이를 자동으로 처리합니다.)
- `DATABASE_URL`, `OPENSEARCH_URL`, `OPENAI_API_KEY` 등은 필요에 맞게 override 하십시오.

### 4. 프런트엔드 확인
프런트엔드는 API와 동일 포트에서 서빙되며, `http://localhost:8000`으로 접속하면 상표 검색 UI를 사용할 수 있습니다.
- 결과 리스트 하단의 프롬프트 입력창에서 이미지/텍스트 재검색을 실행할 수 있으며, "최우선"/"우선"/"균형"/"프롬프트 우선"(90/10 · 70/30 · 50/50 · 30/70 · 10/90) 가중치 프리셋을 선택해 질의를 보정할 수 있습니다.

## 문서

- [`README_dev.md`](README_dev.md): 전체 아키텍처, 데이터 시딩, 검색 파이프라인 상세
- [`markdown/search-pipeline.md`](markdown/search-pipeline.md): 이미지/텍스트 검색 단계, 점수 산정, 응답 구조
- [`markdown/session-bootstrap.md`](markdown/session-bootstrap.md): KT Cloud 세션 부팅/복구 시나리오
- [`markdown/text-only-ingest.md`](markdown/text-only-ingest.md): 텍스트 임베딩만 추가로 적재할 때 사용

## 기여
1. 변경 전 관련 문서를 확인하고, 수정 시 문서도 함께 갱신합니다.
2. 기능별 테스트 데이터는 실제 상표 데이터를 기준으로 하며, 더미 데이터나 OCR 예제는 사용하지 않습니다.
3. Pull Request에는 실행한 스크립트와 검증 방법을 명시해 주세요.

## 라이선스
프로젝트 내 소스코드와 모델은 별도의 고지 사항이 없는 한 회사 내부 용도로만 사용됩니다.
