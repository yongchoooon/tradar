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

## 검색 파이프라인 요약

이미지와 텍스트는 분리된 Top-K 리스트로 반환됩니다. 자세한 단계는 `markdown/search-pipeline.md`에 기록되어 있습니다.

### 이미지 흐름 (기본 N=100, K=10)
1. 입력 이미지를 MetaCLIP2/DINOv2로 임베딩
2. pgvector에서 각각 ANN Top-N 후보 검색
3. 각 후보에 대해 누락된 공간의 임베딩을 다시 읽어 코사인 유사도 계산
4. DINO:MetaCLIP 0.5:0.5 가중 평균으로 최종 이미지 점수 산출 (pgvector `<#>` 반환값은 음수 내적이므로 `VectorClient`가 부호를 반전해 사용)
5. Top-K를 선정하고 인접군/상태별로 그룹화

### 텍스트 흐름
1. 상표명 → TextVariantService → GPT-4o-mini 유사어 생성 (활성화 시)
2. 모든 용어를 MetaCLIP2 벡터로 가중 평균, pgvector ANN Top-N 검색
3. 용어를 공백으로 결합해 OpenSearch BM25 Top-N 검색
4. BM25 전용 후보는 텍스트 임베딩을 DB에서 읽어 코사인 유사도 계산 (동일하게 `<#>` 결과의 부호를 보정)
5. MetaCLIP 유사도만으로 Top-K를 선정 후 그룹화

### 응답 필드
- `image_top`, `text_top`: 각각 Top-K 리스트 (기본 20)
- `image_misc`, `text_misc`: Top-K 이외 후보 중 상태가 `등록`/`공고`가 아닌 항목(최대 10)
- `SearchResult`: `trademark_id`, `title`, `status`, `class_codes`, `app_no`, `image_sim`, `text_sim`, `thumb_url`
- `QueryInfo`: `k`, `text`, `goods_classes`, `group_codes`, `variants`

## 세션 부팅

- `scripts/bootstrap_seed.sh`: 신규 세션, 시스템 및 의존성 설치 + 데이터 시딩
- `scripts/bootstrap_session.sh`: 재개 세션, PostgreSQL 스냅샷 복원, OpenSearch 번들 확인, `sync_opensearch.sh` 실행
- 상세 절차는 `markdown/session-bootstrap.md` 참조

## 운영 팁

- **LLM 사용**: `.env`에 `OPENAI_API_KEY`, `TRADEMARK_LLM_ENABLED=true` 설정. 비용 로그는 `logs/openai_usage.csv`에 누적됩니다.
- **임베딩 모델 경로**: 기본값은 `/home/work/workspace/models/{metaclip,dinov2}`. 변경 시 `METACLIP_MODEL_NAME`, `DINOV2_MODEL_NAME` 환경변수를 사용하세요.
- **장비**: GPU가 없다면 `EMBED_DEVICE=cpu` 및 `BOOTSTRAP_*` 변수로 조정 가능합니다.
- **백엔드 선택**: FastAPI와 모든 시딩/부팅 스크립트는 Torch 백엔드를 기본 사용합니다. 더미(해시) 백엔드는 제거되었으며, 모델이 없을 경우 스크립트가 즉시 실패합니다.

## 개발 지침

1. **문서 우선**: 파이프라인 변경 시 `README_dev.md`, `markdown/search-pipeline.md`를 반드시 갱신합니다.
2. **테스트 데이터**: 더미 데이터나 OCR 샘플은 사용하지 않습니다. 실제 상표 데이터 기준으로 동작을 검증하세요.
3. **코드 스타일**: `python -m compileall`로 최소 문법 검사를 수행하고, 주요 변경점은 PR/커밋 메시지에 서술합니다.
4. **보안/비용**: OpenAI 키는 `.env` 등 비공개 파일에서만 관리하고, 사용 로그를 주기적으로 점검하세요.

## 참고 문서
- `markdown/search-pipeline.md`: 검색 단계, 점수 계산, 응답 예시
- `markdown/frontend.md`: 프런트엔드 구조와 API 연동 포맷
- `markdown/session-bootstrap.md`: KT Cloud 부팅/복구 체크리스트
