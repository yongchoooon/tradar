# T-RADAR 프로젝트 설정 & 배포 가이드

이 문서는 현재 레포지토리(`FastAPI + LangGraph 백엔드`, `Vite 기반 React 프런트엔드`, `PostgreSQL + pgvector + OpenSearch` 검색 데이터베이스)를 그대로 기준으로 삼아, 로컬 개발부터 AWS 배포까지의 전체 흐름을 쉽게 설명합니다. 원본 문서에 있던 `make` 명령이나 추가 툴은 이 저장소에는 없으므로 아래 절차만 따라 하면 됩니다.

---
## 1. 로컬 개발 환경

### 1.1 필수/선택 소프트웨어
| 구분 | 최소 요구 버전 | 비고 |
| --- | --- | --- |
| Python 3.11 | 권장: pyenv 또는 시스템 Python | FastAPI, LangGraph 실행용 |
| Node.js 18 + npm | `frontend/` 개발/빌드 | Vite Dev Server 필요 |
| PostgreSQL 15 + pgvector | 데이터/임베딩 저장 | `CREATE EXTENSION vector;` 필수 |
| OpenSearch 2.11 이상 | BM25 후보 확장 | 로컬 번들(`scripts/bootstrap_seed.sh`) 또는 AWS OpenSearch Service 사용 |
| Git 2.x | 소스 클론 |  |
| Docker & Docker Compose(선택) | `docker-compose.yml` 빠른 실행 | Postgres, API, Vite를 한 번에 띄울 때 사용 |
| NVIDIA Driver + CUDA Toolkit(선택) | GPU로 임베딩 추론 | `EMBED_DEVICE=cuda:0` 설정 시 필요 |

### 1.2 프로젝트 클론
```bash
# 원하는 경로에서 실행
git clone https://github.com/your-org/tradar.git
cd tradar
```

### 1.3 의존성 설치
1. **Python 가상환경**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -U pip
   pip install -r requirements.txt
   # 레포지토리 코드에서 직접 사용하므로 추가 패키지를 반드시 설치하세요.
   pip install "psycopg[binary]==3.2.*" pgvector opensearch-py tqdm
   ```
2. **프런트엔드**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

### 1.4 환경 변수 작성
1. 기본 템플릿 복사 후 직접 값을 입력합니다.
   ```bash
   cp .env.example .env  # 이미 .env가 있다면 원하는 값으로 수정만 하면 됩니다.
   ```
2. 꼭 알아 두어야 할 주요 변수 (모두 `.env`에 작성하면 `scripts/run_api.sh`가 자동으로 읽습니다.)
   | 변수 | 설명 |
   | --- | --- |
   | `DATABASE_URL` | PostgreSQL 접속 URL. 로컬 기본값 `postgresql://postgres:postgres@localhost:5432/tradar` |
   | `POSTGRES_PASSWORD` | `docker-compose`의 `db` 서비스에서 사용하는 비밀번호 |
   | `OPENAI_API_KEY` | 검색/시뮬레이션 모두에 쓰이는 OpenAI 키 |
   | `KIPRIS_ACCESS_KEY` | KIPRIS IntermediateDocument API 호출용 |
   | `OPENSEARCH_URL` + `OPENSEARCH_INDEX` | BM25 후보 조회용 OpenSearch 도메인 |
| `TRADEMARK_LLM_*`, `SIMULATION_LLM_MODEL` | 검색/시뮬레이션 LLM 모델명 (기본값: `gpt-4o-mini`, `gpt-5-nano`) |
   | `MEDIA_ALLOWED_ROOTS` | `/media/{path}` 다운로드 허용 경로 (기본적으로 `tradar-data`, `tradar`) |

