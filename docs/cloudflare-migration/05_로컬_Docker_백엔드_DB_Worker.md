# 05. 로컬 Docker 백엔드·DB·worker 구성

## 1. 유지할 구성

현재 데스크톱에 다음 서비스를 유지한다.

```text
db              pgvector/pgvector:pg15
opensearch      opensearchproject/opensearch:2.11.1
api             FastAPI/Uvicorn
desktop-worker  GPU search worker
cloudflared     새로 추가할 Tunnel connector
```

`~/workspace/tradar-data`는 worker/API에 read-only mount한다.

## 2. 현재 Compose 관계

기본 stack:

```bash
docker compose -f docker-compose.yml up -d db opensearch api
```

Worker stack:

```bash
docker compose -f docker-compose.desktop.yml up -d desktop-worker
```

`docker-compose.desktop.yml`은 기본 stack의 network를 external network로 참조한다.

```yaml
networks:
  tradar_external:
    external: true
    name: ${DESKTOP_COMPOSE_NETWORK:-tradar_default}
```

실제 network 확인:

```bash
cd ~/workspace/tradar
docker compose up -d db opensearch api
docker network ls
bash scripts/find_compose_network.sh
```

필요하면 `.env`에 설정한다.

```env
DESKTOP_COMPOSE_NETWORK=tradar_default
```

## 3. 환경변수 파일 분리

권장 파일:

```text
.env.runtime       backend/worker runtime secret, Git 제외
.env.cloudflare    Tunnel token, Git 제외
.env.example       이름과 설명만 포함, 실제 secret 금지
```

권한:

```bash
chmod 600 .env.runtime .env.cloudflare
```

현재 레포의 `.gitignore`는 `.env.runtime`과 `.env.cloudflare`을 자동으로 무시하지 않으므로 먼저 다음 항목을 추가한다.

```gitignore
.env.runtime
.env.cloudflare
.env.r2
```

포함됐는지 확인한다.

```bash
git check-ignore -v .env.runtime .env.cloudflare
```

## 4. Backend/worker 환경변수

직접 새 목록을 만들지 말고 저장소의 template을 복사한다.

```bash
cd ~/workspace/tradar
cp .env.runtime.example .env.runtime
chmod 600 .env.runtime
```

반드시 바꿀 항목:

```text
POSTGRES_PASSWORD와 DATABASE_URL 안의 URL-encoded password
CORS_ALLOWED_ORIGINS
외부 API key(모두 새로 회전한 값)
ADMIN_PASSWORD / ADMIN_COOKIE_SECRET
DESKTOP_WORKER_TOKEN / WORKER_TOKEN(같은 값)
R2_ENDPOINT_URL / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY
```

SSM client는 코드에서 삭제됐다. 모든 runtime 설정은 `.env.runtime`에서 오며 `TRADAR_DISABLE_SSM` 같은 flag는 더 이상 존재하지 않는다. Pages frontend에는 이 secret들을 넣지 않는다.

## 5. Compose에서 env를 실제 container에 주입

`docker-compose.yml`과 `docker-compose.desktop.yml`은 다음 파일을 `env_file`로 읽도록 이미 수정됐다.

```yaml
env_file:
  - ${TRADAR_RUNTIME_ENV_FILE:-.env.runtime}
```

Compose의 `${POSTGRES_PASSWORD}` 보간도 같은 값을 보게 하려면 실행 때 `--env-file`을 함께 준다.

```bash
docker compose --env-file .env.runtime config >/dev/null
docker compose --env-file .env.runtime up -d db opensearch api
docker compose --env-file .env.runtime -f docker-compose.desktop.yml up -d desktop-worker
```

Container 내부에서는 secret 값을 출력하지 않고 SET/MISSING만 검사한다.

```bash
docker compose exec api python - <<'PY'
import os
for key in [
    "APP_ENV", "DATABASE_URL", "OPENSEARCH_URL", "CORS_ALLOWED_ORIGINS",
    "R2_ENDPOINT_URL", "R2_BUCKET", "R2_ACCESS_KEY_ID",
]:
    print(key, "SET" if os.getenv(key) else "MISSING")
PY
```

## 6. Worker WebSocket을 로컬로 변경

권장:

```env
WORKER_WS_URL=ws://api:8000/ws/worker
```

조건:

- worker와 api가 같은 Docker network에 연결됨
- service name이 `api`
- API가 container port 8000에서 listen

대안:

```env
WORKER_WS_URL=ws://host.docker.internal:8000/ws/worker
```

AWS/Cloudflare 외부 주소는 사용하지 않는다.

```text
사용하지 않음: wss://api.example.com/ws/worker
사용:         ws://api:8000/ws/worker
```

이렇게 하면 Access cookie/service token 문제 없이 worker가 로컬에서 직접 등록된다.

## 7. Port 노출 제한

Cloudflare Tunnel은 inbound port forwarding을 요구하지 않는다. Host port가 필요하면 localhost에만 bind한다.

