# 13. AWS 삭제 후 Cloudflare 전환 실제 실행 순서

> 기준일: 2026-08-06
> 목표: Frontend는 Cloudflare Pages, object storage는 R2, 외부 API는 Access + Tunnel, DB/OpenSearch/API/GPU worker는 데스크톱 Docker에서 운영한다.

## 표기

- **[사용자 작업]** Cloudflare/GitHub Dashboard나 secret 입력처럼 이 레포가 대신할 수 없는 작업
- **[코드 수정 완료]** 현재 `main` 작업 트리에 구현된 항목
- **[값 확정 후 설정]** 실제 domain/account/token이 있어야 완료할 수 있는 항목
- **[후속 코드 수정]** 조건에 따라 나중에 별도 개발이 필요한 항목

---

## 0단계. Git legacy branch 보존

**[코드 수정 완료]** AWS 버전의 마지막 commit `be50024`를 가리키는 로컬 branch `legacy/aws`를 만들었고, 현재 작업 branch는 `main`이다.

확인:

```bash
cd ~/workspace/tradar
git branch --show-current
git log -1 --oneline legacy/aws
git log -1 --oneline main
```

`legacy/aws`를 GitHub에도 보존하려면 **사용자가 확인 후** 한 번 push한다.

```bash
git push -u origin legacy/aws
```

이 명령은 legacy branch만 올린다. 현재 main 변경까지 올리는 명령이 아니다. 실제 secret 파일과 다음 사용자 소유 untracked 파일은 migration commit에 포함하지 않는다.

```text
.omx/
.env.runtime
.env.cloudflare
깃허브_페이지_클라우드플레어_R2_전환_계획.md
쟁점_중심_RAG_기능_제안.md
```

---

## 1단계. 먼저 회전해야 할 secret

**[사용자 작업, 최우선]** 이전 대화에 실제 값이 노출된 것으로 보이는 다음 종류의 credential은 전부 폐기/회전한다.

- OpenAI/Gemini/Hugging Face/KIPRIS key
- 관리자 password/cookie secret
- API-worker 공유 token
- 과거 AWS access key가 혹시 남아 있다면 삭제 상태 재확인

새 값만 `.env.runtime`에 사용한다. GitHub issue, commit, 문서, shell history에 실제 값을 넣지 않는다.

---

## 2단계. Cloudflare account와 domain 준비

**[사용자 작업]**

1. Cloudflare account MFA를 켠다.
2. 보유 domain을 Cloudflare에 Add a site 한다.
3. Registrar nameserver를 Cloudflare가 제시한 값으로 변경한다.
4. Cloudflare zone 상태가 `Active`가 될 때까지 기다린다.
5. hostname을 확정한다.

권장 예:

```text
Frontend: tradar.example.com
API:      api.example.com
```

처음 Pages를 시험할 때는 `*.pages.dev`를 쓸 수 있다. 그러나 named Tunnel에 안정적인 production hostname을 붙이려면 Cloudflare에서 관리하는 domain이 필요하다.

**코드 수정 필요 없음.** 이 단계는 account/DNS 설정이다.

---

## 3단계. Private R2 bucket 만들기

**[사용자 작업]** Cloudflare Dashboard에서 R2 Object Storage로 이동한다.

1. Bucket 생성: 예시 `tradar-data`
2. Public Development URL/Public access: 끔
3. R2 API token 생성
4. Scope: 해당 bucket만
5. Permission: Object Read & Write
6. 다음 값을 password manager에 저장

```text
Account ID
Access Key ID
Secret Access Key
S3 API endpoint: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
Region: auto
```

Global API key나 Pages deploy token을 boto3 credential로 재사용하지 않는다.

### R2 CORS 입력

`cloudflare/r2-cors.dashboard.example.json`을 열고 실제 frontend origin으로 바꿔 bucket CORS에 붙여 넣는다.

```json
[
  {
    "AllowedOrigins": ["https://tradar.example.com"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["Content-Type"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

주의:

- Origin 끝에 `/`를 넣지 않는다.
- Path를 넣지 않는다.
- 로컬 개발을 할 때만 `http://localhost:5172`를 추가한다.
- 운영에서는 `*`를 쓰지 않는다.
- Presigned PUT 때 `Content-Type`은 presign 요청에 사용한 값과 같아야 한다.

