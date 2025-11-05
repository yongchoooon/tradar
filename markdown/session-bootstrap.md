# 세션 초기화 가이드

KT Cloud 세션을 새로 생성할 때마다 아래 순서로 개발 환경을 재구성합니다. 모든 명령은 리포지토리 루트(`/home/work/workspace/codex-t-radar`)에서 실행한다고 가정합니다.

---

## 0. 자동화 스크립트 실행
- **처음 환경을 준비할 때** 아래 스크립트가 설치와 시딩을 모두 처리합니다.
  ```bash
  bash scripts/bootstrap_seed.sh
  # 또는 사용자 데이터로 시딩
  bash scripts/bootstrap_seed.sh /path/to/trademarks.json /path/to/images
  ```
  - 기본 동작
    - `apt-get`으로 PostgreSQL/pgvector 설치
    - PostgreSQL 서비스 기동 및 `postgres` 계정 비밀번호를 `postgres`로 설정
    - `tradar` 데이터베이스와 `vector` 확장 생성
    - 충돌 가능 패키지(`transformer-engine`, `flash-attn`, `transformers`) 제거 후 `pip install -r requirements.txt`
    - 지정한 메타데이터/이미지로 벡터 DB 시딩
    - OpenSearch 설치·기동, 벡터 DB 시딩 완료 후 인덱스 동기화
    - Torch 백엔드를 기본 사용합니다. 환경변수 `BOOTSTRAP_METACLIP_MODEL`, `BOOTSTRAP_DINOV2_MODEL`, `BOOTSTRAP_EMBED_DEVICE`로 모델 경로나 디바이스를 조정할 수 있습니다.

- **이미 시딩이 끝난 상태에서 세션을 다시 열었다면** 서비스를 기동하고 색인만 동기화합니다.
  ```bash
  bash scripts/bootstrap_session.sh
  ```
  - PostgreSQL 서비스와 OpenSearch를 재시작하고 `scripts/sync_opensearch.sh`를 자동으로 실행합니다.

- `sudo`가 없는 환경에서는 아래 수동 절차를 참고하세요.

---

## 1. 수동으로 진행하고 싶다면
1. **패키지 설치**
   ```bash
   sudo apt-get update -y
   sudo apt-get install -y postgresql postgresql-contrib
   sudo apt-get install -y postgresql-15-pgvector || sudo apt-get install -y postgresql-14-pgvector
   ```
   - 만약 `postgresql-XX-pgvector` 패키지가 없다면 `build-essential`, `git`, `postgresql-server-dev-XX`를 설치하고 [pgvector GitHub](https://github.com/pgvector/pgvector) 리포에서 `make && sudo make install`로 빌드하면 됩니다. 자동 시드 스크립트(`bootstrap_seed.sh`)가 이 과정을 대신 실행합니다.
2. **PostgreSQL 서비스 시작**
   ```bash
   sudo service postgresql start
   ```
3. **DB/사용자 설정**
   ```bash
   sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
   sudo -u postgres createdb tradar 2>/dev/null || true
   sudo -u postgres psql -d tradar -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
4. **파이썬 의존성 설치**
   ```bash
   pip install -r requirements.txt
   ```
   - `requirements.txt`는 GitHub에서 최신 `transformers`를 받아오고 `huggingface_hub[cli]`도 함께 설치합니다. 네트워크가 필요하며, 기존에 설치된 구버전 `transformers`는 자동으로 제거됩니다.
5. **벡터 DB 시딩**
  ```bash
  python scripts/vector_db_prepare.py \
    --metadata data/trademarks.json \
    --images-root data/images \
    --database-url postgresql://postgres:postgres@localhost:5432/tradar \
    --truncate
  ```
   - 실제 DINOv2/MetaCLIP2 임베딩을 생성하려면 Torch 모델 경로와 디바이스를 확인하고 필요 시 `--metaclip-model`, `--dinov2-model`, `--embed-device` 옵션으로 지정합니다 (백엔드는 기본적으로 Torch).
   - 예시 (CPU 실행):
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
      --embed-device cpu
    ```
    - 메타데이터 파일에 개별 이미지의 절대 경로가 있는 경우(`image_paths`/`mark_image_paths` 등) `--images-root`와 무관하게 해당 경로를 그대로 사용합니다.
    - 파라미터를 생략하면 기본값으로 `data/trademarks.json`, `data/images/`를 참조합니다.

---

## 2. 확인용 명령
- PostgreSQL 접속: `psql postgresql://postgres:postgres@localhost:5432/tradar`
- 레코드 확인: `SELECT count(*) FROM image_embeddings_dino;`
- FastAPI에서 사용할 환경 변수 예시:
  - `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tradar`
  - `OPENSEARCH_URL=http://localhost:9200` (OpenSearch 사용 시)
  - 검색 응답에는 `application_number`, `title_korean`, `title_english`, `goods_services`, `doi`, `thumb_url` 등이 포함되며 DOI는 프론트엔드 카드에서 링크로 노출됩니다.

---

## 3. 참고
- Docker 기반 배포를 사용할 경우에는 `docker-compose.yml`의 `postgres`, `opensearch`, `api` 서비스를 `docker compose up -d`로 실행하면 동일한 구조를 재현할 수 있습니다.
- 스크립트는 매번 새 세션에서 실행되더라도 이미 설치된 패키지를 덮어쓰지 않고 필요한 경우만 다시 설정합니다.
- 부팅 스크립트는 Torch 백엔드를 기본 사용합니다. 모델 경로나 디바이스는 `BOOTSTRAP_METACLIP_MODEL`, `BOOTSTRAP_DINOV2_MODEL`, `BOOTSTRAP_EMBED_DEVICE`로 조정할 수 있습니다.
- GPT 기반 유사어 생성을 사용하려면 `.env` 파일에 `OPENAI_API_KEY`를 설정하고 `TRADEMARK_LLM_MODEL`(기본값 `gpt-4o-mini`)을 필요에 따라 조정하세요.