### 1.5 데이터베이스 및 임베딩 시딩
1. **PostgreSQL + pgvector 준비**
   ```bash
   # 한 번만 실행: 데이터베이스/확장 생성
   psql -U postgres -c "CREATE DATABASE tradar;"
   psql -U postgres -d tradar -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
2. **상표 메타데이터 + 임베딩 업로드**
   - 샘플 데이터는 `data/` 디렉터리에 JSON 형태로 포함되어 있습니다. 실제 운영 데이터가 있다면 해당 경로로 대체하세요.
   - GPU가 없다면 `EMBED_DEVICE=cpu`를 환경 변수로 지정해도 됩니다.
   ```bash
   source .venv/bin/activate
   export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/tradar"
   export OPENSEARCH_URL="http://localhost:9200"  # 로컬 OpenSearch가 떠 있어야 합니다.

   python scripts/vector_db_prepare.py \
     --metadata data/trademarks_real.json \
     --images-root data \
     --truncate

   bash scripts/sync_opensearch.sh  # PostgreSQL → OpenSearch 동기화
   ```
3. **OpenSearch 설치가 필요하다면** `scripts/bootstrap_seed.sh`가 PostgreSQL 설치, pgvector 확장, OpenSearch 번들 설치, vector 시딩, 인덱스 싱크까지 자동으로 처리합니다. (Ubuntu/WSL에서 실행하는 것이 가장 수월합니다.)

### 1.6 서비스 실행 방법
**A. Python + Vite (권장 개발 모드)**
```bash
# 1) 백엔드
source .venv/bin/activate
bash scripts/run_api.sh  # uvicorn이 8000번 포트에서 실행됩니다.

