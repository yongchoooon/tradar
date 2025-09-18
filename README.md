# 상표 유사도 검색 서비스 코딩 가이드 v2 (개정 파이프라인)

> 목표: **이미지 전체** 또는 **사용자 지정 영역(바운딩 박스)** 기반으로 비주얼/텍스트 유사 상표를 검색하고, 이미지와 텍스트 각각에 대해 **별도 Top-K** 결과를 반환한다. 초기 메타 필터링 없이 **전체 DB**에서 1차 검색 후 중복 제거 및 재랭킹을 수행한다.

---

## 개요
- 입력: 단일 상표 이미지(Base64) + 선택적 바운딩 박스 + 상품/서비스류 코드
- 처리: 서버가 원본/크롭 이미지를 생성하고 이미지/텍스트 임베딩으로 전체 상표 DB에서 후보를 검색
- 출력: 이미지 유사 Top-K, 텍스트 유사 Top-K를 각각 반환하고 상태값(등록/거절 등)과 인접군 여부로 그룹핑
- 운영: FastAPI 기반 마이크로서비스 + Celery 비동기 작업 + PostgreSQL/pgvector + OpenSearch 조합

## 핵심 변경 사항 (v2)
- [변경] 초기 메타 필터링 없이 **전체 DB**에서 1차 검색 수행
- [추가] 바운딩 박스 업로드 시 서버가 **원본 1 + 크롭 N**까지 최대 3장의 쿼리 이미지 생성
- [단순화] 재랭킹은 **이미지 유사도**와 **텍스트 유사도**만 사용
- [출력] 이미지 Top-K, 텍스트 Top-K를 **분리**하여 반환하고 상태값, 인접군 여부에 따라 섹션을 나눔

## 시스템 구성

### 기술 스택 요약
- **Backend**: FastAPI + SQLAlchemy + Pydantic
- **Workers/Queue**: Celery + Redis (대용량 임베딩 처리)
- **DB**: PostgreSQL + `pgvector`
- **Search**: OpenSearch(BM25), PGVector(ANN)
- **Object Store**: S3 호환(MinIO/AWS S3)
- **Models(ONNX)**: YOLOv8(선택), ViT/CLIP(이미지 임베딩), KoSentence-BERT(텍스트 임베딩), OCR(PaddleOCR)
- **Model Serving**: onnxruntime-gpu
- **Frontend(선택)**: React + Konva 또는 `react-image-annotate`로 박스 드로잉
- **Container**: Docker / docker-compose

### 모델 및 서빙 전략
- ViT 학습은 **Vienna 중분류 멀티레이블** 기반을 계획하고 검색은 코사인 유사도를 사용
- 모델 레지스트리 테이블에 `name, version, task, onnx_key, dim`을 저장하고 onnxruntime-gpu 세션을 캐싱하여 배포

---

## 엔드-투-엔드 파이프라인

### 1. 요청 엔드포인트
`POST /search/multimodal`
```json
{
  "image_b64": "<base64>",
  "boxes": [
    {"x1":0.02,"y1":0.05,"x2":0.40,"y2":0.92},
    {"x1":0.45,"y1":0.18,"x2":0.98,"y2":0.82}
  ],
  "goods_classes": ["30","43"],
  "k": 20
}
```

### 2. 입력 전처리
1. 바운딩 박스 좌표 검증(0~1 정규화 또는 px → 정규화)
2. 원본 이미지에서 박스 별 **서버 측 크롭** 생성
3. **쿼리 이미지 셋 = {원본} ∪ {크롭들}** (최대 3장)

```python
from PIL import Image

def crop_from_boxes(img: Image.Image, boxes):
    W, H = img.size
    crops = []
    for b in boxes:
        x1, y1, x2, y2 = denorm(b, W, H)
        crops.append(img.crop((x1, y1, x2, y2)))
    return crops

def make_query_images(img_bytes: bytes, boxes: list[dict]) -> list[Image.Image]:
    img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    crops = crop_from_boxes(img, boxes or [])
    return [img] + crops[:2]  # 최대 3장
```

### 3. 임베딩 생성
- 이미지: 각 쿼리 이미지 → ViT/CLIP ONNX → L2 정규화 벡터
- 텍스트: OCR(원본 + 크롭) → 정규화 → KoSBERT ONNX → 벡터
- BM25 질의 텍스트: OCR 결과를 결합해 구성

```python
def encode_images(images):
    return [vit.encode(img) for img in images]

def encode_texts(texts):
    return text_model.encode(" ".join(texts))
```

### 4. 전체 DB 1차 검색
- **Visual ANN**: 각 쿼리 이미지 임베딩으로 PGVector `LIMIT N0`
  - 여러 크롭 결과는 **trademark_id** 기준으로 병합하고 `image_sim_raw = max(sim)`을 사용
- **Text ANN**: 텍스트 임베딩으로 PGVector `LIMIT N0`
- **BM25**: OpenSearch로 `title, goods_services, decision_text` 검색 `LIMIT N0`

