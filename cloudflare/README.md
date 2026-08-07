# Cloudflare dashboard input samples

- `r2-cors.dashboard.example.json`: paste into the R2 bucket CORS policy. It is
  currently configured for the temporary Pages origin
  `https://t-radar.pages.dev`; replace it when a custom domain is added.
- Keep only localhost origins that are actually used for development.
- An allowed origin must not include a path and must not end with `/`.
- Never commit a tunnel token, R2 secret key, or Cloudflare API token here.

The named Tunnel is remotely managed in the Cloudflare dashboard. Its published
application maps the public API hostname to the Docker-network service URL
`http://api:8000`. The local token belongs only in `.env.cloudflare` as
`TUNNEL_TOKEN`.

## 로컬 Backend 스택 실행

Desktop GPU Worker는 Backend API가 정상적으로 준비된 뒤 실행해야 한다.
따라서 기본 스택과 Worker를 동시에 올리지 않고 두 터미널에서 순서대로
실행한다.

### 1단계: 기본 스택 실행

첫 번째 터미널에서 PostgreSQL, OpenSearch, Backend API를 실행한다.

```bash
cd ~/workspace/tradar

docker compose \
  --env-file .env.runtime \
  -f docker-compose.yml \
  up --build db opensearch api
```

`api`가 시작되고 `/health` 검사가 통과할 때까지 기다린다. `-d`를 사용하지
않으므로 기본 스택 로그가 첫 번째 터미널에 계속 표시된다.

### 2단계: Desktop Worker 실행

기본 스택이 정상 상태가 된 다음 새 터미널을 열어 Worker를 실행한다.

```bash
cd ~/workspace/tradar

docker compose \
  --env-file .env.runtime \
  -f docker-compose.desktop.yml \
  up --build desktop-worker
```

Worker 로그는 두 번째 터미널에 계속 표시된다. 각 스택을 종료하려면 해당
터미널에서 `Ctrl+C`를 누른다.

Quick Tunnel은 아래 명령으로 세 번째 터미널에서 실행한다.

## 도메인 없는 Quick Tunnel 실행 방법

현재 로컬 네트워크에서는 QUIC에 사용하는 outbound UDP 연결이 차단되어
`530` 응답이 발생할 수 있다. 따라서 Quick Tunnel을 실행할 때는 HTTP/2
transport를 명시적으로 사용한다.

먼저 로컬 Backend가 정상인지 확인한다.

```bash
curl -i http://127.0.0.1:8000/health
```

`200 OK` 응답을 확인한 다음 Quick Tunnel을 실행한다.

```bash
cloudflared tunnel \
  --protocol http2 \
  --url http://127.0.0.1:8000
```

이 명령을 실행한 터미널은 Tunnel을 사용하는 동안 종료하지 않는다.
로그에 `Registered tunnel connection`이 표시되어야 하며, 새 터미널에서
발급된 주소를 확인한다.

```bash
curl -i https://<발급된-주소>.trycloudflare.com/health
```

Quick Tunnel을 다시 실행할 때마다 주소가 바뀔 수 있으므로 새 주소를
`VITE_API_BASE_URL`에 반영한 뒤 frontend를 다시 build/deploy해야 한다.

### Quick Tunnel 주소를 Frontend `.env`에 저장하고 build

Quick Tunnel 주소를 build 명령 앞에 일회성 환경변수로 지정하지 않고
`frontend/.env`에 저장한다.

```bash
cd ~/workspace/tradar/frontend
nano .env
```

발급된 실제 주소를 다음과 같이 저장한다. 주소 끝에는 `/`를 붙이지 않는다.

```dotenv
VITE_API_BASE_URL=https://<발급된-주소>.trycloudflare.com
```

Vite에서는 `.env.local`이 `.env`보다 우선한다. 따라서 `frontend/.env.local`에
`VITE_API_BASE_URL`이 별도로 존재하면 삭제하거나 주석 처리해야 한다. 그렇지
않으면 `.env`에 저장한 Quick Tunnel 주소가 build에 반영되지 않는다.

그다음 별도의 환경변수 주입 없이 build한다.

```bash
npm ci
npm run build
```

`frontend/.env`와 `frontend/.env.local`은 Git에서 제외된 로컬 설정 파일이므로
커밋하지 않는다. Quick Tunnel을 다시 실행해 주소가 변경되면 `.env`의 값을
새 주소로 변경한 후 frontend를 다시 build/deploy한다.

## Quick Tunnel 사용 시 반드시 알아야 할 제약

도메인 없이 발급받는 `*.trycloudflare.com` Quick Tunnel은 운영 배포가
아니라 개발 및 임시 테스트 용도로만 사용한다.

- Tunnel을 다시 실행하면 무작위 hostname이 변경될 수 있다.
- API hostname이 바뀌면 `VITE_API_BASE_URL`도 변경하고 frontend를 다시
  build/deploy해야 한다.
- 소유한 도메인이 아니므로 프로젝트용 Cloudflare Access 보호를 정상적인
  운영 방식으로 적용할 수 없다.
- URL을 아는 사용자는 로컬 API에 접근할 수 있으므로 URL을 공개하지 않는다.
- 동시에 처리할 수 있는 in-flight request는 최대 200개이며, 초과하면
  `429` 응답이 발생한다.
- Server-Sent Events(SSE)를 지원하지 않는다.
- SLA와 uptime이 보장되지 않는다.

### T-RADAR 기능별 영향

| 기능 | Quick Tunnel에서의 상태 |
|---|---|
| 이미지·텍스트·상품 검색 | 일반 HTTP 요청이므로 임시 테스트 가능 |
| Desktop worker WebSocket | `ws://api:8000/ws/worker` Docker 내부 연결이므로 영향 없음 |
| Simulation stream | SSE 기반이므로 Quick Tunnel에서는 지원되지 않음 |
| 관리자 session | Pages와 API가 서로 다른 site이고 admin cookie가 `SameSite=Lax`이므로 정상 동작을 보장할 수 없음 |

따라서 Quick Tunnel은 화면 및 기본 검색 smoke test에만 사용한다. Simulation,
관리자 기능, 고정 API 주소, Access 인증이 필요한 단계에서는 소유 도메인을
Cloudflare에 연결하고 remotely-managed named Tunnel로 전환해야 한다.

공식 문서:

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
