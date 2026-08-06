# 03. Cloudflare 계정·도메인·DNS·Access 구성

## 1. 준비물

- Cloudflare account
- 소유한 domain
- domain registrar 로그인 권한
- Cloudflare에 추가할 DNS record 목록
- 허용할 사용자 이메일 목록

권장 hostname:

```text
tradar.example.com  Cloudflare Pages frontend
api.example.com     Cloudflare Tunnel -> local FastAPI
```

## 2. Domain 등록과 DNS hosting 구분

Cloudflare DNS를 사용하기 위해 domain registrar까지 즉시 Cloudflare Registrar로 이전할 필요는 없다.

1. Cloudflare에 site/zone을 추가한다.
2. Cloudflare가 제공한 nameserver 두 개를 확인한다.
3. 현재 registrar에서 authoritative nameserver를 Cloudflare 값으로 변경한다.
4. Cloudflare dashboard에서 zone이 Active인지 확인한다.

Route 53이 registrar인 경우에도 nameserver만 Cloudflare로 바꿀 수 있다. 다만 AWS 사용을 완전히 종료하려면 이후 domain registration도 다른 registrar로 이전한다.

### 기존 Route 53 record 이전

다음 종류를 빠뜨리지 않는다.

- MX
- SPF TXT
- DKIM TXT/CNAME
- DMARC TXT
- 도메인 소유권 검증 TXT
- GitHub/Google/OpenAI 등 외부 서비스 검증 record
- 기존 subdomain

Cloudflare proxy를 켜면 안 되는 record:

- 이메일 MX 대상
- 일반 TCP/비 HTTP 서비스
- 외부 서비스가 DNS-only를 요구하는 검증/연결 record

`tradar`와 `api`는 Cloudflare를 통해 HTTP(S)를 처리하므로 proxied 상태를 사용한다.

## 3. DNS 전파 확인

```bash
dig NS example.com +short
dig A tradar.example.com +short
dig CNAME tradar.example.com +short
dig A api.example.com +short
```

공용 resolver 비교:

```bash
dig @1.1.1.1 NS example.com +short
dig @8.8.8.8 NS example.com +short
```

Route 53 hosted zone은 Cloudflare nameserver 전파와 핵심 record 검증 후 삭제한다.

## 4. Pages frontend domain 예약

Cloudflare Pages 프로젝트 생성은 [07 Pages 프론트엔드](./07_Cloudflare_Pages_프론트엔드.md)에서 진행한다. 프로젝트 생성 후 custom domain으로 다음을 연결한다.

```text
tradar.example.com
```

Pages가 domain 검증과 DNS record를 자동 구성하도록 dashboard 절차를 따른다. 동일 hostname의 기존 A/CNAME record가 있으면 충돌하므로 먼저 확인한다.

## 5. Tunnel API hostname 예약

Cloudflare Tunnel 생성은 [06 Cloudflare Tunnel](./06_Cloudflare_Tunnel.md)에서 진행한다. Public hostname은 다음과 같다.

```text
api.example.com -> http://api:8000
```

데스크톱의 공인 IP를 A record로 만들지 않는다. Tunnel이 생성한 DNS route를 사용한다.

## 6. Cloudflare Access 권장 정책

현재 API에는 검색/시뮬레이션 비용을 발생시키는 endpoint와 `/admin`이 있다. 공개 인터넷에 무인증으로 열지 않는다.

### 권장: frontend와 API를 같은 Access application에 포함

```text
Application type: Self-hosted
Application name: tradar-demo
Domains:
  tradar.example.com
  api.example.com
Session duration: 발표/데모 시간에 맞춤
```

Allow policy 예시:

```text
Action: Allow
Include:
  Emails:
    owner@example.com
    collaborator@example.com
```

사용자가 frontend에 진입할 때 인증하고, API domain에도 application cookie가 발급되는 구성을 목표로 한다.

### 인증 제공자

소수 데모 사용자:

- One-time PIN

조직 사용자:

- Google Workspace
- GitHub
- Microsoft Entra ID

이메일 domain 전체를 허용하는 정책보다 개별 이메일 allowlist가 안전하다.

## 7. Access cookie와 frontend 요청

