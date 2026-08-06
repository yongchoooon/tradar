# 06. Cloudflare Tunnel 구성

## 1. 목표

인터넷에서 들어오는 다음 요청을 데스크톱 FastAPI로 전달한다.

```text
https://api.example.com
  -> Cloudflare edge
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> cloudflared container
  -> http://api:8000
```

공유기 port forwarding, 고정 공인 IP, ALB는 사용하지 않는다.

## 2. Tunnel 방식 선택

권장: remotely-managed named tunnel

장점:

- Dashboard에서 public hostname 관리
- Docker container에는 tunnel token만 필요
- 로컬 certificate/credentials JSON 관리가 단순

Quick Tunnel(`trycloudflare.com`)은 임시 smoke test에서만 사용하고 production hostname으로 사용하지 않는다.

## 3. Dashboard에서 Tunnel 생성

1. Cloudflare Zero Trust dashboard 진입
2. Networks > Tunnels
3. Create a tunnel
4. Connector: `cloudflared`
5. Name: `tradar-api`
6. Docker connector token 복사

Token은 secret이다. 다음 파일에 저장한다.

```env
TUNNEL_TOKEN=<secret-token>
```

```bash
chmod 600 .env.cloudflare
git check-ignore -v .env.cloudflare
```

## 4. Public hostname 설정

```text
Subdomain: api
Domain: example.com
Type: HTTP
URL: api:8000
```

Service URL은 `http://api:8000`이다. `localhost:8000`을 사용하면 cloudflared container 자신의 localhost를 가리키므로 같은 container가 아닌 한 실패한다.

## 5. Compose 서비스

`docker-compose.yml`에는 다음 형태가 이미 반영됐다.

```yaml
cloudflared:
  image: cloudflare/cloudflared:latest
  restart: unless-stopped
  command: tunnel --no-autoupdate run
  env_file:
    - ${CLOUDFLARE_ENV_FILE:-.env.cloudflare}
  depends_on:
    api:
      condition: service_healthy
```

Remotely-managed Tunnel은 cloudflared가 공식 지원하는 `TUNNEL_TOKEN` 환경변수를 읽는다. Token을 command-line 인자로 넣지 않아 process argument에 노출되는 범위를 줄인다.

```bash
cp .env.cloudflare.example .env.cloudflare
chmod 600 .env.cloudflare
# TUNNEL_TOKEN=... 입력

docker compose --env-file .env.runtime up -d cloudflared
```

`.env.cloudflare`은 service의 `env_file`이고 `.env.runtime`은 Compose의 DB password 보간에 필요하다.

## 6. Container network 확인

```bash
docker compose up -d api cloudflared
docker compose ps
```

cloudflared container에서 API DNS/HTTP 확인:

Cloudflared image에는 shell/curl이 없을 수 있으므로 같은 network에 임시 curl container를 실행한다.

```bash
NETWORK=$(docker inspect "$(docker compose ps -q api)" \
  --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')

docker run --rm --network "$NETWORK" curlimages/curl:latest \
  -fsS http://api:8000/health
```

기대 응답:

```json
{"status":"ok"}
```

## 7. Tunnel 상태 확인

```bash
docker compose logs --tail=200 cloudflared
```

정상 신호:

- tunnel connection registered
- 여러 Cloudflare edge connection 생성
- 반복되는 origin connection error 없음

Dashboard에서도 connector status가 `HEALTHY`인지 확인한다.

## 8. Access 적용 전/후 검사

Access 적용 전 임시 테스트를 했다면 즉시 Access 정책을 적용한다.

```bash
curl -i https://api.example.com/health
```

Access 적용 후 비인증 curl은 다음 중 하나가 정상이다.

- 302 login redirect
- 403
- Access login HTML

허용된 브라우저에서 로그인한 `/health`는 FastAPI JSON을 반환해야 한다.

## 9. WebSocket 검증

Cloudflare Tunnel은 WebSocket을 지원하지만 이 프로젝트의 worker는 로컬 URL을 사용하므로 public WebSocket은 운영 핵심 경로가 아니다.