**코드 수정 필요 없음.** Dashboard 설정이다.

---

## 4단계. 로컬 runtime 파일 만들기

**[사용자 작업]**

```bash
cd ~/workspace/tradar
cp .env.runtime.example .env.runtime
cp .env.cloudflare.example .env.cloudflare
chmod 600 .env.runtime .env.cloudflare
git check-ignore -v .env.runtime .env.cloudflare
```

`.env.runtime`의 모든 `CHANGE_ME`를 바꾼다. 특히:

```env
CORS_ALLOWED_ORIGINS=https://tradar.example.com

R2_ENABLED=true
R2_BUCKET=tradar-data
R2_LOG_BUCKET=tradar-data
R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<new-r2-access-key>
R2_SECRET_ACCESS_KEY=<new-r2-secret-key>
R2_REGION=auto

WORKER_WS_URL=ws://api:8000/ws/worker
```

다음 두 값은 반드시 동일해야 한다.

```text
DESKTOP_WORKER_TOKEN == WORKER_TOKEN
```

`POSTGRES_PASSWORD`에 URL 예약문자가 있으면 `DATABASE_URL` 안에서는 percent-encoding한다. `TRADAR_IMAGE_ROOT=../tradar-data`는 현재 경로 구조라면 `~/workspace/tradar-data`를 mount한다.

**[코드 수정 완료]** SSM lookup은 삭제됐고 API/worker는 `.env.runtime`만 사용한다.

---

## 5단계. 코드와 Compose 정적 검증

실제 container를 올리기 전에 실행한다.

```bash
cd ~/workspace/tradar
.venv/bin/pytest -q
.venv/bin/python -m compileall -q app worker scripts/verify_r2.py

docker compose --env-file .env.runtime config >/dev/null
docker compose --env-file .env.runtime -f docker-compose.desktop.yml config >/dev/null
```

Frontend:

```bash
cd ~/workspace/tradar/frontend
npm ci
VITE_API_BASE_URL=https://api.example.com npm run build
npm audit
```

**[코드 수정 완료]** CI도 동일한 backend test와 frontend build를 실행한다.

---

## 6단계. R2 연결 검증

**[사용자 작업: 실제 R2 값 입력 후]**

```bash
cd ~/workspace/tradar
.venv/bin/python scripts/verify_r2.py --env-file .env.runtime
.venv/bin/python scripts/verify_r2.py --env-file .env.runtime --write
```

두 번째 명령은 `_healthchecks/`에 작은 파일을 만들고 읽고 삭제한다. 실패하면:

1. endpoint의 account ID
2. token scope가 올바른 bucket인지
3. Object Read & Write permission
4. bucket 이름
5. PC 시간 동기화

순서로 확인한다.

---

## 7단계. 로컬 DB/OpenSearch/API 시작

**[사용자 작업]** 기존 Docker volume을 유지한 채 실행한다.

```bash
cd ~/workspace/tradar

docker compose --env-file .env.runtime up -d db opensearch
docker compose --env-file .env.runtime up -d --build api

docker compose --env-file .env.runtime ps
curl -fsS http://127.0.0.1:9200/_cluster/health?pretty
curl -fsS http://127.0.0.1:8000/health
```

API log:

```bash
docker compose logs --tail=200 api
```

DB, OpenSearch, API host port는 모두 `127.0.0.1`에만 bind된다. 공유기 port forwarding을 만들지 않는다.

### API가 R2 presign하는지 확인

```bash
curl -fsS -X POST http://127.0.0.1:8000/media/presign \
  -H 'Content-Type: application/json' \
  -d '{"filename":"r2-test.png","content_type":"image/png"}' \
  | python -m json.tool
```

반환 URL의 query string 전체는 secret처럼 취급하고 로그/문서에 복사하지 않는다.

---

## 8단계. GPU worker 시작

기본 stack이 만든 network를 확인한다.

```bash
cd ~/workspace/tradar
bash scripts/find_compose_network.sh
```