```sql
SELECT trademark_id, 1 - (vec <=> :q) AS sim
FROM embeddings
WHERE type = 'image'
ORDER BY vec <=> :q
LIMIT :N0;
```

### 5. 후보 병합 및 스코어 집계
- 세 소스 결과를 **trademark_id**로 병합하여 후보 맵 생성
- `image_sim = max(sim_i over all query crops)`
- `text_sim_vec = max(sim from text ANN)`
- `text_sim_bm25 = normalize(bm25_score)` → 0~1 스케일
- `text_sim = max(text_sim_vec, text_sim_bm25)`

```python
from collections import defaultdict

def bm25_norm(score, min_s, max_s):
    if max_s == min_s:
        return 0.0
    return (score - min_s) / (max_s - min_s)

def merge_hits(img_hits_list, txt_hits, bm25_hits):
    cand = defaultdict(lambda: {'image_sim': 0.0,
                                'text_sim_vec': 0.0,
                                'text_sim_bm25': 0.0})
    for hits in img_hits_list:
        for h in hits:
            cand[h.id]['image_sim'] = max(cand[h.id]['image_sim'], h.sim)
    for h in txt_hits:
        cand[h.id]['text_sim_vec'] = max(cand[h.id]['text_sim_vec'], h.sim)
    min_s = min((h['score'] for h in bm25_hits), default=0.0)
    max_s = max((h['score'] for h in bm25_hits), default=1.0)
    for h in bm25_hits:
        cand[h['id']]['text_sim_bm25'] = max(
            cand[h['id']]['text_sim_bm25'],
            bm25_norm(h['score'], min_s, max_s),
        )
    for v in cand.values():
        v['text_sim'] = max(v['text_sim_vec'], v['text_sim_bm25'])
    return cand
```

### 6. Top-K 산출 및 응답 구성
- `topk_by(candidates, key, k)`로 이미지/텍스트 Top-K 각각 계산
- 메타데이터를 조회한 뒤 상태값(registered/refused/others)과 인접군 여부로 그룹핑
- 반환 JSON은 이미지/텍스트 Top-K를 분리하고 각 섹션에서 상태/인접군 기준 정렬

```python
def topk_by(cand_map, key, k):
    ids = sorted(cand_map.keys(), key=lambda i: cand_map[i][key], reverse=True)
    return ids[:k]
```

```json
{
  "query": {"k": 20, "boxes": 2, "goods_classes": ["30","43"]},
  "image_topk": {
    "adjacent": [ { "id": "T1", "title": "STARBUCKS", "status": "registered",
      "class_codes": ["30"], "app_no": "...", "image_sim": 0.83, "text_sim": 0.61, "thumb": "..." } ],
    "non_adjacent": [ ... ],
    "refused": [ ... ],
    "registered": [ ... ]
  },
  "text_topk": {
    "adjacent": [ ... ],
    "non_adjacent": [ ... ],
    "refused": [ ... ],
    "registered": [ ... ]
  }
}
```

프런트엔드는 썸네일, 상표명, 상태, 클래스, 출원번호, `image_sim`, `text_sim`을 카드 형태로 노출하고, 클릭 시 상세 패널에서 서지/거절사유/Vienna 코드/추가 이미지를 보여준다.

---

## 메타데이터 조인 및 인접군 판정

### 핵심 테이블 조인
- `trademarks(id, title, status, class_codes, vienna_codes, app_no, reg_no, owner, dates…)`
- `assets(id, trademark_id, thumb_url)`
- 필요 시 `decisions(type, text)` 조인하여 거절 사유 요약 제공

### 상품/서비스 인접군
- 파일 경로: `app/data/goods_services/ko_goods_services.tsv`
  - 컬럼: `nc_class, name_ko, similar_group_code`
- 로딩 후 딕셔너리 캐싱, `similar_group_code`가 겹치면 인접군으로 간주

```python
def load_goods_groups(tsv_path):
    import csv
    mapping, groups = {}, {}
    with open(tsv_path, newline='', encoding='utf-8') as f:
        for nc, name, grp in csv.reader(f, delimiter='\t'):
            mapping[nc] = {'name': name, 'group': grp}
            groups.setdefault(grp, set()).add(nc)
    return mapping, groups

def is_adjacent(user_classes, target_classes, meta):
    user_groups = {meta[c]['group'] for c in user_classes if c in meta}
    target_groups = {meta[c]['group'] for c in target_classes if c in meta}
    return len(user_groups & target_groups) > 0

def group_by_status_and_goods(ids, meta, user_classes, goods_meta):
    groups = {'registered': [], 'refused': [], 'others': [],
              'adjacent': [], 'non_adjacent': []}
    for i in ids:
        m = meta[i]
        if m['status'] == 'registered':
            groups['registered'].append(i)
        elif m['status'] == 'refused':
            groups['refused'].append(i)
        else:
            groups['others'].append(i)
        bucket = 'adjacent' if is_adjacent(user_classes, m['class_codes'], goods_meta) else 'non_adjacent'
        groups[bucket].append(i)
    return groups
```