Access 보호 hostname은 유효한 `CF_Authorization` cookie가 필요하다. Cross-origin API 호출이므로 frontend fetch는 credentials를 포함해야 한다.

```ts
fetch(url, {
  ...init,
  headers,
  credentials: 'include',
})
```

SSE도 credentials를 포함한다.

```js
new EventSource(url, { withCredentials: true })
```

코드 변경은 [08 애플리케이션 코드 변경](./08_애플리케이션_코드_변경.md)을 따른다.

## 8. Access와 CORS preflight

현재 frontend는 `Content-Type: application/json`과 `X-Client-Id`를 사용한다. 브라우저는 본 요청 전에 cookie 없는 `OPTIONS` preflight를 보낼 수 있다. Access가 OPTIONS를 막으면 실제 API 요청은 FastAPI까지 도달하지 않는다.

권장 설정:

1. Zero Trust > Access > Applications
2. `tradar-demo` application 선택
3. Advanced settings > CORS
4. `Bypass OPTIONS requests to origin` 활성화
5. FastAPI CORS가 origin을 엄격히 검증하도록 유지

이 bypass는 `OPTIONS`에만 적용한다. `/search`, `/simulation`, `/admin`, `/media/presign` 전체를 Bypass 정책으로 공개하지 않는다.

FastAPI 설정:

```env
CORS_ALLOWED_ORIGINS=https://tradar.example.com
```

로컬 개발 origin도 필요하면 쉼표로 추가한다.

```env
CORS_ALLOWED_ORIGINS=https://tradar.example.com,http://localhost:5173
```

운영 안정화 후 localhost origin을 제거한다.

## 9. CORS 검증

```bash
curl -i -X OPTIONS https://api.example.com/search/multimodal \
  -H 'Origin: https://tradar.example.com' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type,x-client-id'
```

기대값:

```text
HTTP 200 또는 204
Access-Control-Allow-Origin: https://tradar.example.com
Access-Control-Allow-Methods에 POST
Access-Control-Allow-Headers에 content-type, x-client-id
```

실패 신호:

- 302와 Access login HTML: API용 cookie 또는 Access application domain 설정 확인
- OPTIONS 403: Access CORS bypass/response 설정 확인
- FastAPI 400/405: origin CORS middleware 또는 route 확인
- 브라우저에서만 실패: `credentials: include`, cookie privacy 설정 확인

## 10. Cookie 보안

- frontend/API를 가능하면 같은 site의 subdomain으로 유지한다.
- Access session duration을 필요 이상 길게 두지 않는다.
- HttpOnly 기본 설정을 유지한다.
- private/incognito 브라우저는 third-party/cross-origin cookie 정책 때문에 별도 테스트한다.
- Access만 믿고 애플리케이션 admin password를 제거하지 않는다.

## 11. Rate limiting 권장

다음 endpoint는 비용 또는 GPU 부하를 발생시킨다.

```text
POST /media/presign
POST /search/multimodal
POST /simulation/run
```

Access allowlist가 있더라도 사용자 실수/자동화 오작동을 막기 위해 Cloudflare rate limiting 또는 FastAPI 애플리케이션 제한을 추가한다.

초기 보수적 기준 예시:

| Endpoint | 예시 제한 | 목적 |
|---|---:|---|
| `/media/presign` | 사용자/IP당 분당 20 | 오브젝트 남용 방지 |
| `/search/multimodal` | 사용자/IP당 분당 5 | GPU worker 보호 |
| `/simulation/run` | 사용자/IP당 10분당 2 | LLM 비용 보호 |

실제 데모 사용량에 따라 조정한다.

## 12. 완료 조건

- [ ] Cloudflare zone이 Active다.
- [ ] 기존 이메일/검증 DNS record를 보존했다.
- [ ] `tradar.example.com`과 `api.example.com` 역할을 확정했다.
- [ ] frontend/API가 Access application에 포함됐다.
- [ ] 허용 이메일과 비허용 이메일 동작을 확인했다.
- [ ] OPTIONS만 origin으로 통과하고 실제 API는 인증이 필요하다.
- [ ] Route 53 hosted zone/domain 정리 조건을 확인했다.

## 공식 문서

- Access authorization cookie: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/>
- Access CORS: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/cors/>
- Access policies: <https://developers.cloudflare.com/cloudflare-one/access-controls/policies/>
