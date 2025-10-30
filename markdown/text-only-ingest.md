# 텍스트 전용 임베딩 적재

`scripts/vector_db_prepare_text_only.py` 스크립트는 이미지 임베딩을 건드리지 않고
`trademarks`, `text_embeddings_metaclip` 두 테이블만 업데이트한다. 기존
`vector_db_prepare.py`가 요구하는 이미지 파일이 없거나, 텍스트 임베딩만 후속으로
추가하려는 경우에 사용한다.

## 실행 예시

```bash
python scripts/vector_db_prepare_text_only.py \
  --metadata data/trademarks_real_no_vienna.json \
  --database-url postgresql://postgres:postgres@localhost:5432/tradar \
  --text-backend torch \
  --metaclip-model facebook/metaclip-2-worldwide-giant \
  --embed-device cuda:0
```

- `--truncate`를 함께 지정하면 기존 `trademarks`, `text_embeddings_metaclip`
  레코드를 비운 뒤 새로 채운다. 이미지 임베딩 테이블은 삭제하지 않는다.
- `--text-backend`, `--metaclip-model`, `--embed-device`는 기존
  `vector_db_prepare.py`와 동일하게 동작하며 생략하면 환경변수/기본값(모두 Torch 백엔드)을 따른다.
- 벡터 차원은 첫 레코드에서 추론하므로 입력 메타데이터가 최소 1건 이상이어야
  한다.

## 주의 사항

- 스크립트는 `scripts/vector_db_prepare.py`의 헬퍼를 재활용하므로 JSON/CSV/TSV
  포맷 요구사항은 동일하다.
- 메타데이터에 `image_path`/`image_paths`/`mark_image_paths`가 포함돼 있으면 처음
  찾은 경로를 `trademarks.image_path`에 기록한다. 값이 없으면 기존 DB 값이 그대로
  유지된다.
