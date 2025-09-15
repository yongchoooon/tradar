상표 유사도/위험도 서비스 코딩 가이드 (파이프라인 기준)
0) 기술 스택 제안

Backend: FastAPI + SQLAlchemy + Pydantic

Workers/Queue: Celery + Redis

DB: PostgreSQL + pgvector 확장

Search: OpenSearch(=Elastic 호환) for BM25, PGVector for ANN

Object Store: S3 호환(MinIO/AWS S3)

OCR/Detection/Embedding: PaddleOCR or EasyOCR, YOLOv8, ViT/CLIP, KoSentence-BERT

Model 서빙: onnxruntime-gpu

Container: Docker / docker-compose

Logging/Obs.: Prometheus + Grafana, OpenSearch Dashboards

1) 리포지토리 구조
repo/
  docker-compose.yml
  .env.example
  app/
    main.py
    api/
      __init__.py
      routes_search.py
      routes_ingest.py
      routes_admin.py
    core/
      config.py
      security.py
      logging.py
    models/               # SQLAlchemy ORM
      base.py
      trademark.py
      asset.py
      embedding.py
      decision.py
      registry.py
    schemas/              # Pydantic
      common.py
      search.py
      ingest.py
      admin.py
    services/
      ocr_service.py
      detect_service.py
      text_embed_service.py
      image_embed_service.py
      vienna_classifier.py
      bm25_client.py
      vector_client.py
      s3_client.py
      scoring.py
      highlight.py
    pipelines/
      ingest_pipeline.py
      search_pipeline.py
    workers/
      celery_app.py
      tasks.py
    search/
      opensearch_mapping.json
      queries.py
    registry/
      loader.py           # ONNX 모델 로더
    utils/
      image.py
      text.py
      id.py
  alembic/                # 마이그레이션
  tests/

2) Docker 구성 예시 (docker-compose.yml)

서비스: api, worker, postgres, opensearch, os-dash, minio, redis

Postgres에 pgvector 확장 설치

OpenSearch는 단일 노드 개발 모드

3) 데이터 스키마 (요지)
3.1 테이블

trademarks

id PK, title, class_code(e.g., "30류"), vienna_codes(int[]), status(live|expired|refused|withdrawn|pending), app_no, reg_no, owner, source, published_at, created_at

assets

id PK, trademark_id FK, image_url, pdf_url, thumb_url

embeddings

id PK, trademark_id FK, type(image|text), dim, vec vector

인덱스: USING ivfflat (vec vector_cosine_ops) WITH (lists=100)

decisions

id PK, trademark_id FK, type(rejection|office_action|accept), text, raw_url, created_at

risk_signals

id PK, trademark_id FK, reason(enum), weight, detail

model_registry

id PK, name, version, onnx_object_key, task(yolo|vit|text-embed|vienna-cls), meta(json), created_at

3.2 OpenSearch 인덱스

인덱스명: trademarks_text

필드: title(BM25), goods_services(BM25), decision_text(BM25), class_code(keyword), vienna_codes(keyword), status(keyword), trademark_id(keyword)

한국어 형태소 분석기 적용 가능하면 설정

4) 모델 로딩 및 서비스 인터페이스
# registry/loader.py
class ModelHandle:
    def __init__(self, s3, name, version): ...
    def session(self):  # onnxruntime.InferenceSession 반환
        ...

# services/text_embed_service.py
class TextEmbedder:
    def __init__(self, onnx_session): ...
    def encode(self, text:str) -> np.ndarray: ...

# services/image_embed_service.py
class ImageEmbedder:
    def __init__(self, onnx_session): ...
    def encode(self, image:np.ndarray) -> np.ndarray: ...

# services/detect_service.py (YOLO)
# services/ocr_service.py (PaddleOCR)
# services/vienna_classifier.py (ONNX 분류기)

5) 인입 파이프라인 (Ingest)

업로드: 이미지/거절결정서 PDF/S3 키 수신 → S3 저장

OCR: 표면 텍스트 추출 → normalize(text) 소문자, 자모 분리/공백 정리

Detection: YOLO로 마크/로고 바운딩박스 → 크롭 이미지 생성

Embedding 생성

Text: title, OCR text → TextEmbedder.encode

Image: 원본 또는 크롭 → ImageEmbedder.encode

분류/메타

Vienna 코드 예측, 상태/분류 메타 바인딩

저장

trademarks, assets, embeddings insert

색인

OpenSearch: title, goods_services, decision_text 색인

PGVector: embeddings.vec upsert

비동기 처리

2–7단계는 Celery task로 분리 (tasks.ingest_trademark)

