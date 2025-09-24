# 검색 파이프라인 문서

## 파일 위치
- `app/pipelines/search_pipeline.py`
- 보조 서비스: `app/services/vector_client.py`, `bm25_client.py`, `image_embed_service.py`, `text_embed_service.py`, `ocr_service.py`

## 입력 스키마
- `SearchRequest`
  - `image_b64`: 업로드 이미지 (필수)
  - `boxes`: 바운딩 박스 리스트 (선택) → 서버에서 최대 2개 크롭 생성
  - `text`: 상표명 텍스트. 사용자가 입력한 문자열을 OCR 결과와 결합해 벡터화
  - `goods_classes`, `group_codes`: 선택한 류/유사군 (향후 재랭킹 또는 보고용)
  - `k`: Top-K (현재 UI에서 20 고정)

## 파이프라인 단계
1. **이미지 준비**: 원본 + 최대 2개의 크롭 → `ImageEmbedder` 로 임베딩
2. **텍스트 구성**: 사용자가 입력한 상표명 + OCR 텍스트 → `TextEmbedder`, BM25 검색에 사용
3. **1차 검색**
   - 이미지 임베딩 → VectorClient (코사인 유사도 기반) 결과
   - 텍스트 임베딩 → VectorClient (텍스트 공간)
   - BM25 → BM25Client (단순 토큰 카운트 기반 점수)
4. **스코어 병합**: `merge_hits`
   - 이미지/텍스트/BM25 결과를 상표 ID 기준으로 통합
   - 텍스트 score 는 ANN vs BM25 중 최대값 사용
5. **Top-K 추출**: 이미지/텍스트 기준 각각 상위 K개 ID 선정
6. **메타데이터 조인**: `catalog.bulk_by_ids` 로 상표 상세 정보를 가져오고, goods TSV 기반 인접군 계산
7. **응답 구조**: `SearchResponse`
   - `query`: 요청 요약 (`k`, `boxes`, `text`, `goods_classes`, `group_codes`)
   - `image_topk`, `text_topk`: `SearchGroups` 구조 (인접군/비인접군/등록/거절/기타)

## 모의 서비스 구현
- 현재 Vector/BM25/Embedding/OCR 은 해시 기반 toy 구현으로 실제 모델 없이 동작
- 향후 실제 검색엔진/모델로 교체 시 인터페이스 유지하면서 내부 구현만 교체하면 됨

## 테스트 노트
- `tests/test_search_pipeline.py` 에서 기본 동작 검증 (선택된 유사군/박스 수, 인접군 분류)
- 로컬에서 pytest 사용 시 `pytest` 설치 필요. 현재 환경에는 포함되어 있지 않음

## 업데이트 가이드
- 새로운 스코어링 요소 추가 시 `merge_hits` 와 `SearchResult` 필드 문서화
- 응답 구조 변경 시 `markdown/frontend.md` 및 프론트 상태 흐름도 함께 수정
- 실제 서비스 연결 후에는 벡터/BM25 클라이언트, 임베딩 서비스에 대한 별도 문서를 추가 권장
