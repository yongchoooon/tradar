# T-RADAR 프로젝트 인프라 & CI/CD 가이드라인

> 이 문서는 **“처음 AWS/CI/CD를 접하는 사람”**을 기준으로  
> T-RADAR 프로젝트의 로컬 개발 환경, AWS 인프라, CI/CD 개념을 한 번에 이해할 수 있도록 정리한 가이드입니다.  
> **현재 운영 검색은 데스크톱 GPU 워커 + 로컬 Postgres/OpenSearch로 오프로딩**하며,
> RDS/OpenSearch Service 관련 섹션은 **클라우드로 검색 인프라를 옮길 때 참고용**입니다.

---

## 0. 전체 구조 한눈에 보기

T-RADAR는 크게 세 레벨로 나뉩니다.

1. **로컬 개발 환경** (Docker, Make)
2. **AWS 인프라** (S3, CloudFront, ECS/Fargate, ALB 등) + **데스크톱 GPU 워커(WebSocket)**  
   *(RDS/OpenSearch Service는 검색 인프라를 클라우드로 옮길 때 선택)*
3. **CI/CD 파이프라인** (GitHub Actions → AWS)

대략적인 그림은 다음과 같습니다.

```text
[로컬 개발 환경]
  개발자 PC
   ├─ Docker (backend, frontend, postgres, opensearch)
   ├─ Make (make up, make migrate-up 등)
   └─ OpenAI / KIPRIS 키를 .env에 설정

[원격 프로덕션 환경 (AWS)]
  프론트엔드: S3 버킷 + CloudFront (+ 선택적으로 Route 53)
  백엔드: ECR(이미지 저장소) + ECS(Fargate로 컨테이너 실행) + ALB(로드밸런서)
  검색 실행: 데스크톱 GPU 워커(WebSocket, outbound) + 로컬 Postgres/pgvector + OpenSearch
  이미지: S3 presigned 업로드
  설정/비밀값: SSM Parameter Store
  (선택) 검색 인프라를 클라우드로 옮길 경우 RDS/OpenSearch Service 사용

[CI/CD]
  GitHub Repo에 push
    → GitHub Actions 실행
      → Backend: 테스트, Docker 빌드, ECR 푸시, ECS 배포
      → Frontend: 빌드, S3 업로드, CloudFront 캐시 무효화
```

---

## 1. 로컬 개발 환경

### 1.1 필수 소프트웨어

- **Docker Desktop 4.x 이상**
  - 컨테이너를 실행하는 기본 도구
- **Docker Compose v2.x 이상**
  - 여러 컨테이너(backend, frontend, postgres, opensearch)를 한 번에 띄우는 도구
- **Git 2.x 이상**
  - 코드 버전 관리, GitHub 연동
- **Make**
  - `make up`, `make migrate-up` 같은 단축 명령을 실행하는 도구  
  - 윈도우: Git Bash 또는 WSL2에서 사용

선택 (GPU 사용 시)

- NVIDIA Driver 525.x 이상
- NVIDIA Container Toolkit  
  → Docker 컨테이너에서 GPU에 접근할 수 있도록 해줌

---

### 1.2 프로젝트 클론

```bash
git clone https://github.com/your-org/tradar.git
cd tradar
```

---

### 1.3 환경 설정

1) **컨텍스트를 local로 설정**

```bash
make use-local
```

- 프로젝트가 `local`, `prod` 등 여러 환경별 설정을 가지고 있을 때,
- 지금부터는 **로컬 개발용 설정**을 사용하겠다고 스위치를 바꿔주는 명령입니다.  
- 내부적으로 `.local-debug/contexts/local/`의 설정을 사용하도록 연결합니다.

2) **환경변수 파일 편집**

```text
.local-debug/contexts/local/.env
```

다음 값을 실제 키로 채워 넣습니다.

- `OPENAI_API_KEY`: OpenAI API 키
- `KIPRIS_ACCESS_KEY`: KIPRIS API 키

이 키들은 **로컬에서 실제 OpenAI / KIPRIS 호출을 테스트**할 때 필요합니다.

---

### 1.4 서비스 시작 및 로그

#### 기본 서비스 시작

```bash
# backend, frontend, postgres, opensearch
make up
```

#### 개발 도구 포함 시작

```bash
# + pgAdmin, OpenSearch Dashboards
make up-tools
```

