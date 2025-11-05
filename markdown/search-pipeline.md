# 검색 파이프라인

이 문서는 `/search/multimodal` 엔드포인트에서 수행되는 단계별 로직을 설명합니다. 구현은 `app/pipelines/search_pipeline.py`에 있으며, 아래 구성요소들과 연동됩니다.

- `app/services/image_embed_service.py`: MetaCLIP2 + DINOv2 임베딩
- `app/services/text_embed_service.py`: MetaCLIP2 텍스트 임베딩
- `app/services/text_variant_service.py`: LLM 기반 유사어 생성
- `app/services/vector_client.py`: pgvector ANN 검색
- `app/services/bm25_client.py`: OpenSearch BM25
- `app/services/catalog.py`: 상표 메타데이터 조회

## 요청 스키마

- `SearchRequest`
  - `image_b64` (필수): 업로드된 상표 이미지
  - `text` (선택): 사용자가 입력한 상표명
  - `goods_classes`, `group_codes`: 선택된 서비스류/유사군 (향후 인접군/비인접군 구분에 활용 예정)
  - `k`: 반환할 Top-K (기본 20)
  - `debug`: 디버그 세부정보를 포함할지 여부 (기본 비활성)

`QueryInfo`에는 요청에 사용된 텍스트, 유사어 목록, 선택한 분류 정보가 반영됩니다. `goods_classes`/`group_codes`는 현재 응답에 그대로 포함되며, 차후 인접군 표시 로직에 활용될 예정입니다.

## 이미지 검색 흐름

1. **임베딩 생성**
   - 입력 이미지를 MetaCLIP2, DINOv2 두 공간으로 임베딩합니다.
2. **ANN Top-N 검색 (기본 100)**
   - `image_embeddings_dino`에서 pgvector `<#>` 연산(inner product의 음수)을 이용해 오름차순 Top-N 후보를 조회하고, `VectorClient`가 부호를 반전해 코사인 값으로 사용합니다.
   - `image_embeddings_metaclip`에서도 동일한 방식으로 후보를 수집합니다.
3. **보조 점수 채우기**
   - DINO 후보 중 MetaCLIP 점수가 없는 항목은 `image_embeddings_metaclip`에서 벡터를 읽어 코사인 유사도 계산
   - MetaCLIP 후보의 DINO 점수도 동일 방식으로 보완
4. **스코어 블렌딩**
   - DINO:MetaCLIP = 0.5:0.5 가중 평균 (위 단계에서 보정된 raw 코사인 값을 사용)
5. **Top-K 선정**
   - 상위 K개 후보를 선택합니다. 인접군/비인접군 분리는 추후 `goods.is_adjacent` 로직을 사용해 확장할 예정이며, 현재는 단일 리스트로 반환됩니다.

## 텍스트 검색 흐름

1. **유사어 확장**
   - `TextVariantService`가 기본 변형 + GPT-4o-mini 유사어(활성화 시)를 생성합니다.
2. **쿼리 벡터 생성**
   - 원본 상표명은 가중치 1.0, 유사어는 0.8로 가중합하여 MetaCLIP2 텍스트 임베딩을 만듭니다.
3. **ANN Top-N 검색 (기본 100)**
   - `text_embeddings_metaclip`에서 MetaCLIP 코사인 유사도 기준 Top-N 후보를 조회합니다.
4. **BM25 Top-N 검색**
   - 유사어와 원문을 공백으로 연결한 쿼리를 OpenSearch에 질의하여 Top-N 후보를 얻습니다.
   - ANN 결과에 없던 BM25 후보는 텍스트 임베딩을 DB에서 읽어 코사인 유사도를 계산하고, `<#>` 결과의 부호를 반전해 사용합니다.
5. **Top-K 선정**
   - MetaCLIP 유사도만으로 정렬하여 Top-K를 선택합니다. 선택한 상품 분류 기반의 인접/비인접 구분은 향후 버전에서 추가됩니다.
   - Top-K 밖의 후보 중 상태가 `등록`/`공고`가 아닌 항목은 "기타" 섹션에 별도로 노출합니다.

## 응답 구조

`SearchResponse`
- `query`: 요청 요약 (`k`, 입력 텍스트, 선택한 류/유사군, 생성된 유사어)
- `image_top`: 이미지 Top-K 후보 리스트
- `image_misc`: Top-K 이외의 후보 중 상태가 등록/공고가 아닌 항목 (최대 10개, 등록/공고만 정상 상태로 간주)
- `text_top`: 텍스트 Top-K 후보 리스트
- `text_misc`: 텍스트 후보 중 등록/공고 외 상태 (최대 10개, 등록/공고만 정상 상태로 간주)
- `SearchResult`: 상표별 메타데이터와 점수
  - `trademark_id`, `app_no`: DB의 `application_number`
  - `title`: 한글/영문 제목 중 우선값
  - `image_sim`, `text_sim`: 각각 블렌딩된 이미지 점수, MetaCLIP 텍스트 점수
  - `thumb_url`: `/media?path=...` 형태의 썸네일 경로 또는 원본 URL
  - `doi`: 연계 문서가 있는 경우 DOI 링크

## 연동 서비스 요약

| 서비스 | 모듈 | 주요 환경 변수 |
| ------ | ---- | --------------- |
| PostgreSQL + pgvector | `app/services/db.py`, `vector_client.py`, `catalog.py` | `DATABASE_URL` |
| OpenSearch | `app/services/bm25_client.py` | `OPENSEARCH_URL`, `OPENSEARCH_INDEX`, `OPENSEARCH_SEARCH_FIELDS` |
| OpenAI GPT-4o-mini | `app/services/synonym_service.py` | `OPENAI_API_KEY`, `TRADEMARK_LLM_ENABLED` |

## 업데이트 가이드

- 점수 가중치나 Top-N 값을 변경할 때는 이 문서와 `README_dev.md`를 동시 수정합니다.
- 신규 스코어를 추가하면 `SearchResult` 필드, 프런트엔드(`markdown/frontend.md`), 로그 포맷을 함께 갱신하세요.
- BM25 또는 pgvector 구성을 변경하면 `scripts/sync_opensearch.sh`, `scripts/vector_db_prepare*.py` 문서도 확인하세요.