외부 WebSocket endpoint smoke test가 필요하면 Access 인증 문제를 고려해 브라우저 세션 또는 Access service token을 사용한다. Worker token을 URL query에 넣지 않는다.

운영 권장:

```text
worker -> ws://api:8000/ws/worker (local only)
browser -> HTTPS API/SSE through Tunnel
```

## 10. SSE/긴 요청

Simulation 진행률은 EventSource/SSE를 사용한다.

확인할 항목:

- Cloudflare가 응답을 buffering하지 않는지
- FastAPI가 `text/event-stream`을 반환하는지
- `Cache-Control: no-cache`
- 브라우저 EventSource가 Access cookie를 포함하는지
- 데스크톱 절전으로 connection이 끊기지 않는지

## 11. Origin 보안

- Router inbound 8000 port를 열지 않는다.
- Host API port는 `127.0.0.1:8000`으로 제한한다.
- Tunnel hostname에는 Access를 적용한다.
- `cloudflared` token 유출 시 즉시 connector/token을 rotate한다.
- `/admin`도 같은 API hostname Access 보호 아래 둔다.
- Cloudflare header만으로 사용자 identity를 신뢰하는 로직을 추가하려면 JWT 검증을 별도로 구현한다.

## 12. Client IP 처리

현재 `app/main.py`는 `X-Forwarded-For`를 우선 읽는다. Cloudflare 환경에서는 `CF-Connecting-IP`도 고려할 수 있다.

보안상 임의 client가 origin에 직접 접근할 수 없도록 Tunnel-only 구조를 유지해야 forwarding header spoofing 위험이 줄어든다.

향후 변경 권장:

1. `CF-Connecting-IP` 우선
2. 신뢰된 proxy 경로에서만 forwarding header 사용
3. rate limiting의 식별자와 log IP 정책 일치

## 13. 자동 시작과 업데이트

```yaml
restart: unless-stopped
```

Docker daemon 자동 시작:

```bash
sudo systemctl enable --now docker
```

`latest` tag는 편리하지만 예고 없는 변경을 줄이려면 안정화 후 검증한 cloudflared version으로 pin하고 정기적으로 업데이트한다.

## 14. 장애 진단

### 502 Bad Gateway

확인 순서:

1. `docker compose ps api`
2. 로컬 `curl http://127.0.0.1:8000/health`
3. 동일 Docker network에서 `curl http://api:8000/health`
4. cloudflared public hostname service URL
5. API container listen address가 `0.0.0.0:8000`인지

### 1033/connector 없음

- cloudflared container 실행 여부
- tunnel token 유효성
- 데스크톱 outbound 인터넷/DNS
- Dashboard connector 상태

### Access login 무한 redirect

- frontend/API domain이 같은 Access application인지
- cookie SameSite 설정
- 브라우저 privacy/third-party cookie 차단
- hostname/DNS가 올바른 Cloudflare zone인지

### API는 되지만 simulation stream 실패

- EventSource `withCredentials`
- Access cookie
- `Content-Type: text/event-stream`
- API/container 재시작 여부
- browser Network에서 SSE status 확인

## 15. Tunnel 삭제/재생성

Token이 유출되면 단순 container 재시작으로 해결하지 않는다.

1. Dashboard에서 compromised connector/token 폐기
2. 새 token 발급
3. `.env.cloudflare` 교체
4. container recreate
5. 이전 connector가 더 이상 연결되지 않는지 확인

```bash
docker compose --env-file .env.cloudflare up -d --force-recreate cloudflared
```

## 16. 완료 조건

- [ ] Named tunnel `tradar-api`가 있다.
- [ ] `api.example.com -> http://api:8000`이다.
- [ ] Connector가 HEALTHY다.
- [ ] 공인 inbound port forwarding이 없다.
- [ ] Access 비인증 요청은 차단된다.
- [ ] 허용 브라우저 `/health`는 JSON이다.
- [ ] API/SSE가 Tunnel을 통해 동작한다.
- [ ] cloudflared가 재부팅 후 자동 시작한다.

## 공식 문서

- Cloudflare Tunnel: <https://developers.cloudflare.com/tunnel/>
- Tunnel WebSocket FAQ: <https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/>
- Tunnel configuration: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/>