출력값이 `tradar_default`가 아니면 `.env.runtime`의 `DESKTOP_COMPOSE_NETWORK`를 바꾼다.

```bash
docker compose --env-file .env.runtime \
  -f docker-compose.desktop.yml up -d --build desktop-worker

docker compose --env-file .env.runtime \
  -f docker-compose.desktop.yml logs --tail=200 desktop-worker
```

Worker는 public Tunnel을 거치지 않고 `ws://api:8000/ws/worker`로 직접 연결한다.

**[코드 수정 완료]** worker 연결 구조는 로컬 Docker network 기준이다.

---

## 9단계. Named Cloudflare Tunnel 만들기

**[사용자 작업]** Cloudflare Zero Trust Dashboard에서:

1. Networks → Tunnels
2. Create a tunnel
3. Connector: cloudflared
4. Name: `tradar-api`
5. Remotely-managed token 복사
6. `.env.cloudflare`에만 입력

```env
TUNNEL_TOKEN=<new-tunnel-token>
```

Published application/public hostname:

```text
Hostname: api.example.com
Service type: HTTP
Service URL: http://api:8000
```

`localhost:8000`이 아니다. Cloudflared가 Docker container이므로 service name `api`를 사용한다.

시작:

```bash
cd ~/workspace/tradar
docker compose --env-file .env.runtime up -d cloudflared
docker compose logs --tail=200 cloudflared
curl -i https://api.example.com/health
```

Dashboard connector 상태가 `HEALTHY`이고 `/health`가 `{"status":"ok"}`여야 한다. Tunnel은 outbound 연결이라 inbound firewall/router port를 열지 않는다.

**[코드 수정 완료]** Compose cloudflared service는 token을 environment로 읽는다.

---

## 10단계. Access는 Tunnel smoke test 후 적용

처음에는 Tunnel `/health`와 API 기능을 검사하고 곧바로 Access를 건다.

**[사용자 작업]** Zero Trust → Access → Applications에서 self-hosted application을 만든다.

권장:

1. `tradar.example.com`과 `api.example.com` 두 concrete hostname을 하나의 multi-domain application에 포함
2. Allow policy는 본인 이메일/승인한 identity만
3. 비허용 사용자는 차단
4. CORS preflight `OPTIONS` 처리 정책 확인
5. 허용 브라우저에서 frontend와 API 둘 다 로그인 확인

Frontend와 API가 cross-origin이므로 browser request는 Access cookie를 포함해야 한다.

**[코드 수정 완료]** `fetch`는 `credentials: include`, SSE는 `withCredentials: true`를 사용한다.

주의: 브라우저가 third-party cookie를 강하게 차단하면 cross-origin Access 흐름이 실패할 수 있다. 먼저 일반 창에서 테스트한다. 계속 문제가 있으면 **[후속 코드 수정]** Cloudflare Worker/Pages Function으로 `/api/*` same-origin proxy를 만드는 설계로 변경한다.

---

## 11단계. Cloudflare Pages project 만들기

이 레포는 GitHub Actions가 build/deploy하는 **Direct Upload** 방식을 사용한다. Cloudflare native Git integration을 동시에 켜지 않는다.

**[사용자 작업]** Dashboard에서 Workers & Pages → Create → Pages → Direct Upload:

```text
Project name: tradar-frontend
Production branch: main
Build output: frontend/dist (GitHub Actions가 업로드)
```

처음 수동 확인:

```bash
cd ~/workspace/tradar/frontend
VITE_API_BASE_URL=https://api.example.com npm run build
npx wrangler@latest pages deploy dist \
  --project-name=tradar-frontend \
  --branch=main
```

Wrangler login 또는 API token 인증은 Cloudflare 안내에 따른다. 이후 Pages custom domain으로 `tradar.example.com`을 연결한다.

SPA route가 새로고침될 때 `index.html` fallback이 정상인지 `/admin/login` 같은 deep link로 확인한다.

---

## 12단계. GitHub Actions 설정

**[사용자 작업]** Cloudflare에서 Pages 배포용 최소 권한 API token을 별도로 만든다. R2 token/Tunnel token과 분리한다.

