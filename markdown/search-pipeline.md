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
  - `image_prompt`: 이미지 재검색용 프롬프트(선택)
  - `image_prompt_mode`: 가중치 프리셋 (`primary_strong`·`primary_focus`·`balanced`·`prompt_focus`·`prompt_strong` → 90/10·70/30·50/50·30/70·10/90)
  - `text_prompt`: 텍스트 재검색용 프롬프트(선택)
  - `text_prompt_mode`: 텍스트 가중치 프리셋 (`primary_focus`·`balanced`·`prompt_focus`)
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
4. **프롬프트 가중치**
   - 프롬프트가 없을 때는 DINO:MetaCLIP = 0.5:0.5로 동일하게 가중합니다.
   - 프롬프트가 있으면 MetaCLIP 이미지 벡터와 텍스트 임베딩을 90/10, 70/30, 50/50, 30/70, 10/90 프리셋 중 선택한 값으로 보정하며, 최종 이미지 점수에서도 동일 비율이 적용됩니다.
5. **Top-K 선정**
   - 상위 K개 후보를 선택합니다. 인접군/비인접군 분리는 추후 `goods.is_adjacent` 로직을 사용해 확장할 예정이며, 현재는 단일 리스트로 반환됩니다.

## 텍스트 검색 흐름

1. **유사어 확장**
   - `TextVariantService`가 기본 변형 + GPT-4o-mini 유사어(활성화 시)를 생성합니다.
2. **프롬프트 해석**
   - 텍스트 프롬프트가 입력되면 `PromptInterpreter`가 OpenAI LLM을 사용해 추가 검색어·접두 조건·제외 토큰을 JSON 형태로 추출합니다. 오류나 비활성화 시 프롬프트 문장은 단순 추가 검색어로만 사용하고, 이 사실을 디버그 메시지에 기록합니다.
3. **쿼리 벡터 생성**
   - 원본 상표명은 가중치 1.0, 유사어는 0.8로 가중합하여 MetaCLIP2 텍스트 임베딩을 만듭니다.
   - 프롬프트 벡터는 90/10 · 70/30 · 50/50 · 30/70 · 10/90 프리셋에 따라 기존 텍스트 벡터와 가중 평균되어 새 질의를 형성합니다.
4. **ANN Top-N 검색 (기본 100)**
   - `text_embeddings_metaclip`에서 MetaCLIP 코사인 유사도 기준 Top-N 후보를 조회합니다.
5. **BM25 Top-N 검색**
   - 유사어와 원문을 공백으로 연결한 쿼리를 OpenSearch에 질의하여 Top-N 후보를 얻습니다.
   - ANN 결과에 없던 BM25 후보는 텍스트 임베딩을 DB에서 읽어 코사인 유사도를 계산하고, `<#>` 결과의 부호를 반전해 사용합니다.
6. **프롬프트 필터 적용**
   - LLM이 추출한 접두/포함/제외 규칙을 이용해 ANN 결과를 재정렬하며, 실패 시 해당 항목이 디버그 메시지로 노출됩니다.
7. **Top-K 선정**
   - MetaCLIP 유사도와 프롬프트 필터를 반영해 Top-K를 선택합니다. 선택한 상품 분류 기반의 인접/비인접 구분은 향후 버전에서 추가됩니다.
   - Top-K 밖의 후보 중 상태가 `등록`/`공고`가 아닌 항목은 "기타" 섹션에 별도로 노출됩니다.

## 프롬프트 재검색

- 이미지/텍스트 프롬프트는 독립적으로 적용되며, 모든 재검색은 pgvector ANN을 다시 호출해 전체 후보 공간을 탐색합니다.
- 임베딩은 SHA-256 키 기반 LRU 캐시(기본 128개)로 재사용하므로 동일한 이미지·문장에 대한 재검색은 인코딩 비용이 들지 않습니다.
- 디버그 모드에서는 사용된 가중치, 추가된 검색어, LLM 폴백 여부가 `debug.messages`에 텍스트로 수집됩니다.
- 재검색 요청에 `variants` 배열을 포함하면 기존 LLM 유사어를 그대로 재사용하며, 새롭게 생성하지 않고 프롬프트에서 추가된 항목만 확장합니다.

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
- `DebugInfo.messages`: 재검색 가중치, LLM 해석 결과, 폴백 여부 등 추가 메시지 배열

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
