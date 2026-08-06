# 07. Cloudflare Pages 프론트엔드 배포

## 1. 배포 대상

```text
Source: frontend/
Build artifact: frontend/dist/
Framework: React + Vite
Production domain: https://tradar.example.com
API base: https://api.example.com
```

R2에는 `frontend/dist`를 업로드하지 않는다. Pages가 정적 asset build/CDN을 담당한다.

## 2. 로컬 production build 확인

```bash
cd ~/workspace/tradar/frontend
npm ci
VITE_API_BASE_URL=https://api.example.com npm run build
```

결과:

```bash
find dist -maxdepth 2 -type f | sort | head -50
grep -R "api.example.com" dist | head
```

로컬 preview:

```bash
npm run preview -- --host 127.0.0.1 --port 4173
```

Build에 secret이 들어가지 않았는지 검사한다.

```bash
rg -n "AKIA|SECRET_ACCESS_KEY|OPENAI_API_KEY|DESKTOP_WORKER_TOKEN" dist || true
```

## 3. Pages Direct Upload 프로젝트 생성

Cloudflare dashboard:

1. Workers & Pages
2. Create application
3. Get started
4. Direct Upload/Upload assets 선택
5. Project name을 `tradar-frontend`로 생성

이 계획은 Cloudflare native Git integration 대신 GitHub Actions에서 Wrangler로 `frontend/dist`를 업로드한다.

```text
GitHub Actions build
  -> frontend/dist
  -> wrangler pages deploy
  -> Cloudflare Pages
```

중요: Direct Upload와 Git integration은 프로젝트 생성 방식이 다르며 나중에 전환할 때 새 Pages 프로젝트가 필요할 수 있다. GitHub Actions 배포를 사용할 것이므로 처음부터 Direct Upload 방식으로 생성한다.

Build 설정은 Cloudflare dashboard가 아니라 GitHub Actions workflow에 둔다.

```text
Working directory: repository root
Build command: npm ci && npm run build
Build output directory: frontend/dist
Pages project: tradar-frontend
```

Node version을 고정한다.

```text
NODE_VERSION=22
```

GitHub Actions build 환경변수:

```text
VITE_API_BASE_URL=https://api.example.com
```

`VITE_*` 값은 browser bundle에 포함될 수 있으므로 secret을 넣지 않는다.

## 4. Custom domain

Pages project > Custom domains:

```text
tradar.example.com
```

Vite `base`는 `/`를 유지한다.

```js
export default defineConfig({
  base: '/',
  // ...
})
```

Cloudflare dashboard가 안내하는 DNS record를 사용하고 동일 hostname의 기존 record 충돌을 제거한다.

검증:

```bash
curl -I https://tradar.example.com
```

Access 적용 후 비인증 curl은 Access redirect/403일 수 있다. 허용된 브라우저에서 실제 HTML과 JS asset을 확인한다.

## 5. GitHub Actions 자동 배포

`main` push에서 frontend build/test가 성공한 경우 Wrangler Action으로 Pages에 배포한다.

권장 trigger:

```text
push: main + frontend/** 또는 Pages workflow 변경
workflow_dispatch: 수동 재배포
pull_request: build/test만 수행, 초기에는 Pages preview 배포하지 않음
```

Preview URL은 매번 origin이 달라질 수 있고 다음 설정을 추가로 요구한다.

- FastAPI CORS allowlist
- R2 CORS AllowedOrigins
- Cloudflare Access application domain

초기 migration에서는 PR preview 배포를 끄고 production custom domain만 검증하는 것이 단순하다. 상세 workflow와 secret은 [12 GitHub Actions CI/CD](./12_GitHub_Actions_CICD.md)를 따른다.

## 6. Monorepo workflow 최적화

GitHub Actions의 `paths`를 사용해 `frontend/**` 변경에만 production deploy를 트리거한다. 공통 API contract나 workflow 변경도 배포 대상에 포함한다.

## 7. 기존 AWS frontend workflow 비활성화

현재 `.github/workflows/frontend-deploy.yml`은 다음을 수행한다.

- AWS credential 설정
- `aws s3 sync`
- CloudFront invalidation

AWS 삭제 전에 GitHub Actions UI에서 workflow를 Disable한다. 코드 migration commit에서는 다음 중 하나를 선택한다.

권장: AWS workflow 제거