#### 상태 확인 및 로그

```bash
make status        # 컨테이너 상태
make logs-backend  # 백엔드 로그
make logs-frontend # 프론트엔드 로그
make logs-all      # 전체 로그
```

---

### 1.5 데이터베이스 마이그레이션

**마이그레이션(Migration)** = DB 스키마 변경을 코드로 관리하는 방식입니다.

```bash
# 아직 적용되지 않은 마이그레이션들을 모두 적용
make migrate-up

# 새 마이그레이션 생성
make migrate-create MSG="add_new_table"

# 마이그레이션 히스토리 확인
make migrate-history
```

---

### 1.6 로컬 접속 URL 정리

| 서비스                | URL                          | 설명                          |
|----------------------|-----------------------------|-------------------------------|
| Frontend             | http://localhost:5173       | 웹 UI                         |
| Backend API          | http://localhost:8000       | FastAPI 백엔드                |
| API Docs (Swagger)   | http://localhost:8000/docs  | 백엔드 API 문서 및 테스트     |
| pgAdmin              | http://localhost:5050       | PostgreSQL 웹 관리 도구       |
| OpenSearch Dashboards| http://localhost:5601       | OpenSearch 웹 UI              |
| OpenSearch API       | http://localhost:9200       | REST API (curl 테스트용)      |

---

## 2. AWS 인프라 개념 잡기

### 2.1 전체 아키텍처 개요

```text
┌─────────────────────────────────────────────────────────────────┐
│                         AWS Cloud                               │
├─────────────────────────────────────────────────────────────────┤
│   [프론트엔드]                                                   │
│     Route 53 (도메인) → CloudFront(CDN) → S3(tradar-frontend)   │
│                                                                 │
│   [백엔드]                                                       │
│     ECR(이미지 저장소) → ECS(Fargate 컨테이너) → ALB(HTTPS 443) │
│                              │                                  │
│                              ▼                                  │
│   [데이터]                                                       │
│     RDS(Postgres+pgvector)   OpenSearch Service(BM25+k-NN)      │
│                                                                 │
│   [구성/보안]                                                    │
│     VPC(사설 네트워크), Subnet, Security Group, Parameter Store │
└─────────────────────────────────────────────────────────────────┘
```

현재 운영에서는 위 `데이터` 블록 대신 **데스크톱 GPU 워커 + 로컬 Postgres/OpenSearch**가 검색을 수행하고,
ECS 백엔드는 `/ws/worker`로 작업을 위임합니다. RDS/OpenSearch Service 구성은 클라우드로 이전할 때만 사용하세요.

이제 하나씩 역할을 설명합니다.

---

### 2.2 S3 (Simple Storage Service)

#### S3 Bucket이란?

- **S3 = AWS의 파일 저장소 서비스 (Object Storage)** 입니다.
- 버킷(bucket)은 일종의 **최상위 폴더 이름**이라고 보면 됩니다.
  - 예: `tradar-frontend`, `tradar-dataset` 등

#### T-RADAR에서 S3의 역할

1. **프론트엔드 빌드 결과물 저장**
   - Vite/React로 빌드된 `dist/` 폴더 내용(HTML, JS, CSS, 이미지 등)을
   - S3 버킷(`tradar-frontend`)에 업로드합니다.
   - 이 정적 파일들은 CloudFront를 통해 전 세계에 빠르게 배포됩니다.

2. **대용량 검색용 이미지 저장**
   - 수 TB 규모의 상표 이미지 데이터도 S3에 저장 가능합니다.
   - 패턴:
     - 원본 이미지는 `s3://tradar-dataset/...` 에 저장
     - DB(OpenSearch/Postgres)에는
       - 이미지의 S3 경로(URL)
       - 메타데이터(상표명, NC, 등록/거절 여부 등)
       - 임베딩 벡터
     - 서비스에서 검색 결과를 보여줄 때 S3 경로를 참고하여 이미지를 로딩

#### S3는 무료인가?

- S3는 **유료 서비스**입니다.
- 비용은 리전과 스토리지 클래스에 따라 다르지만, 일반적인 S3 Standard 기준으로  
  대략 **1GB당 한 달에 약 0.02달러대** 수준입니다.
- 대략적인 감만 잡으면:
  - 1TB 저장: 한 달에 약 2~3만 원대
  - 5TB 저장: 한 달에 십여만 원대
