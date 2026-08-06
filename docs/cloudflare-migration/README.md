# T-RADAR AWS 제거 및 Cloudflare 전환 문서 모음

> 기준일: 2026-08-05
> 기준 레포: `/home/jinwon/workspace/tradar`
> 운영 조건: 서비스 중단 허용, AWS rollback 불필요, DB/OpenSearch/FastAPI/GPU worker/원본 데이터는 데스크톱 유지

## 1. 목표 구조

```text
사용자 브라우저
  -> https://tradar.example.com
     Cloudflare Access
     Cloudflare Pages
     React/Vite 정적 프론트엔드

  -> https://api.example.com
     Cloudflare Access
     Cloudflare Tunnel
     cloudflared 컨테이너 (데스크톱)
       -> FastAPI 컨테이너
          -> PostgreSQL + pgvector 컨테이너
          -> OpenSearch 컨테이너
          -> GPU worker 컨테이너 (Docker 내부 WebSocket)
          -> Cloudflare R2 (질의 이미지와 로그)

데스크톱 파일시스템
  -> ~/workspace/tradar-data
     원본 상표 이미지와 데이터 유지
```

### 서비스별 역할

| 서비스 | 역할 | AWS 대체 대상 |
|---|---|---|
| Cloudflare Pages | React/Vite 프론트 빌드와 CDN 배포 | S3 frontend + CloudFront |
| Cloudflare R2 | presigned PUT/GET, 질의 이미지, 선택적 로그/백업 | S3 data bucket |
| Cloudflare Tunnel | 외부 HTTPS API를 로컬 FastAPI로 전달 | ALB + 공개 ECS 진입점 |
| Cloudflare Access | 프론트/API 사용자 인증 | 별도 앱 인증 계층 보강 |
| 로컬 FastAPI | API, SSE, worker registry, simulation | ECS/Fargate backend |
| 로컬 worker | GPU 검색 실행 | 기존 구조 유지 |
| 로컬 PostgreSQL/OpenSearch | 벡터/BM25 데이터 | 기존 구조 유지 |

Cloudflare **R2는 프론트 배포 서비스가 아니다.** 프론트는 Pages에 배포하고 R2는 오브젝트 저장에 사용한다.

## 2. 문서 읽는 순서

AWS 삭제는 이미 끝났으므로 **새 구축은 13번 실행 순서부터 시작**한다. 0~2번은 과거 AWS 구성과 삭제 기록을 확인할 때만 읽는다.

0. [현재 AWS 구성과 SSM의 정확한 설명](./00_현재_AWS_구성과_SSM_정확한_설명.md)
1. [AWS 삭제 전 인벤토리와 백업](./01_AWS_삭제전_인벤토리와_백업.md)
2. [AWS 리소스 삭제 런북](./02_AWS_리소스_삭제_런북.md)
3. [Cloudflare 계정·도메인·DNS·Access](./03_Cloudflare_계정_도메인_DNS_Access.md)
4. [R2 오브젝트 스토리지 구성](./04_R2_오브젝트_스토리지.md)
5. [로컬 Docker 백엔드·DB·worker 구성](./05_로컬_Docker_백엔드_DB_Worker.md)
6. [Cloudflare Tunnel 구성](./06_Cloudflare_Tunnel.md)
7. [Cloudflare Pages 프론트엔드 배포](./07_Cloudflare_Pages_프론트엔드.md)
8. [애플리케이션 코드 변경](./08_애플리케이션_코드_변경.md)
9. [통합 검증과 장애 대응](./09_통합_검증과_장애대응.md)
10. [운영·보안·백업·비용 관리](./10_운영_보안_백업_비용.md)
11. [실행 체크리스트](./11_실행_체크리스트.md)
12. [GitHub Actions CI/CD](./12_GitHub_Actions_CICD.md)
13. [AWS 삭제 후 Cloudflare 전환 실제 실행 순서](./13_Cloudflare_전환_실행순서.md)

## 2.1 CI/CD 결정

Cloudflare로 이전해도 GitHub Actions를 계속 사용한다.

```text
Pull request/push
  -> GitHub Actions: backend test + frontend build

main push (frontend 변경)
  -> GitHub Actions
  -> Wrangler
  -> Cloudflare Pages Direct Upload

Desktop backend/worker/cloudflared
  -> 초기에는 로컬 수동 배포
  -> 선택적으로 보안이 강화된 self-hosted runner로 workflow_dispatch 배포
```

