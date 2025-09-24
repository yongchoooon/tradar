# 상표 유사도 검색 서비스 코딩 가이드 v2 (개정 파이프라인)

> 목표: **이미지 전체** 또는 **사용자 지정 영역(바운딩 박스)** 기반으로 비주얼/텍스트 유사 상표를 검색하고, 이미지와 텍스트 각각에 대해 **별도 Top‑K** 결과를 반환한다. 초기 필터링은 하지 않고 **전체 DB**에서 1차 검색 후 중복 제거 및 재랭킹을 수행한다.

---

## 0) 기술 스택 요약 (v1 유지 + 소폭 보강)
- **Backend**: FastAPI + SQLAlchemy + Pydantic
- **Workers/Queue**: Celery + Redis (대용량 임베딩 처리)
- **DB**: PostgreSQL + `pgvector`
- **Search**: OpenSearch(BM25), PGVector(ANN)
- **Object Store**: S3 호환(MinIO/AWS S3)
- **Models(ONNX)**: YOLOv8(선택), ViT/CLIP(이미지 임베딩), KoSentence-BERT(텍스트 임베딩), OCR(PaddleOCR)
- **Model Serving**: onnxruntime-gpu
- **Frontend(선택)**: React + Konva 또는 `react-image-annotate` 로 박스 그리기
- **Container**: Docker / docker-compose

---

## 1) 변경점 한눈에
- [변경] 초기 메타 필터링 없이 **전체 DB**에서 1차 검색 수행
- [추가] **사용자 바운딩 박스 업로드** → 서버에서 **크롭 2개 + 원본 1개 = 최대 3개 쿼리 이미지**
- [단순화] 재랭킹은 **이미지 유사도**와 **텍스트 유사도**만 사용
- [출력] 이미지 Top‑K, 텍스트 Top‑K **각각** 반환. 상태별(등록/거절 등) **분리 표출**.  
  상품/서비스류는 **인접군 vs 비인접군**으로 분리

---

## 2) API 설계

### 2.1 업로드 및 검색 통합
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

### 2.2 상세 정보
`GET /trademarks/{id}`  
서지, 거절사유, 원본 이미지 등 상세 메타 반환.

---

## 3) 서버 처리 파이프라인

### 3.1 입력 전처리
1) 바운딩 박스 좌표 검증(0~1 범위 또는 px → 정규화)  
2) 원본에서 박스별 **서버 측 크롭** 생성  
3) **쿼리 이미지 셋 = {원본} ∪ {크롭들}** (최대 3개)

```python
from PIL import Image

def crop_from_boxes(img: Image.Image, boxes):
    W, H = img.size
    crops = []
    for b in boxes:
        x1, y1, x2, y2 = denorm(b, W, H)
        crops.append(img.crop((x1, y1, x2, y2)))
    return crops
```

### 3.2 임베딩 생성
- 이미지: 각 쿼리 이미지 → ViT/CLIP ONNX → L2 정규화 벡터
- 텍스트: OCR(원본 + 크롭) → 정규화 → KoSBERT ONNX → 벡터
- BM25 텍스트 질의: OCR 결합 텍스트

```python
def encode_images(images): return [vit.encode(img) for img in images]
def encode_texts(texts):  return text_model.encode(" ".join(texts))
```

### 3.3 1차 검색(전체 DB)
- **Visual ANN**: 각 쿼리 이미지 임베딩으로 PGVector `LIMIT N0`  
  여러 크롭 결과는 **id 기준 병합** 후 **최대 유사도**를 그 후보의 `image_sim_raw`로 사용
- **Text ANN**: 텍스트 임베딩으로 PGVector `LIMIT N0`
- **BM25**: OpenSearch로 `title, goods_services, decision_text` 검색 `LIMIT N0`

```sql
-- PGVector 예시
SELECT trademark_id, 1 - (vec <=> :q) AS sim
FROM embeddings
WHERE type='image'
ORDER BY vec <=> :q
LIMIT :N0;
```

### 3.4 병합 및 중복 제거
- 세 소스 결과를 **trademark_id**로 머지
- 각 후보의 스코어 집계
  - `image_sim = max(sim_i over all query crops and over all image hits for that id)`
  - `text_sim_vec = max(sim from text ANN)`
  - `text_sim_bm25 = normalize(bm25_score)` → 0~1 스케일
  - `text_sim = max(text_sim_vec, text_sim_bm25)`