- 자주 접근하지 않는 데이터는 Glacier/IA 같은 더 저렴한 스토리지 클래스를 사용해 비용을 줄일 수 있습니다.

#### 요약

- **프론트 빌드 결과물** + **대용량 이미지** 모두 S3에 두는 것이 일반적인 패턴입니다.
- S3는 “이미지/정적 파일을 위한 서비스용 클라우드 하드디스크”로 이해하면 됩니다.

---

### 2.3 CloudFront와 CDN, 그리고 FastAPI와의 차이

#### CDN이란?

- **CDN (Content Delivery Network)**:  
  전 세계 여러 지역에 파일 캐시 서버를 두고,  
  사용자에게 **가장 가까운 서버**에서 정적 파일을 내려주는 시스템입니다.
- 효과:
  - 응답 속도 향상
  - 트래픽 비용 최적화
  - 대규모 트래픽에도 안정적인 서비스

#### CloudFront란?

- AWS가 제공하는 CDN 서비스 이름이 **CloudFront**입니다.
- 역할:
  1. 사용자의 요청을 받아서
  2. S3(또는 다른 Origin)에서 파일을 가져와 캐시하고
  3. 다음 요청부터는 CloudFront 엣지 서버에서 바로 파일을 서빙합니다.

#### FastAPI와 비교

- **FastAPI**
  - 네가 직접 작성한 백엔드 애플리케이션 서버
  - DB 조회, 검색, 인증, 비즈니스 로직을 처리
- **CloudFront**
  - 정적 파일(JS, CSS, 이미지)을 빠르게 전달하는 “전달자”
  - 코드를 실행하지 않고, 파일만 캐싱/전달

정리하면:

- **SPA 프론트엔드 정적 파일** → S3 + CloudFront
- **API 서버(FastAPI)** → ECS(Fargate) + ALB

---

### 2.4 ECR (Elastic Container Registry)

- **Docker Hub의 AWS 버전**이라고 이해하면 됩니다.
- `tradar-backend` 라는 이름의 **이미지 저장소(repository)**를 만들고,
- GitHub Actions가 만든 Docker 이미지를 여기로 `push`합니다.
  - 예: `tradar-backend:latest`, `tradar-backend:v1.0.0` 등 태그

ECS/Fargate는 배포할 때 항상 **ECR에서 이미지를 가져와(pull)** 컨테이너를 실행합니다.

---

### 2.5 ECS, Fargate, 컨테이너 여러 개의 의미

#### Docker 컨테이너 vs ECS/Fargate

- **Docker 컨테이너**:  
  애플리케이션이 들어있는 “박스” 그 자체
- **ECS (Elastic Container Service)**:
  - 이 컨테이너들을 **몇 개 띄우고, 헬스체크하고, 죽으면 다시 띄우고, 스케일링**할지 관리하는 서비스
- **Fargate**:
  - 컨테이너를 실제로 실행하는 “서버 없는(serverless) 실행 엔진”
  - EC2 인스턴스를 직접 관리하지 않고,  
    “컨테이너 CPU/메모리만 지정하면 AWS가 알아서 서버를 준비해서 돌려주는 모드”

#### “ECS + Fargate에서 컨테이너를 여러 개 띄운다”는 말의 의미

- 예를 들어,
  - ECS Service 설정에 “이 백엔드 Task를 **3개 유지해줘**”라고 지정하면,
  - Fargate가 컨테이너 3개를 실행합니다.
  - ALB는 이 3개의 컨테이너에게 트래픽을 분산합니다.

이 구조의 장점:

1. **고가용성**
   - 하나의 컨테이너가 죽어도 나머지가 서비스 유지
2. **트래픽 분산**
   - 동시에 더 많은 요청 처리 가능
3. **무중단 배포**
   - 새 버전 컨테이너를 띄우고, 헬스체크가 통과되면 이전 버전을 하나씩 내리는 방식으로  
     다운타임 없이 롤링 업데이트 가능
4. **자동 스케일링**
   - “CPU 70% 넘으면 1개 더 늘려라” 같은 정책 설정 가능

#### T-RADAR에 필요한가?

- 초기에는 **Task 1개**만으로도 충분할 수 있습니다.
- 다만 **ECS/Fargate 구조를 잡아두면**,  
  나중에 트래픽이 늘었을 때 **Task 개수만 1 → 3**으로 늘리는 식으로 손쉽게 확장할 수 있습니다.