Cloudflare Tunnel은 GitHub Actions를 대체하지 않는다. Tunnel은 네트워크 연결이고, Actions는 test/build/deploy 자동화다.

## 3. 반드시 이해할 운영 특성

### 데스크톱이 꺼지면 API도 중단된다

Pages 프론트 자체는 열리더라도 FastAPI, 검색, 업로드 presign, simulation은 동작하지 않는다. 데스크톱 자동 부팅, Docker restart policy, cloudflared 자동 시작을 설정해야 한다.

### API는 한 프로세스/한 replica로 운영한다

현재 다음 상태가 메모리에 존재한다.

- `app/services/worker_registry.py`: worker 연결과 pending job
- `app/services/search_cache.py`: 검색 결과 context
- `app/services/simulation_jobs.py`: simulation 상태

따라서 동일 API를 여러 replica로 실행하면 요청과 worker 연결이 서로 다른 프로세스로 갈 수 있다. Redis 등의 외부 상태 저장소로 리팩터링하기 전까지 Uvicorn worker와 API replica는 각각 1개로 유지한다.

### worker는 Tunnel을 통하지 않는다

worker는 Docker network 내부에서 다음 주소를 사용한다.

```env
WORKER_WS_URL=ws://api:8000/ws/worker
```

브라우저만 `https://api.example.com`을 사용한다.

### AWS 삭제는 완료됐다

이제 AWS 복구 경로는 전제로 하지 않는다. 로컬 PostgreSQL과 `~/workspace/tradar-data`를 별도 매체에 백업하고, AWS 버전 코드는 `legacy/aws` branch로만 보존한다. 이전 대화에 노출된 외부 API key와 application secret은 새 환경에서 재사용하지 않는다.

## 4. Legacy AWS 버전에서 확인됐던 연동 파일

현재 `main`에서는 아래 파일을 제거하고 R2/Pages/Tunnel 구성으로 교체했다. AWS 시점의 내용은 `legacy/aws` branch에서 확인한다.

```text
.github/workflows/frontend-deploy.yml
.github/workflows/backend-deploy.yml
ecs/task-definition.json
app/services/s3_storage.py
app/services/log_storage.py
app/services/ssm_params.py
```

Legacy 기록에서 확인된 기본 AWS 배포 식별자:

```text
Region: ap-northeast-2
ECS cluster: tradar-cluster
ECS service: tradar-backend-svc
ECR repository: tradar-backend
Frontend S3 bucket: tradar-frontend
```

사용자 기록으로 ALB는 `tradar-alb`, target group은 `tradar-backend-tg`, data bucket은 `tradar-data`로 확인됐다. NAT Gateway는 기록상 이미 삭제됐고, Route 53 사용 근거는 없다. 이 항목들은 삭제 완료된 legacy 기록이며 새 환경에서는 사용하지 않는다.

사용자 기록상 CloudFront distribution은 frontend/API용 두 개였으나 삭제가 완료되어 새 환경에서는 참조하지 않는다.

## 5. 공통 표기

문서의 다음 값은 실제 값으로 치환한다.

```text
example.com          보유 도메인
tradar.example.com   Pages 프론트 도메인
api.example.com      Tunnel API 도메인
<ACCOUNT_ID>         Cloudflare account ID
<AWS_ACCOUNT_ID>     AWS account ID
<R2_ACCESS_KEY_ID>   R2 S3 API access key
<R2_SECRET_KEY>      R2 S3 API secret
```

Secret과 실제 account ID를 문서, Git commit, GitHub issue에 기록하지 않는다.

## 6. 공식 문서

- Cloudflare Pages Git integration: <https://developers.cloudflare.com/pages/configuration/git-integration/>
- Cloudflare Tunnel: <https://developers.cloudflare.com/tunnel/>
- Cloudflare Access CORS: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/cors/>
- Cloudflare R2 presigned URL: <https://developers.cloudflare.com/r2/api/s3/presigned-urls/>
- AWS ECS service 삭제: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/delete-service-v2.html>
- AWS CloudFront distribution 삭제: <https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/HowToDeleteDistribution.html>