# pipelines/ingest_pipeline.py (요지)
def run_ingest(input: IngestInput) -> str:
    tid = upsert_trademark_meta(...)
    img = load_image(input.image_path)
    ocr = ocr_service.run(img)
    norm_txt = normalize(ocr.text)
    t_vec = text_embed.encode(norm_txt)
    i_vec = image_embed.encode(img)
    vienna = vienna_cls.predict(img)
    save_all(tid, ..., t_vec, i_vec, vienna)
    os_client.index_text(tid, title=..., goods_services=..., decision_text=...)
    vec_client.upsert(tid, "text", t_vec)
    vec_client.upsert(tid, "image", i_vec)
    return tid

6) 검색 파이프라인 (Retrieval + Rerank)

입력: query_text, query_image, filters: {class_code, vienna_codes, status}

전처리

텍스트 normalize

이미지 있으면 임베딩 생성

1차 검색 (병렬)

ANN(Vector)

text_vec로 텍스트 임베딩 Top-N

image_vec로 이미지 임베딩 Top-N

BM25(Text)

OpenSearch로 title, goods_services, decision_text Top-N

필터링/중복제거

동일 업체/출원번호 중복 제거

메타 필터: 동일 업종(분류), Vienna 코드 포함/불일치 감점, 상태 스코어링

재계산/가중합 스코어

유사도 계산

이미지 코사인 s_i

텍스트 코사인 s_t

상품/서비스류 겹침 s_c (Jaccard, 편집거리 보정)

행정/거절 신호 s_r (거절유사 근거, 진행상태)

최종 스코어 S = 0.5*s_i + 0.25*s_t + 0.15*s_c + 0.1*s_r

상세정보 결합

메타 RDB + OS에서 거절사유 본문 GET

Top-K 선택 및 하이라이트

매칭 근거, 핵심 서지, 위험도 라벨링

# services/scoring.py
def final_score(si, st, sc, sr):
    return 0.5*si + 0.25*st + 0.15*sc + 0.10*sr

# pipelines/search_pipeline.py (요지)
def search(query: SearchInput) -> SearchOutput:
    tvec = text_embed.encode(normalize(query.text)) if query.text else None
    ivec = image_embed.encode(query.image) if query.image else None

    cand_vec_t = vec_client.search("text", tvec, topn=200) if tvec is not None else []
    cand_vec_i = vec_client.search("image", ivec, topn=200) if ivec is not None else []
    cand_bm25  = os_client.search(query.text, topn=200) if query.text else []

    merged = merge_dedupe([cand_vec_t, cand_vec_i, cand_bm25])
    filtered = apply_filters(merged, query.filters)   # class_code, vienna, status
    rescored = []
    for c in filtered:
        si = cosine(ivec, c.image_vec) if ivec is not None and c.image_vec is not None else 0
        st = cosine(tvec, c.text_vec)  if tvec  is not None and c.text_vec  is not None else 0
        sc = jaccard(query.goods_set, c.goods_set) if query.goods_set else approx_goods_overlap(query.text, c.goods_services)
        sr = admin_reject_signal(c.decision_text, c.status)
        S  = final_score(si, st, sc, sr)
        rescored.append((c, S))
    topk = take_topk(rescored, k=query.k)
    return decorate_with_explanations(topk)

7) API 설계
7.1 검색

POST /search/trademark

Body:

{
  "text": "STARBUCKS 30류 커피",
  "image_b64": "...", 
  "class_code": "30",
  "vienna_codes": [0502],
  "status_in": ["live","pending"],
  "k": 20
}


Response:

{
  "query": {...},
  "results": [
    {
      "trademark_id": "T2024-0001",
      "title": "STARBUCKS",
      "class_code": "30",
      "vienna_codes": [502],
      "status": "live",
      "scores": {"image":0.77,"text":0.69,"class_overlap":0.80,"admin_signal":0.35,"final":0.66},
      "evidence": {
        "highlights": {"title":["starbucks"], "decision_text":["혼동 우려"]},
        "goods_overlap": ["커피","차","설탕"]
      },
      "assets": {"image_url":"s3://.../img.jpg"}
    }
  ]
}

7.2 인입/색인

POST /ingest/trademark — 이미지/메타 업로드 → task_id 반환

GET /ingest/status/{task_id} — 파이프라인 진행률

7.3 어드민

POST /admin/models/register — ONNX S3 업로드, 레지스트리 등록

POST /admin/reindex — 특정 trademark 재색인