---

### 2.6 ALB (Application Load Balancer)

#### 왜 HTTPS 443 포트인가?

- HTTPS의 표준 포트가 **443**입니다.
- 브라우저, 방화벽, 회사 네트워크 모두 **443 = 안전한 웹 트래픽**으로 인식합니다.
- 전 세계 유저의 요청을 안전하게 받기 위한 기본값이라고 보면 됩니다.

#### ALB의 역할

- **역할**
  1. 외부에서 들어오는 HTTP/HTTPS 요청을 받는다.
  2. 뒤에 있는 여러 ECS/Fargate 컨테이너에 트래픽을 **분산**한다.
  3. 헬스체크를 통해 **죽은 컨테이너에는 트래픽을 보내지 않는다.**
  4. Host/Path 기반 라우팅 지원 (`api.tradar.com` → 백엔드 등)

- **실체**
  - AWS가 운영하는 L7 로드밸런서 서비스
  - 우리가 설정하는 것은:
    - 리스너(443 포트, 인증서)
    - 타겟 그룹(ECS 서비스)
  - 실제 서버 인프라는 AWS 쪽에서 관리

---

### 2.7 VPC, Subnet, Security Group

#### VPC (Virtual Private Cloud)

- AWS 안에서 **독립적인 네트워크 공간**을 만드는 것
- 예: `10.0.0.0/16` 대역을 내 프로젝트 전용으로 사용

#### Subnet

- VPC 안을 다시 잘게 나눈 네트워크 구역
  - Public Subnet: 인터넷과 직접 통신 가능한 구역 (ALB 등)
  - Private Subnet: 외부에서 직접 접속 불가능한 구역 (ECS, RDS, OpenSearch 등)

#### Security Group

- 일종의 **방화벽 규칙 묶음**
  - 예: `db-sg`는 ECS에서 오는 5432 포트만 허용
  - `backend-sg`는 ALB에서 오는 8000 포트만 허용

#### 왜 필요한가?

- **보안**
  - DB, 검색 서버를 외부와 완전히 분리
  - ALB, NAT 등을 통해서만 통신 가능하게 설정
- **구조화**
  - 서비스 아키텍처를 네트워크 레벨에서 명확히 나누어 관리
- **기업/서비스 간 격리**
  - 같은 리전 내에서도 VPC 단위로 각 프로젝트를 분리

---

### 2.8 RDS (PostgreSQL + pgvector) - 선택

- AWS의 관리형 데이터베이스 서비스.
- T-RADAR에서는:
  - 엔진: PostgreSQL
  - 확장: `pgvector` 활성화
    - 벡터 컬럼을 저장하고, 벡터 유사도 검색 지원
    - 텍스트/이미지 임베딩을 저장하는 데 사용

클라우드로 검색 인프라를 옮길 경우 RDS를 사용하면:
- 백업, 장애 조치, 모니터링 등을 AWS가 상당 부분 대신 처리해주기 때문에,
- 직접 EC2에 Postgres를 설치하는 것보다 운영 부담이 적습니다.

---

### 2.9 OpenSearch Service - 선택

- Elasticsearch 호환 검색엔진의 AWS 관리형 서비스.
- T-RADAR에서의 역할:
  - BM25 기반 텍스트 검색 (상표명, 설명 등)
  - k-NN 기반 벡터 검색 (이미지/텍스트 임베딩 기반 유사도 검색)
- 클러스터를 2노드 이상으로 구성해 고가용성 확보.

---

### 2.10 Parameter Store (SSM)

- DB URL, OpenAI API 키, KIPRIS 키 등 **비밀값/설정값**을 안전하게 저장하는 서비스.
- 예: `/tradar/prod/database-url`, `/tradar/prod/openai-api-key`
- ECS에서 Task 실행 시, 이 값을 읽어 환경변수로 주입해 사용할 수 있습니다.

---

## 3. IAM과 계정 구조

### 3.1 IAM이란?

- **IAM (Identity and Access Management)**  
  → “누가 무엇을 어디에서 할 수 있는지”를 정의하는 AWS의 권한 시스템입니다.

### 3.2 IAM User란?