```yaml
ports:
  - "127.0.0.1:5432:5432"
```

```yaml
ports:
  - "127.0.0.1:9200:9200"
```

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

확인:

```bash
ss -lntp | grep -E ':(5432|9200|8000)\b'
```

기대값은 `127.0.0.1` 또는 Docker 내부 접근뿐이다. 공유기에서 5432/9200/8000 port forwarding을 만들지 않는다.

## 8. Restart policy

데스크톱 재부팅 후 자동 복구를 위해 각 서비스에 적용한다.

```yaml
restart: unless-stopped
```

적용 대상:

- db
- opensearch
- api
- desktop-worker
- cloudflared

Docker daemon도 OS 시작 시 자동 실행되도록 설정한다.

```bash
sudo systemctl enable --now docker
```

## 9. Healthcheck 권장

PostgreSQL:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U postgres -d tradar"]
  interval: 10s
  timeout: 5s
  retries: 10
```

OpenSearch:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://localhost:9200/_cluster/health || exit 1"]
  interval: 15s
  timeout: 5s
  retries: 20
```

API는 image에 curl이 없을 수 있으므로 Python healthcheck를 사용할 수 있다.

```yaml
healthcheck:
  test:
    - CMD-SHELL
    - >-
      python -c "import urllib.request;
      urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
  interval: 15s
  timeout: 5s
  retries: 10
```

`depends_on`의 service health 조건은 사용 중인 Compose specification 지원 여부를 확인한다.

## 10. 시작 순서

```bash
cd ~/workspace/tradar

docker compose up -d db opensearch

docker compose ps
curl -fsS http://127.0.0.1:9200/_cluster/health?pretty

docker compose up -d api
curl -fsS http://127.0.0.1:8000/health

docker compose -f docker-compose.desktop.yml up -d desktop-worker

docker compose logs --tail=100 api
docker compose -f docker-compose.desktop.yml logs --tail=100 desktop-worker
```

Tunnel은 API 로컬 검증 후 시작한다.

## 11. 연결성 검사

### API -> DB

```bash
docker compose exec api python - <<'PY'
from app.services import db
with db.get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("select 1")
        print(cur.fetchone())
PY
```

### API/worker -> OpenSearch

```bash
docker compose exec api python - <<'PY'
import os
from opensearchpy import OpenSearch
c = OpenSearch(os.environ["OPENSEARCH_URL"])
print(c.ping())
PY
```

### Worker 등록

```bash
docker compose -f docker-compose.desktop.yml logs desktop-worker \
  | grep -E 'Connecting|registered|connectivity OK'
```

Worker가 등록되지 않으면:

1. `WORKER_WS_URL`
2. Docker network
3. `WORKER_TOKEN`/`DESKTOP_WORKER_TOKEN`
4. worker ID allowlist
5. API logs

순서로 확인한다.

## 12. Readiness endpoint 권장

현재 `/health`는 API process 상태만 반환하고 worker 등록 여부를 보장하지 않는다. 운영에서는 별도 endpoint를 추가한다.

예상 응답:

```json
{
  "status": "ready",
  "worker_connected": true,
  "database": "ok",
  "opensearch": "ok"
}
```

Secret이나 내부 URL은 응답하지 않는다. DB/OpenSearch 검사를 매 요청마다 무겁게 수행하지 않도록 timeout/cache를 둔다.

## 13. API process 수 제한

현재 상태 저장이 메모리 기반이므로:

```text
Uvicorn workers: 1
API replicas: 1
```

다음을 사용하지 않는다.

```bash
uvicorn app.main:app --workers 4
```

여러 process가 필요하려면 worker registry, search cache, simulation job을 Redis/DB 기반으로 먼저 리팩터링한다.

## 14. 원본 이미지 mount 확인

현재 예시:

```yaml
volumes:
  - ${TRADAR_IMAGE_ROOT:-../tradar-data}:/data/images:ro
```

확인:

```bash
docker compose exec api sh -c 'find /data/images -maxdepth 2 -type f | head'
docker compose -f docker-compose.desktop.yml exec desktop-worker \
  sh -c 'find /data/images -maxdepth 2 -type f | head'
```

Host path는 다음으로 명시할 수 있다.

```env
TRADAR_IMAGE_ROOT=/home/jinwon/workspace/tradar-data
```

## 15. 완료 조건

- [ ] DB/OpenSearch/API/worker가 같은 기대 network에서 동작한다.
- [ ] worker가 `ws://api:8000/ws/worker`로 등록된다.
- [ ] SSM lookup이 꺼졌다.
- [ ] Backend R2 환경변수가 실제 container에 주입됐다.
- [ ] DB/OpenSearch/API port가 공인 인터페이스에 노출되지 않는다.
- [ ] 데스크톱 재부팅 후 container가 자동 시작된다.
- [ ] API process/replica는 1개다.
- [ ] `tradar-data`가 read-only mount됐다.