```python
def bm25_norm(score, min_s, max_s):
    if max_s == min_s: return 0.0
    return (score - min_s) / (max_s - min_s)
```

### 3.5 재랭킹
- **이미지 Top‑K**: `sort_by(image_sim)`  
- **텍스트 Top‑K**: `sort_by(text_sim)`
- 이후 **상태별 그룹핑**과 **상품/서비스 인접군** 분리에 사용

---

## 4) 메타데이터 조인 및 그룹핑

### 4.1 핵심 서지 조회
- `trademarks`(id, title, status, class_codes, vienna_codes, app_no, reg_no, owner, dates…)
- `assets`(thumb_url)
- 필요 시 `decisions`(거절사유 전문 요약) 조인

### 4.2 상태별 분리
- `status in {'registered','refused','pending','expired',...}`
- 결과를 **registered vs refused** 우선으로 나눠서 반환

### 4.3 상품/서비스 인접군 판정
- 파일: `app/data/goods_services/ko_goods_services.tsv`
  - 컬럼: `nc_class, name_ko, similar_group_code`
- 로딩 후 **딕셔너리**로 보관
- 입력 `goods_classes` 중 하나라도 후보의 클래스와 **동일한 `similar_group_code`**면 **인접군**으로 간주

```python
def load_goods_groups(tsv_path):
    import csv
    m, group = {}, {}
    with open(tsv_path, newline='', encoding='utf-8') as f:
        for nc, name, g in csv.reader(f, delimiter='\t'):
            m[nc] = {'name': name, 'group': g}
            group.setdefault(g, set()).add(nc)
    return m, group

def is_adjacent(user_classes, target_classes, meta):
    ug = {meta[c]['group'] for c in user_classes if c in meta}
    tg = {meta[c]['group'] for c in target_classes if c in meta}
    return len(ug & tg) > 0
```

---

## 5) 응답 포맷
```json
{
  "query": {"k": 20, "boxes": 2, "goods_classes": ["30","43"]},
  "image_topk": {
    "adjacent": [ { "id":"T1","title":"STARBUCKS","status":"registered","class_codes":["30"],"app_no":"...", "image_sim":0.83, "text_sim":0.61, "thumb":"..." } ],
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

프런트는 썸네일, 상표명, 상태, 클래스, 출원번호, `image_sim`, `text_sim`만 **카드**로 노출. 클릭 시 상세 패널에서 서지, 거절사유, Vienna, 타 이미지 노출.

---

## 6) 모델 관련
- ViT 학습은 **Vienna 중분류 멀티레이블**로 계획. 검색은 **임베딩 코사인** 사용.
- 레지스트리 테이블에 `name, version, task, onnx_key, dim` 저장. 배포는 onnxruntime-gpu 로 세션 캐싱.

---

## 7) DB 스키마 개요(틀만)
- `trademarks(id PK, title, status, class_codes text[], vienna_codes int[], app_no, reg_no, owner, source, published_at, created_at)`
- `assets(id PK, trademark_id FK, image_url, thumb_url)`
- `embeddings(id PK, trademark_id FK, type enum(image|text), dim int, vec vector)`
  - 인덱스: `USING ivfflat (vec vector_cosine_ops) WITH (lists=100)`
- `decisions(id PK, trademark_id FK, type enum(rejection|office_action|accept), text, created_at)`
- `model_registry(id PK, name, version, onnx_object_key, task, dim, meta jsonb)`
- `goods_groups(nc_class text PK, name_ko text, similar_group_code text)`  ← TSV 로드

---

## 8) 핵심 구현 함수 목록 (Codex 힌트)

### 8.1 바운딩 박스 기반 쿼리 이미지 생성
```python
def make_query_images(img_bytes: bytes, boxes: list[dict]) -> list[PIL.Image.Image]:
    img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    crops = crop_from_boxes(img, boxes or [])
    return [img] + crops[:2]  # 최대 3장