---

## 구현 스켈레톤

```python
@router.post('/search/multimodal', response_model=SearchResponse)
def search_multimodal(req: SearchRequest):
    imgs = make_query_images(base64.b64decode(req.image_b64), req.boxes or [])
    img_vecs = [img_embed.encode(im) for im in imgs]
    ocr_texts = [ocr.run(im).text for im in imgs]
    t_vec = text_embed.encode(' '.join(clean(t) for t in ocr_texts))
    bm25_q = ' '.join(ocr_texts)

    img_hits_list = [ann_search('image', v, topn=200) for v in img_vecs]
    txt_hits = ann_search('text', t_vec, topn=200)
    bm25_hits = os_client.search(bm25_q, topn=200)

    cand = merge_hits(img_hits_list, txt_hits, bm25_hits)
    topk_img_ids = topk_by(cand, 'image_sim', req.k)
    topk_txt_ids = topk_by(cand, 'text_sim', req.k)

    meta = fetch_meta(topk_img_ids + topk_txt_ids)
    goods_meta, _ = load_goods_groups(TSV_PATH)

    img_groups = group_by_status_and_goods(topk_img_ids, meta, req.goods_classes, goods_meta)
    txt_groups = group_by_status_and_goods(topk_txt_ids, meta, req.goods_classes, goods_meta)

    return build_response(req, cand, meta, img_groups, txt_groups)
```

```python
def ann_search(kind: str, vec: np.ndarray, topn: int) -> list[Hit]:
    sql = text('''
      SELECT trademark_id, 1 - (vec <=> :q) AS sim
      FROM embeddings
      WHERE type = :kind
      ORDER BY vec <=> :q
      LIMIT :k
    ''')
    return [Hit(*row) for row in session.execute(sql, {'q': vec.tolist(), 'kind': kind, 'k': topn})]
```

---

## DB 스키마 개요
- `trademarks(id PK, title, status, class_codes text[], vienna_codes int[], app_no, reg_no, owner, source, published_at, created_at)`
- `assets(id PK, trademark_id FK, image_url, thumb_url)`
- `embeddings(id PK, trademark_id FK, type enum(image|text), dim int, vec vector)`
  - 인덱스: `USING ivfflat (vec vector_cosine_ops) WITH (lists=100)`
- `decisions(id PK, trademark_id FK, type enum(rejection|office_action|accept), text, created_at)`
- `model_registry(id PK, name, version, onnx_object_key, task, dim, meta jsonb)`
- `goods_groups(nc_class text PK, name_ko text, similar_group_code text)` ← TSV 로드 소스

---

## 프런트엔드 요구 사항
- 원본 업로드 → **전체 검색** 또는 **영역 검색** 라디오 선택
- 영역 검색 시 박스 드로잉 UI, 좌표를 정규화하여 전송
- 결과 화면 구성
  - 탭 1: **이미지 유사 Top-K**
  - 탭 2: **텍스트 유사 Top-K**
  - 각 탭에 **등록/거절** 섹션 분리
  - 각 섹션에 **인접군/비인접군** 카드 리스트
  - 카드 항목: 썸네일, 상표명, 상태, 클래스, 출원번호, `image_sim`, `text_sim`
  - 카드 클릭 → 상세 모달

---

## 체크리스트
- [ ] 바운딩 박스 서버 크롭 정확도 검증(px/정규화 혼용 처리)
- [ ] OCR 품질 튜닝 및 글자 정규화
- [ ] 임베딩 차원/정규화 일관성
- [ ] BM25 스코어 정규화 방식 확정(분포 기반)
- [ ] ANN topn, dedupe 정책, 동률 처리
- [ ] 상태값 도메인 표준화
- [ ] TSV 인접군 로더 캐싱 및 핫 리로드
- [ ] 대용량 쿼리 타임아웃, 재시도, 지표 수집

---

## 테스트 전략
- 단위: 박스 크롭, 스코어 병합, 인접군 판정
- 통합: 원본 + 2 크롭 입력 → 이미지/텍스트 Top-K가 정확히 분리되는지 검증
- 회귀: 모델 버전 교체 시 스코어 분포 모니터링

---

## 예시 요청
```bash
curl -X POST http://localhost:8000/search/multimodal \
 -H 'Content-Type: application/json' \
 -d '{
   "image_b64": "...",
   "boxes": [
     {"x1": 0.02, "y1": 0.05, "x2": 0.40, "y2": 0.92},
     {"x1": 0.45, "y1": 0.18, "x2": 0.98, "y2": 0.82}
   ],
   "goods_classes": ["30"],
   "k": 20
 }'
```

이 가이드는 v1 스택을 유지하면서 **바운딩 박스 기반 멀티 이미지 쿼리**, **초기 필터 제거**, **이미지/텍스트 별도 Top-K** 요구사항을 반영한다.