```text
.github/workflows/frontend-deploy.yml 삭제
```

새 workflow 예시:

```text
.github/workflows/cloudflare-pages-deploy.yml
```

필요 GitHub secret:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

Frontend build에는 R2 key, Tunnel token, backend API key를 사용하지 않는다.

## 8. API base URL 확인

`frontend/src/lib/apiClient.ts`는 다음 값을 필수로 요구한다.

```text
VITE_API_BASE_URL
```

누락 시 frontend module load 단계에서 오류가 발생한다. Pages production environment variable이 정확한지 확인한다.

```text
올바름: https://api.example.com
잘못됨: https://api.example.com/
잘못됨: http://api:8000
잘못됨: ws://api:8000
```

코드는 trailing slash를 제거하지만 환경변수는 명확한 origin 형태로 둔다.

## 9. Access 보호

`tradar.example.com`을 Cloudflare Access application에 포함한다. 사용자는 Pages HTML을 받기 전에 로그인한다.

장점:

- API 로그인 흐름이 단순해짐
- 데모 사용자 제한
- frontend에서 API를 무인증으로 반복 호출하는 남용 감소

주의:

- Pages default `*.pages.dev` URL이 별도로 열려 있으면 custom domain Access를 우회할 수 있는지 확인한다.
- 필요하면 Pages project의 default domain 접근 정책/redirect를 별도로 관리한다.
- API는 custom domain Access로 독립 보호한다.

## 10. SPA asset 및 cache 검증

브라우저 Network에서 확인:

- `index.html`: 200
- JS/CSS hashed asset: 200
- content type 정확
- API 요청이 `api.example.com`
- AWS CloudFront/S3 URL 요청 없음
- mixed content 없음

새 배포 후 오래된 asset 오류가 보이면 hard reload와 Pages deployment 상태를 확인한다.

## 11. Pages rollback

AWS rollback은 하지 않지만 Pages 내부 이전 deployment로 rollback할 수 있다.

기록할 내용:

- 정상 production deployment ID
- Git commit SHA
- 빌드 환경변수

API schema 변경과 frontend rollback의 호환성도 고려한다.

## 12. 배포 검증

허용 사용자 브라우저:

1. `https://tradar.example.com` 접속
2. Access 로그인
3. landing page 표시
4. 개발자 도구 Console 오류 없음
5. `/health` 또는 첫 API 요청 성공
6. R2 image upload 성공
7. 검색과 simulation 성공

비허용 사용자:

1. Access에서 차단
2. Pages asset/API 응답을 직접 얻지 못함

## 13. 문제 해결

| 현상 | 원인 | 해결 |
|---|---|---|
| Blank page | JS runtime 오류/API env 누락 | Console, `VITE_API_BASE_URL` 확인 |
| Asset 404 | Vite base/output 설정 | custom domain은 `base: '/'` |
| API CORS | Pages origin allowlist 누락 | FastAPI/R2/Access CORS 확인 |
| Access login 후 API 302 | API cookie/credentials 누락 | 같은 Access app, fetch credentials |
| Preview만 실패 | 동적 preview origin 미허용 | preview 비활성 또는 별도 CORS 정책 |
| 옛 AWS API 호출 | 이전 build/env cache | Pages env 수정 후 새 production deploy |

## 14. 완료 조건

- [ ] `npm ci && npm run build`가 로컬에서 성공한다.
- [ ] Pages root/build/output 설정이 정확하다.
- [ ] `VITE_API_BASE_URL`이 production에 설정됐다.
- [ ] `tradar.example.com` custom domain이 연결됐다.
- [ ] Access 로그인 후 frontend가 표시된다.
- [ ] Browser가 AWS endpoint를 호출하지 않는다.
- [ ] AWS frontend workflow가 비활성/삭제됐다.
- [ ] GitHub Actions가 Wrangler로 Pages production deploy를 수행한다.
- [ ] Preview deployment 정책을 결정했다.

## 공식 문서

- Pages Git integration: <https://developers.cloudflare.com/pages/configuration/git-integration/>
- Pages Direct Upload: <https://developers.cloudflare.com/pages/get-started/direct-upload/>
- Direct Upload CI: <https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/>
- Pages GitHub integration: <https://developers.cloudflare.com/pages/configuration/git-integration/github-integration/>
- Pages limits: <https://developers.cloudflare.com/pages/platform/limits/>