- AWS 계정 안에서 사용하는 **사용자 계정**입니다.
- 실제 사람이 사용할 수도 있고, 프로그램(CI/CD, 서버 애플리케이션)이 사용할 수도 있습니다.
- 각 IAM User는:
  - 권한(Policy)
  - Access Key/Secret Key
  를 가질 수 있습니다.

### 3.3 사람 계정 vs GitHub Actions용 계정

보통 다음과 같이 분리하는 것을 권장합니다.

1. **사람용 계정 (예: `yongdeuk-admin`)**
   - AWS 콘솔(웹 사이트)에 로그인할 때 사용
   - 필요하다면 CLI에서 `aws configure`로 사용
   - 비교적 넓은 권한, MFA 등 보안 설정

2. **CI/CD용 계정 (예: `tradar-github-actions`)**
   - 콘솔에 직접 로그인하지 않고
   - Access Key/Secret Key만 발급해서 GitHub Actions에서 사용
   - 필요한 권한만 최소로 부여
     - ECR 이미지 푸시/풀
     - ECS 서비스 업데이트
     - S3 배포
     - CloudFront 캐시 무효화
     - SSM 파라미터 읽기 등

두 계정 모두 **같은 AWS Account의 리소스를 보고 조작**하게 됩니다.  
다만, 용도와 권한 범위가 다를 뿐입니다.

---

## 4. CI/CD 파이프라인 구조

### 4.1 전체 흐름

```text
GitHub main 브랜치에 push
  → GitHub Actions 워크플로우 실행
    → Backend:
        - pytest 실행
        - Docker 이미지 빌드
        - ECR에 push
        - ECS 서비스 업데이트 (새 버전 배포)
    → Frontend:
        - npm run build
        - dist/를 S3(tradar-frontend)에 sync
        - CloudFront 캐시 무효화
```

### 4.2 워크플로우 파일 위치

```text
.github/workflows/
  ├── backend-deploy.yml    # 백엔드 CI/CD
  ├── frontend-deploy.yml   # 프론트엔드 CI/CD
  └── db-migrate.yml        # DB 마이그레이션 (수동)
```

- 각 파일 안의 `on:` 설정에 따라
  - 예: `backend/**` 경로 변경 시에만 backend 배포
  - `frontend/**` 변경 시에만 frontend 배포
  같이 동작하도록 설정할 수 있습니다.

---

### 4.3 Backend CI/CD

1. 특정 브랜치/경로에 push 발생
2. **Test Job**
   - `pytest` 실행
   - 테스트 실패 시 이후 단계 중단
3. **Build Job**
   - Docker 이미지 빌드
   - ECR에 `tradar-backend:latest` 등으로 푸시
4. **Deploy Job**
   - ECS 서비스 업데이트 (`aws ecs update-service ...`)
   - 새 Task가 뜨고 헬스체크를 통과하면, 이전 Task를 내려 무중단 배포 수행

---

### 4.4 Frontend CI/CD

1. `frontend/**` 경로에 push 발생
2. **Build Job**
   - `npm install`
   - `npm run build` → `dist/` 생성
3. **Deploy Job**
   - `aws s3 sync dist/ s3://tradar-frontend --delete`
   - `aws cloudfront create-invalidation --paths "/*"`  
     → 캐시 무효화로 새 빌드 파일을 즉시 반영

---

### 4.5 GitHub Secrets 설정 (VITE_API_BASE_URL 포함)

GitHub Repository → Settings → Secrets and variables → Actions 에서 설정합니다.

대표적인 항목:

| Secret Name           | 설명                                   | 예시                                 |
|-----------------------|----------------------------------------|--------------------------------------|
| AWS_ACCESS_KEY_ID     | `tradar-github-actions` Access Key     | `AKIAXXXXXXXX`                       |
| AWS_SECRET_ACCESS_KEY | `tradar-github-actions` Secret Key     | `xxxxxxxx`                           |
| VITE_API_BASE_URL     | 프론트엔드 빌드 시 사용할 API 베이스 URL | `https://api.tradar.com` 또는 로컬 |

#### VITE_API_BASE_URL의 의미

- Vite는 `VITE_`로 시작하는 환경변수를 빌드 시 JS 코드에 주입합니다.
- 예:

```ts
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});
```

- 로컬 개발 시:
  - `VITE_API_BASE_URL = http://localhost:8000`