GitHub repository → Settings → Secrets and variables → Actions:

### Secrets

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

### Variables

```text
CLOUDFLARE_PAGES_PROJECT=tradar-frontend
VITE_API_BASE_URL=https://api.example.com
```

다음 workflow가 이미 구현됐다.

```text
.github/workflows/ci.yml
.github/workflows/cloudflare-pages-deploy.yml
```

동작:

```text
PR / main push -> backend pytest + frontend build
main의 frontend 변경 -> Pages production deploy
```

Cloudflared, API, DB, worker는 GitHub-hosted runner가 데스크톱 Docker를 조작할 수 없으므로 초기에는 로컬에서 수동 update한다. Self-hosted runner는 host Docker 권한 위험 때문에 별도 보안 설계 전에는 사용하지 않는다.

---

## 13단계. 실제 domain으로 CORS 최종 일치

다음 세 값이 정확히 같아야 한다.

```text
Pages browser origin:       https://tradar.example.com
FastAPI CORS_ALLOWED_ORIGINS=https://tradar.example.com
R2 CORS AllowedOrigins:     https://tradar.example.com
```

변경 후 API 재시작:

```bash
cd ~/workspace/tradar
docker compose --env-file .env.runtime up -d --force-recreate api
docker compose --env-file .env.runtime up -d cloudflared
```

Frontend API hostname은 GitHub variable `VITE_API_BASE_URL=https://api.example.com`로 build에 주입되므로 변수 수정 후 Pages workflow를 다시 실행한다.

**코드 수정 필요 없음.** 값 변경과 재배포 작업이다.

---

## 14단계. End-to-end 검증

허용된 browser에서 순서대로 확인한다.

1. `https://tradar.example.com` Access login
2. `https://api.example.com/health` JSON
3. DevTools Network에서 API request가 login HTML 대신 JSON을 반환
4. `/media/presign` 성공
5. Browser → R2 PUT preflight/PUT 성공
6. Worker가 presigned GET으로 image download
7. 이미지 검색
8. 텍스트/상품 검색
9. Simulation 시작, SSE event, cancel
10. Admin login/session
11. R2 `queries/`, `logs/` object 확인
12. API/worker/cloudflared 각각 restart 후 복구
13. PC reboot 후 Docker 자동 시작

장애 분리:

| 증상 | 먼저 볼 곳 |
|---|---|
| Pages만 열리고 검색 불가 | 데스크톱 전원, API health, Tunnel connector |
| API가 login HTML 반환 | Access application/cookie/domain |
| CORS error | FastAPI origin, R2 CORS, Access OPTIONS |
| R2 `SignatureDoesNotMatch` | endpoint, region `auto`, PUT Content-Type, PC 시간 |
| Worker 미등록 | Docker network, 두 worker token 동일 여부, worker ID allowlist |
| SSE만 끊김 | Access cookie, EventSource, proxy timeout/network |

---

## 15단계. 운영 시작 조건

다음 전에는 외부 사용자를 받지 않는다.

- [ ] 모든 노출 key 회전
- [ ] `legacy/aws` 원격 보존 여부 결정
- [ ] R2 private bucket/token/CORS 검증
- [ ] DB/OpenSearch/API/worker health
- [ ] Tunnel `HEALTHY`
- [ ] Access allow/deny 검증
- [ ] Pages production deploy
- [ ] GitHub CI/Pages deploy 성공
- [ ] 전체 검색/simulation/admin 검증
- [ ] PostgreSQL과 `~/workspace/tradar-data` 외부 backup
- [ ] Desktop/Docker 재부팅 복구 검증

## 공식 문서

- R2 presigned URL: <https://developers.cloudflare.com/r2/api/s3/presigned-urls/>
- R2 CORS: <https://developers.cloudflare.com/r2/buckets/cors/>
- Create a remotely-managed Tunnel: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/>
- Tunnel run parameters: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/>
- Access CORS/cookies: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/cors/>
- Pages Direct Upload: <https://developers.cloudflare.com/pages/get-started/direct-upload/>
- Pages CI with Direct Upload: <https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/>