8) 서비스 컴포넌트 구현 체크리스트

 S3 클라이언트 래퍼 (pre-signed URL 발급)

 OpenSearch 클라이언트 및 인덱스 관리(mappings, analyzers)

 PGVector 연결 및 ANN 인덱스 생성 (ivfflat, cosine)

 OCR/YOLO/임베딩 ONNX 세션 초기화 모듈

 텍스트 정규화: 소문자, 자모/공백/특수문자 규칙, 영문 오타 교정 옵션

 Vienna 코드 분류기 호출 및 신뢰도 임계값

 상품/서비스류 토큰화 및 Jaccard 계산기

 행정/거절 신호 스코어러 (sr): 상태 가중치 + 거절사유 패턴 매칭

 후보 병합/중복 제거 로직 (동일 출원·등록번호 우선 규칙)

 최종 랭킹, Top-K 슬라이스, 근거 하이라이트 생성

 에러/시간 초과 처리, 재시도, 서킷브레이커

 감사 로그: 입력/출력 요약, 모델 버전, 스코어 구성 요소

9) 점수 설계 상세

s_i: 임베딩 코사인. 이미지가 없으면 0

s_t: 임베딩 코사인. 텍스트가 없으면 0

s_c: 상품/서비스 겹침. Jaccard(goods_query, goods_target) 또는 텍스트기반 추정

s_r: 행정/거절 신호

상태 가중: live:+0.3, pending:+0.2, refused:-0.2, withdrawn:-0.3, expired:-0.3

거절사유 텍스트 규칙: “혼동 우려”, “식별력 부족”, “기만”, “저명표장” 등 키워드에 따라 ± 가중

최종: S = 0.5*s_i + 0.25*s_t + 0.15*s_c + 0.10*s_r

10) 하이라이트/설명 생성

OpenSearch highlight 기능으로 title, decision_text 강조

유사도 근거: 상위 top tokens, 가장 가까운 이미지 패치 유사도(선택)

11) 배치 동기화 (옵션)

KIPRIS/공공데이터포털 덤프 → S3 적재 → ingest_trademark 일괄 실행

스케줄러(Crontab/Celery beat)로 주간 업데이트

12) 보안/권한

API Key 또는 OAuth2 Client Credentials

업로드 URL은 pre-signed, 10분 만료

PII/민감 데이터 로그 금지, 샘플링 로깅

13) 테스트 전략

단위: 정규화, 임베딩 차원/범위, 스코어 함수

통합: 소형 픽스처 DB/OS/PGVector로 end-to-end

회귀: 모델 버전 변경 시 스코어 분포 비교

14) 실행 순서 (개발용 스크립트)

docker compose up -d

alembic upgrade head

python -m app.registry.loader --warm_all # ONNX 예열

uvicorn app.main:app --reload

OpenSearch 인덱스 생성: python scripts/create_index.py

샘플 인입: python scripts/ingest_sample.py

검색 호출: curl -X POST http://localhost:8000/search/trademark ...

15) 프런트엔드 연동 포맷 (Vue 예시)

업로드 후 반환된 pre-signed URL로 이미지 PUT

/search/trademark 결과 카드:

썸네일, 최종 스코어, 분류/상태 배지

핵심 서지(출원/등록번호, 상태, 날짜, Vienna)

위험도 라벨과 근거 문장

16) MVP 범위 제안

텍스트 쿼리 + 이미지 쿼리 동시 지원

Top-K 결과와 근거, 간단 위험도 배지

배치 인입은 CSV + 이미지 폴더 기준

17) 코드 조각 모음
FastAPI 엔드포인트 요지
# app/api/routes_search.py
@router.post("/search/trademark", response_model=SearchResponse)
def search_trademark(req: SearchRequest):
    out = search_pipeline.search(req)
    return out

OpenSearch 질의 예
def os_search(text, topn=200, filters=None):
    must = [{"multi_match": {"query": text, "fields": ["title^2","goods_services","decision_text"]}}]
    if filters and filters.class_code:
        must.append({"term": {"class_code": filters.class_code}})
    return client.search(index="trademarks_text",
                         body={"size": topn, "query":{"bool":{"must":must}},
                               "highlight":{"fields":{"title":{},"decision_text":{}}}})

PGVector 검색 예
def vec_search(kind, vec, topn=200):
    sql = text("""
      SELECT trademark_id, 1 - (vec <=> :q) AS score
      FROM embeddings
      WHERE type = :kind
      ORDER BY vec <=> :q
      LIMIT :k
    """)
    return session.execute(sql, {"q": vec.tolist(), "kind": kind, "k": topn}).fetchall()

18) 성능 팁

pgvector lists 튜닝, ANALYZE, VACUUM 주기화

OpenSearch shard=1, replica=0 개발 설정, 프로덕션은 분리

임베딩 배치 계산 시 GPU 전용 워커 분리