- 프로덕션:
  - `VITE_API_BASE_URL = https://api.tradar.com`

이렇게 하면 코드 수정 없이도  
**환경(로컬/스테이징/프로덕션)에 따라 API 서버 주소를 바꿀 수 있습니다.**

---

### 4.6 수동 배포 방법 (CI/CD 장애/초기 설정 시)

#### Backend 수동 배포

```bash
cd backend
docker build -t tradar-backend .

aws ecr get-login-password --region ap-northeast-2 \
  | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com

docker tag tradar-backend:latest <ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com/tradar-backend:latest
docker push <ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com/tradar-backend:latest

aws ecs update-service \
  --cluster tradar-cluster \
  --service tradar-backend-service \
  --force-new-deployment
```

#### Frontend 수동 배포

```bash
cd frontend
npm run build

aws s3 sync dist/ s3://tradar-frontend --delete
aws cloudfront create-invalidation \
  --distribution-id <DIST_ID> \
  --paths "/*"
```

---

## 5. 대용량 이미지 저장 전략 요약

- 수 TB 규모의 이미지 데이터가 있는 경우:
  - **서비스에서 바로 보여줘야 하는 이미지**  
    → S3 버킷(예: `tradar-images`)에 저장
  - DB/OpenSearch에는:
    - 이미지 S3 경로
    - 메타데이터
    - 임베딩 벡터
  - 필요 시 썸네일을 따로 생성해서 작은 파일만 서비스에 사용

- 비용이 부담되면:
  - 자주 쓰지 않는 데이터는 Glacier/IA 클래스로 옮기는 방식도 고민 가능
  - 학습/연구용 원본은 온프레미스/NAS + 서비스용 샘플/썸네일만 S3에 두는 하이브리드 구성도 가능

---

## 6. 자주 하는 질문 정리 (FAQ)

### Q1. S3에 수 TB 저장해도 되나? 얼마나 비싸나?

- 네, 충분히 가능합니다.
- 용량에 비례해서 과금되며, TB 단위로 저장해도 기술적으로 문제 없음.
- 수 TB를 장기 보관하면 매달 비용이 나가므로,
  - 자주 쓰는 데이터는 S3 Standard
  - 덜 쓰는 데이터는 더 저렴한 스토리지 클래스로 옮기는 식으로 최적화할 수 있습니다.

---

### Q2. Fargate에서 컨테이너를 여러 개 띄우는 게 왜 좋은가?

- 고가용성, 트래픽 분산, 무중단 배포, 자동 스케일링 때문입니다.
- 초기에는 **Task 1개**만 띄워도 되지만,
  - 구조를 ECS/Fargate로 가져가면
  - 나중에 컨테이너 개수만 늘려서 확장하기 쉬워집니다.

---

### Q3. GitHub Actions용 IAM User가 따로 필요한가?

- 네. 보통 다음처럼 나눕니다.
  - 사람용: 콘솔 로그인, CLI 사용 (`yongdeuk-admin`)
  - CI용: GitHub Actions에서만 사용 (`tradar-github-actions`)
- 둘은 같은 AWS 리소스를 보지만,  
  권한과 사용 방식이 다릅니다.

---

### Q4. “tradar-frontend”는 뭔가?

- S3 버킷 이름입니다.
- 로컬 폴더가 아니라, AWS S3 안에서 정적 프론트엔드 파일을 저장하는 **클라우드 폴더**입니다.

---

### Q5. AWS 콘솔이란?

- 브라우저에서 접속하는 AWS 관리 웹 사이트입니다.
- 주소: `https://console.aws.amazon.com/`
- 여기에서 S3 버킷, ECS 서비스, RDS 인스턴스 등을 클릭 몇 번으로 생성/설정/모니터링할 수 있습니다.

---

이 문서를 기반으로:

1. 로컬에서는 `make use-local`, `make up`, `make migrate-up`으로 개발 환경을 익히고,
2. AWS에서는 S3/CloudFront/ECS/Fargate/RDS/OpenSearch의 연결 구조를 큰 틀에서 이해하고,
3. GitHub Actions 설정 파일을 보면서  
   “아, 수동으로 했던 빌드/배포 작업을 여기서 자동으로 하고 있구나” 정도까지 연결되면  
T-RADAR 인프라/CI/CD의 전체 그림은 잡혔다고 보면 됩니다.
