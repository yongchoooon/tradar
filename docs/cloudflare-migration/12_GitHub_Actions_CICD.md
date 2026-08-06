# 12. GitHub Actions CI/CD 계획

## 1. 결론

Cloudflare Tunnel을 사용해도 GitHub Actions를 사용할 수 있다. 두 시스템의 역할은 다르다.

| 구성 | 역할 |
|---|---|
| GitHub Actions | test, frontend build, Pages deploy, 선택적 desktop deploy |
| Cloudflare Pages | frontend 정적 파일 hosting/CDN |
| Cloudflare Tunnel/cloudflared | 외부 API 요청을 데스크톱 FastAPI로 전달 |
| R2 | 질의 이미지/로그 object storage |

권장 자동화 범위:

```text
필수:
  - Backend unit test
  - Frontend production build
  - main frontend 변경 시 Cloudflare Pages deploy

초기에는 수동:
  - Desktop API/worker Docker rebuild/restart
  - cloudflared token/config 변경

선택:
  - 보안이 강화된 self-hosted runner를 통한 desktop deploy
```

## 2. 권장 workflow 구성

```text
.github/workflows/ci.yml
.github/workflows/cloudflare-pages-deploy.yml
.github/workflows/desktop-deploy.yml  # 선택, 초기에는 만들지 않아도 됨
```

기존 AWS workflow는 제거한다.

```text
.github/workflows/frontend-deploy.yml
.github/workflows/backend-deploy.yml
```

## 3. CI workflow

목적:

- Pull request에서 backend test
- Frontend dependency install/build
- Cloudflare/AWS credential 없이 실행

예시:

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  backend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install test dependencies
        run: python -m pip install --upgrade pip pytest

      - name: Run tests
        run: pytest -q

  frontend-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: Production build
        working-directory: frontend
        env:
          VITE_API_BASE_URL: https://api.example.com
        run: npm run build
```

현재 test가 추가 dependency를 요구하기 시작하면 `requirements-test.txt`를 만들어 설치 목록을 고정한다. 전체 `requirements.txt`는 Torch/Transformers 때문에 CI가 매우 무거울 수 있으므로 단순 unit test에 바로 사용하지 않는다.

## 4. Pages 배포 방식 선택

이 계획은 다음을 선택한다.

```text
Cloudflare Pages Direct Upload
GitHub Actions build
Wrangler Action deploy
```

Cloudflare native Git integration을 동시에 production deploy 경로로 사용하지 않는다. Push 한 번에 중복 배포되는 것을 방지한다.

Pages project:

```text
Project name: tradar-frontend
Production branch: main
Deployment type: Direct Upload
```

## 5. Cloudflare API token

Cloudflare dashboard에서 Pages 배포 전용 custom API token을 생성한다.

원칙:

- Account 전체 관리자/global API key 사용 금지
- Pages 배포에 필요한 최소 account permission
- 가능하면 대상 account/resource로 scope 제한
- R2 object token과 분리
- Tunnel token과 분리

GitHub repository secrets:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

Repository variable 또는 workflow 상수:

```text
CLOUDFLARE_PAGES_PROJECT=tradar-frontend
VITE_API_BASE_URL=https://api.example.com
```

`VITE_API_BASE_URL`은 공개값이므로 GitHub secret일 필요는 없다.

## 6. Pages production deploy workflow

예시:

```yaml
name: cloudflare-pages-deploy

on:
  push:
    branches: [main]
    paths:
      - "frontend/**"
      - ".github/workflows/cloudflare-pages-deploy.yml"
  workflow_dispatch:

permissions:
  contents: read
  deployments: write

concurrency:
  group: cloudflare-pages-production
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: Build frontend
        working-directory: frontend
        env:
          VITE_API_BASE_URL: https://api.example.com
        run: npm run build

      - name: Check build output
        run: test -f frontend/dist/index.html

      - name: Deploy to Cloudflare Pages
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: >-
            pages deploy frontend/dist
            --project-name=tradar-frontend
            --branch=main
          gitHubToken: ${{ secrets.GITHUB_TOKEN }}
```

API hostname이 실제로 결정되면 `api.example.com`을 실제 값으로 바꾼다.

## 7. 배포 전 test 결합

중복 build를 줄이는 것보다 배포 안전성이 우선이다. Production deploy job에서 `npm ci && npm run build`를 다시 수행한다.

더 엄격하게 운영하려면:

1. CI workflow 성공을 branch protection required check로 지정
2. `main` merge는 CI 성공 후만 허용
3. Pages deploy는 `main` push에서 실행
4. GitHub `production` environment에 승인 rule 설정

개인 프로젝트이고 자동 배포를 원하면 production manual approval는 생략할 수 있다.

## 8. Pull request preview

초기에는 PR preview를 만들지 않는다.

이유:

- Preview마다 Pages origin이 달라질 수 있음
- FastAPI CORS allowlist 필요
- R2 AllowedOrigins 필요
- Cloudflare Access application domain 필요

Preview를 도입할 때:

```yaml
command: >-
  pages deploy frontend/dist
  --project-name=tradar-frontend
  --branch=${{ github.head_ref }}