```

### 8.2 ANN 검색 유틸
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

### 8.3 후보 병합 및 점수 집계
```python
def merge_hits(img_hits_list, txt_hits, bm25_hits):
    cand = defaultdict(lambda: {'image_sim':0.0,'text_sim_vec':0.0,'text_sim_bm25':0.0})
    for hits in img_hits_list:
        for h in hits:
            cand[h.id]['image_sim'] = max(cand[h.id]['image_sim'], h.sim)
    for h in txt_hits:
        cand[h.id]['text_sim_vec'] = max(cand[h.id]['text_sim_vec'], h.sim)
    # bm25_hits: [{'id':..., 'score':...}]
    min_s = min((h['score'] for h in bm25_hits), default=0.0)
    max_s = max((h['score'] for h in bm25_hits), default=1.0)
    for h in bm25_hits:
        cand[h['id']]['text_sim_bm25'] = max(cand[h['id']]['text_sim_bm25'], bm25_norm(h['score'], min_s, max_s))
    # 최종 텍스트 스코어
    for v in cand.values():
        v['text_sim'] = max(v['text_sim_vec'], v['text_sim_bm25'])
    return cand
```

### 8.4 최종 Top‑K 생성
```python
def topk_by(cand_map, key, k):
    ids = sorted(cand_map.keys(), key=lambda i: cand_map[i][key], reverse=True)
    return ids[:k]
```

### 8.5 그룹핑
```python
def group_by_status_and_goods(ids, meta, user_classes):
    groups = {'registered':[], 'refused':[], 'others':[],
              'adjacent':[], 'non_adjacent':[]}
    for i in ids:
        m = meta[i]
        if m['status']=='registered': groups['registered'].append(i)
        elif m['status']=='refused': groups['refused'].append(i)
        else: groups['others'].append(i)
        (groups['adjacent'] if is_adjacent(user_classes, m['class_codes'], meta_goods) else groups['non_adjacent']).append(i)
    return groups
```

---

## 9) 라우터 스켈레톤
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

    img_groups = group_by_status_and_goods(topk_img_ids, meta, req.goods_classes)
    txt_groups = group_by_status_and_goods(topk_txt_ids, meta, req.goods_classes)

    return build_response(req, cand, meta, img_groups, txt_groups)
```

---

## 10) 프런트엔드 요구 요약
- 원본 업로드 → **전체 검색** 또는 **영역 검색** 라디오 선택
- 영역 검색 시 **박스 그리기** UI, 좌표를 정규화하여 전송
- 결과 화면
  - 탭 1: **이미지 유사 Top‑K**
  - 탭 2: **텍스트 유사 Top‑K**
  - 각 탭 내부에 **등록/거절** 섹션 분리
  - 각 섹션 내부에 **인접군/비인접군** 카드 리스트
  - 카드 항목: 썸네일, 상표명, 상태, 클래스, 출원번호, `image_sim`, `text_sim`
  - 카드 클릭 → 상세 모달

---

## 11) 체크리스트
- [ ] 바운딩 박스 서버 크롭 정확도 검증(px/정규화 혼용 처리)
- [ ] OCR 품질 튜닝 및 글자 정규화
- [ ] 임베딩 차원/정규화 일관성
- [ ] BM25 스코어 정규화 방식 확정(분포 기반)
- [ ] ANN topn, dedupe 정책, 동률 처리
- [ ] 상태값 도메인 표준화
- [ ] TSV 인접군 로더 캐싱 및 핫 리로드
- [ ] 대용량 쿼리 타임아웃, 재시도, 지표 수집

---

## 12) 테스트
- 단위: 박스 크롭, 스코어 병합, 인접군 판정
- 통합: 원본+2크롭 입력 → 두 Top‑K 정확히 분리되는지
- 회귀: 모델 버전 교체 시 스코어 분포 모니터링

---

## 13) 예시 요청
```bash
curl -X POST http://localhost:8000/search/multimodal \
 -H 'Content-Type: application/json' \
 -d '{
   "image_b64": "...",
   "boxes":[{"x1":0.02,"y1":0.05,"x2":0.40,"y2":0.92},{"x1":0.45,"y1":0.18,"x2":0.98,"y2":0.82}],
   "goods_classes":["30"],
   "k":20
 }'
```

이 가이드는 v1의 스택을 유지하면서 **바운딩 박스 기반 멀티 이미지 쿼리**, **초기 필터 제거**, **이미지/텍스트 별도 Top‑K**를 반영한다.