# 2) 프런트엔드 (새 터미널)
cd frontend
npm run dev  # http://localhost:5173, FastAPI로 프록시 자동 연결
```

**B. Docker Compose (Postgres/백엔드/프런트 일체 실행)**
```bash
export POSTGRES_PASSWORD=postgres  # docker-compose.yml에서 참조
export OPENAI_API_KEY=...          # 필요한 변수들을 동일하게 export
export KIPRIS_ACCESS_KEY=...
docker compose up --build
```
- Compose 파일에는 OpenSearch 서비스가 포함되어 있지 않으므로, 로컬에서 OpenSearch를 별도로 실행하거나 AWS OpenSearch 엔드포인트를 `.env`에 지정해야 합니다.
- 코드 변경 시 `api` 컨테이너가 볼륨으로 소스를 마운트하므로 자동 리로드됩니다.

### 1.7 주요 URL
| 서비스 | 주소 |
| --- | --- |
| 프런트엔드 (Vite Dev) | http://localhost:5173 |
| FastAPI (Swagger 포함) | http://localhost:8000 / http://localhost:8000/docs |
| 멀티모달 검색 API | POST http://localhost:8000/search/multimodal |
| 시뮬레이션 스트림 | GET http://localhost:8000/simulation/stream/{job_id} |
| OpenSearch health | http://localhost:9200/_cluster/health |

### 1.8 로그 & 디버그 팁
- `logs/simulation_debug/<타임스탬프>/` 디렉터리에 LangGraph 프롬프트와 응답이 저장됩니다. 디버그 모드를 활성화하려면 UI에서 "시뮬레이션 실행(디버그)" 버튼을 사용하세요.
- `uvicorn` 표준 출력에는 `simulation` 로거가 남기는 KIPRIS/에이전트 진행 로그가 실시간으로 찍힙니다.
- 프런트엔드는 `npm run dev` 터미널에서 Vite 빌드 오류를 바로 확인할 수 있습니다.

### 1.9 자주 쓰는 스크립트/명령
| 목적 | 명령 |
| --- | --- |
| 단위 테스트 | `pytest` |
| OpenSearch 재색인 | `bash scripts/sync_opensearch.sh` |
| 임베딩 재시딩 | `python scripts/vector_db_prepare.py --truncate ...` |
| 세션 재시작(WSL/KT Cloud) | `bash scripts/bootstrap_session.sh` |
| Docker 로그 | `docker compose logs -f api` |

---
## 2. AWS 인프라 구성

### 2.1 구성 개요
- **Frontend**: S3 정적 호스팅 + CloudFront CDN. Vite로 빌드한 `frontend/dist`를 업로드합니다.
- **Backend**: FastAPI + LangGraph 컨테이너를 AWS Fargate(ECS)에서 실행하고, ALB가 HTTPS 요청을 받아 8000번 포트로 전달합니다.
- **데이터 계층**: Amazon RDS for PostgreSQL (pgvector 활성화) + Amazon OpenSearch Service. 둘 다 VPC 내부 사설 서브넷에 둡니다.
- **시크릿 관리**: AWS Systems Manager Parameter Store(`/tradar/prod/*`).
- **이미지 저장소**: Amazon ECR(`tradar-backend`).

### 2.2 리소스 구축 순서
1. **VPC/네트워크**
   - CIDR `10.0.0.0/16` 예시, 공용 서브넷(Load Balancer) 2개 + 사설 서브넷(ECS/RDS/OpenSearch) 2개.
   - NAT 게이트웨이를 추가해 사설 서브넷 ECS가 인터넷으로 나가도록 합니다.

2. **RDS (PostgreSQL 17)**
   - 파라미터 그룹에서 `shared_preload_libraries=vector` 설정 후 인스턴스를 생성합니다.
   - 초기화 후 다음을 실행하세요:
     ```sql
     CREATE DATABASE tradar;
     \c tradar
     CREATE EXTENSION IF NOT EXISTS vector;
     ```
   - 보안 그룹: ALB는 접근이 필요 없고, ECS 서비스 SG만 5432 포트를 열어 둡니다.

3. **Amazon OpenSearch Service**
   - 도메인 이름 예: `tradar-search`. t3.medium.search 2노드, 100GB gp3.
   - Advanced 옵션에서 `indices.knn=true`를 켜면 pgvector 데이터와 병행해 BM25를 사용할 수 있습니다.
   - 액세스 정책은 VPC 보안 그룹 기준으로 제한합니다.

4. **S3 + CloudFront (프런트)**
   - 버킷 이름: `tradar-frontend-<환경>`. 정적 웹 페이지 호스팅을 켭니다.
   - CloudFront 배포를 생성하여 S3를 Origin으로 삼고, 기본 루트 객체를 `index.html`로 설정합니다.
   - SPA 라우팅을 위해 403/404 에러 응답을 `/index.html`로 리다이렉션합니다.

5. **ECR & Docker 이미지 빌드**
   - `aws ecr create-repository --repository-name tradar-backend`
   - 백엔드 이미지는 FastAPI 코드와 Python 의존성만 포함합니다. 프런트엔드는 별도 파이프라인(S3/CloudFront)에서 배포하므로 Dockerfile에 `frontend/dist`를 복사할 필요가 없습니다.
     ```Dockerfile
     FROM python:3.11-slim
     WORKDIR /app
     ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
     COPY requirements.txt .
     RUN pip install --upgrade pip && pip install -r requirements.txt
     COPY app /app/app
     CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
     ```
   - 프런트 배포는 `npm ci --prefix frontend && npm run build --prefix frontend` 후 `aws s3 sync frontend/dist s3://tradar-frontend-prod --delete` 순서로 별도 워크플로우에서 수행합니다.
   - 백엔드 이미지는 평소와 같이 `docker build -t tradar-backend:latest .` → `docker tag` → `docker push` 순서로 ECR에 업로드합니다.

6. **ECS (Fargate) + ALB**
   - 클러스터: `tradar-cluster`.
   - Task Definition: 1 컨테이너(`uvicorn app.main:app --host 0.0.0.0 --port 8000`), CPU/메모리는 LangGraph 사용량(예: 2vCPU/4GB) 기준으로 조정.
   - 환경 변수/시크릿: Parameter Store 값을 Task Definition에 매핑합니다 (다음 표 참고).
   - 서비스: ALB 타깃 그룹(포트 8000)과 연결하고, 최소 2개의 Fargate 태스크로 구성해 무중단 배포를 준비합니다.

7. **Parameter Store**
   | 이름 | 예시 값 | 비고 |
   | --- | --- | --- |
| `/tradar/prod/database-url` | `postgresql://user:pass@tradar-db.cluster-xxx.ap-northeast-2.rds.amazonaws.com:5432/tradar` | SecureString |
| `/tradar/prod/opensearch-url` | `https://vpc-tradar-search-xxx.ap-northeast-2.es.amazonaws.com` | SecureString |
| `/tradar/prod/opensearch-username` | `tradar-opensearch` | (필요 시) Basic Auth |
| `/tradar/prod/opensearch-password` | `****` | Basic Auth 비밀번호 |
| `/tradar/prod/openai-api-key` | `sk-...` | SecureString |
| `/tradar/prod/kipris-access-key` | `...` | SecureString |
| `/tradar/prod/frontend-base-url` | `https://app.tradar.com` | CloudFront 배포 주소 |
| `/tradar/prod/cors-allowed-origins` | `https://app.tradar.com` | 백엔드 CORS 허용 Origin |

### 2.3 GitHub Actions용 IAM 사용자
- 이름: `tradar-github-actions`
- 필요한 권한: ECR 이미지 Push/Pull, ECS 서비스 업데이트, S3(프런트 배포), CloudFront 무효화, SSM Parameter Store 읽기, `iam:PassRole`.
- 아래 정책 JSON을 참고해 사용자나 역할에 연결하세요.
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAccess",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECSAccess",
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition"
      ],
      "Resource": [
        "arn:aws:ecs:ap-northeast-2:*:service/tradar-cluster/*",
        "arn:aws:ecs:ap-northeast-2:*:task-definition/tradar-*"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::tradar-frontend-*",
        "arn:aws:s3:::tradar-frontend-*/*"
      ]
    },
    {
      "Sid": "CloudFrontAccess",
      "Effect": "Allow",
      "Action": "cloudfront:CreateInvalidation",
      "Resource": "*"
    },
    {
      "Sid": "SSMAccess",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": "arn:aws:ssm:ap-northeast-2:*:parameter/tradar/*"
    },
    {
      "Sid": "IAMPassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::*:role/tradar-*"
    }
  ]
}
```

### 2.4 ECS Task Definition에 넣을 주요 환경 변수
| 이름 | 값 예시 | 설명 |
| --- | --- | --- |
| `APP_ENV` | `prod` | 배포 환경 스위치 |
| `DATABASE_URL` | Parameter Store 참조 | RDS 접속 URL |
| `OPENSEARCH_URL` | Parameter Store 참조 | Amazon OpenSearch 엔드포인트 |
| `OPENSEARCH_USERNAME` | Parameter Store 참조 | (선택) Basic Auth 사용자 |
| `OPENSEARCH_PASSWORD` | Parameter Store 참조 | (선택) Basic Auth 비밀번호 |
| `OPENAI_API_KEY` | Parameter Store 참조 | LangChain/LLM |
| `KIPRIS_ACCESS_KEY` | Parameter Store 참조 | KIPRIS REST |
| `CORS_ALLOWED_ORIGINS` | Parameter Store 참조 | 허용 Origin(`https://app.tradar.com`) |
| `TRADEMARK_LLM_MODEL` | `gpt-4o-mini` | 검색 프롬프트용 |
| `SIMULATION_LLM_MODEL` | `gpt-5-nano` | LangGraph 시뮬레이션용 |
| `MEDIA_ALLOWED_ROOTS` | `/data` | 컨테이너 내 허용 파일 루트 |
| `UVICORN_WORKERS`(선택) | `2` | 동시성 확장 |

---
## 3. CI/CD 파이프라인

### 3.1 전체 흐름
1. 개발자가 `main` 브랜치로 푸시하면 GitHub Actions가 실행됩니다.
2. 백엔드 워크플로우는 테스트 후 Docker 이미지를 빌드해 ECR에 푸시하고, ECS 서비스를 업데이트합니다.
3. 프런트엔드 워크플로우는 Vite 빌드를 만들어 S3에 업로드한 뒤 CloudFront 캐시를 무효화합니다.

### 3.2 Backend 워크플로우 초안
- 위치 제안: `.github/workflows/backend-deploy.yml`
- 권장 단계
  1. `actions/checkout`
  2. Python 의존성 설치 → `pytest`
  3. `aws-actions/configure-aws-credentials`
  4. Docker Build & Push (`docker/build-push-action`)
  5. 새 Task Definition을 렌더링(SSM Parameter → 환경 변수 매핑) 후 `aws ecs update-service --force-new-deployment`

### 3.3 Frontend 워크플로우 초안
- 위치 제안: `.github/workflows/frontend-deploy.yml`
- 권장 단계
  1. `actions/checkout`
  2. `npm ci`
  3. `npm run build`
  4. `aws s3 sync frontend/dist s3://tradar-frontend-prod --delete`
  5. `aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"`

### 3.4 GitHub Actions Secrets/Variables
| 이름 | 설명 |
| --- | --- |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | IAM 사용자 자격 증명 |
| `AWS_REGION` | 예: `ap-northeast-2` |
| `ECR_REGISTRY` | `<ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com` |
| `ECS_CLUSTER` | `tradar-cluster` |
| `ECS_SERVICE` | `tradar-backend-service` |
| `SSM_PATH_PREFIX` | `/tradar/prod` |
| `VITE_API_BASE_URL` | CloudFront → ALB URL, 프런트 빌드 시 주입 |

### 3.5 수동 배포 (비상 시)
```bash
# Backend
npm ci --prefix frontend && npm run build --prefix frontend
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com
docker build -t tradar-backend:latest -f Dockerfile.prod .
docker tag tradar-backend:latest <ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com/tradar-backend:latest
docker push <ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com/tradar-backend:latest
aws ecs update-service --cluster tradar-cluster --service tradar-backend-service --force-new-deployment

# Frontend
cd frontend
npm install
npm run build
aws s3 sync dist/ s3://tradar-frontend-prod --delete
aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/*"
```

---
## 4. 문제 해결

### 4.1 로컬 환경 이슈
| 증상 | 확인 방법 |
| --- | --- |
| FastAPI가 부팅되지 않고 `psycopg` 오류 발생 | `pip install "psycopg[binary]" pgvector` 설치 여부 확인 |
| `DATABASE_URL` 미설정 오류 | `.env` 또는 현재 셸에 `DATABASE_URL`이 있는지 확인 (`echo $DATABASE_URL`) |
| OpenSearch 연결 실패 | `curl $OPENSEARCH_URL/_cluster/health?pretty` 로 상태 확인, 필요한 경우 `scripts/bootstrap_seed.sh`로 재시작 |
| 시뮬레이션이 대기 상태에서 멈춤 | 백엔드 터미널 로그(`simulation` 로거) 확인, `logs/simulation_debug`로 최근 작업 조사 |
| 프런트가 API에 연결되지 않음 | `frontend/vite.config.js` 프록시 또는 `VITE_API_BASE_URL` 환경 변수 재확인 |

### 4.2 AWS 환경 이슈
| 증상 | 해결 가이드 |
| --- | --- |
| ECS 태스크 반복 실패 | `aws ecs describe-tasks`로 최근 태스크 ID 확인 → CloudWatch Logs(`/ecs/tradar-backend`)에서 Python 스택트레이스 확인 → Parameter Store 값/시크릿 권한 점검 |
| RDS 접속 불가 | RDS SG에 ECS SG가 5432 포트로 허용되어 있는지 확인, RDS 파라미터 그룹에 `vector`가 활성화됐는지 확인 |
| OpenSearch 타임아웃 | 도메인 용량(CPU/메모리) 또는 VPC 서브넷 라우팅 확인, 인덱스 새로 고침은 `scripts/sync_opensearch.sh`를 bastion에서 실행 |
| Parameter Store 접근 거부 | Task Role에 `ssm:GetParameter*` 권한이 있는지 재확인 |
| CloudFront가 예전 프런트를 보여 줌 | `aws cloudfront create-invalidation --paths "/*"` 명령으로 캐시 즉시 무효화 |

### 4.3 참고 문서
- `README_dev.md`: 멀티모달 검색/시뮬레이션 파이프라인 심화 설명
- `markdown/search-pipeline.md`: pgvector + OpenSearch 검색 로직
- `markdown/agent_simulation.md`: LangGraph 기반 시뮬레이션 동작
- `markdown/session-bootstrap.md`: WSL/KT Cloud 세션 부팅 자동화

---
필요한 항목만 골라서 진행해도 괜찮습니다. 위 순서를 그대로 따르면 "로컬에서 테스트 → AWS 인프라 구성 → GitHub Actions 자동 배포"까지 한 눈에 파악할 수 있도록 구성했습니다.