```

단, fork PR에서는 Cloudflare secret을 노출하거나 deploy job을 실행하지 않는다. Preview origin을 production API에 무제한 허용하지 않는다.

## 9. Cloudflared는 Actions가 직접 배포하지 않음

`cloudflared`는 데스크톱에서 계속 실행되는 connector다. Frontend push마다 다시 배포할 필요가 없다.

변경이 필요한 경우:

- Docker Compose의 cloudflared version 변경
- Tunnel token rotation
- Public hostname/origin 변경
- Access policy 변경

초기에는 이 작업을 데스크톱/Dashboard에서 수동 수행한다.

## 10. 로컬 backend 자동 배포 선택지

GitHub-hosted runner는 데스크톱 Docker daemon에 직접 접근할 수 없다. 자동 배포하려면 별도 방식을 선택해야 한다.

### 선택 A: 수동 배포 — 초기 권장

```bash
cd ~/workspace/tradar
git pull --ff-only
docker compose build api
docker compose up -d api
docker compose -f docker-compose.desktop.yml build desktop-worker
docker compose -f docker-compose.desktop.yml up -d desktop-worker
```

장점:

- 가장 단순
- 데스크톱에 GitHub runner 권한을 주지 않음
- 실행 중 simulation/job을 보고 배포 가능

### 선택 B: GitHub self-hosted runner

데스크톱에 GitHub Actions runner를 설치하고 다음 label을 사용한다.

```text
self-hosted
Linux
X64
tradar-desktop
```

Workflow는 `workflow_dispatch`만 허용한다.

```yaml
name: desktop-deploy

on:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: tradar-desktop-deploy
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: [self-hosted, Linux, X64, tradar-desktop]
    environment: desktop-production
    steps:
      - uses: actions/checkout@v4

      - name: Deploy
        run: /usr/local/sbin/deploy-tradar "${GITHUB_SHA}"
```

`deploy-tradar` script는 다음을 책임진다.

1. 승인된 repository/commit 확인
2. Persistent secret env 사용
3. DB/OpenSearch volume 보존
4. API/worker image build
5. API 1 replica 유지
6. Container recreate
7. health/worker readiness 확인
8. 실패 시 이전 image/commit 복구

## 11. Self-hosted runner 보안

Self-hosted runner는 workflow 명령을 데스크톱에서 실행한다. 따라서 초기에는 권장하지 않는다.

반드시 지킬 조건:

- Private repository 권장
- Public repository fork PR job 금지
- PR event에서 self-hosted runner 사용 금지
- `workflow_dispatch`와 protected environment approval
- Runner user 최소 권한
- Docker group 권한은 사실상 host root 수준임을 인지
- Secret env는 runner workspace 밖에 저장
- Runner update/상태 관리
- Label/group로 대상 workflow 제한

GitHub도 public repository의 fork PR이 self-hosted runner에서 위험한 코드를 실행할 수 있음을 경고한다. 따라서 이 레포가 public이면 desktop deploy는 수동으로 유지하는 것이 안전하다.

## 12. GHCR 방식: 장기 선택지

GitHub Actions에서 image를 GitHub Container Registry에 push하고 데스크톱이 pull하는 방식도 가능하다.

```text
GitHub Actions -> ghcr.io image
Desktop -> docker compose pull -> up -d
```

현재 제약:

- API/worker가 같은 대형 Dockerfile 사용
- Torch/Transformers dependency로 image가 큼
- 로컬 model mount/build 구조 검토 필요

`Dockerfile.api`와 `Dockerfile.worker`를 분리한 후 도입하는 것을 권장한다.

## 13. GitHub environment와 branch protection

권장 environment:

```text
production          Pages deploy
desktop-production  선택적 desktop deploy
```

권장 branch protection:

- Pull request required
- `backend-test` required
- `frontend-build` required
- Direct push 제한은 협업 규모에 맞게 설정

## 14. Secret 금지 목록

Pages workflow에 넣지 않는다.

```text
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
OPENAI_API_KEY
GEMINI_API_KEY
KIPRIS_ACCESS_KEY
DATABASE_URL
DESKTOP_WORKER_TOKEN
TUNNEL_TOKEN
```

Pages deploy에 필요한 Cloudflare API token과 account ID만 GitHub에 둔다. API token은 Pages 배포 최소 권한으로 제한한다.

## 15. Workflow 검증

1. PR 생성
2. Backend/frontend CI 성공
3. `main` merge
4. Pages deploy workflow 실행
5. Wrangler output deployment URL 확인
6. `tradar.example.com` 새 asset 확인
7. Browser API base와 Access/R2 전체 기능 확인

잘못된 frontend가 배포됐으면 Pages 이전 deployment 또는 이전 Git commit을 다시 `workflow_dispatch`로 배포한다.

## 16. 완료 조건

- [ ] AWS workflow가 제거/비활성화됐다.
- [ ] Backend/frontend CI가 있다.
- [ ] Pages는 Direct Upload project다.
- [ ] Main frontend 변경 시 Wrangler deploy가 실행된다.
- [ ] Cloudflare API token은 Pages 최소 권한이다.
- [ ] R2/backend/Tunnel secret은 Pages workflow에 없다.
- [ ] Pull request에서 production secret deploy가 실행되지 않는다.
- [ ] Desktop deploy는 초기에는 수동이다.
- [ ] Self-hosted runner를 사용할 경우 private/protected/manual 조건을 만족한다.

## 공식 문서

- Direct Upload: <https://developers.cloudflare.com/pages/get-started/direct-upload/>
- Direct Upload CI: <https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/>
- Wrangler Action: <https://github.com/cloudflare/wrangler-action>
- GitHub self-hosted runners: <https://docs.github.com/en/actions/reference/runners/self-hosted-runners>
- Self-hosted runner 추가와 보안 주의: <https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners>
