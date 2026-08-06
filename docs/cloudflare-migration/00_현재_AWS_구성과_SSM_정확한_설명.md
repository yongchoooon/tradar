# 00. 현재 AWS 구성과 SSM의 정확한 의미

> 기준일: 2026-08-06
> 근거: 사용자가 제공한 AWS 작업 기록과 현재 repository
> 주의: 이 문서는 AWS 계정의 실시간 조회 결과가 아니다. 삭제 전 콘솔 또는 정상 인증된 AWS CLI로 존재 여부를 다시 확인한다.

## 1. 먼저 바로잡는 표현

“ECS가 `/tradar/prod/*`를 사용한다”는 표현은 너무 뭉뚱그려져 있었다. 정확한 표현은 다음과 같다.

> `/tradar/prod/...`는 **AWS Systems Manager Parameter Store에 저장된 parameter 이름의 계층형 prefix**다. ECS의 폴더나 컨테이너 내부 경로가 아니다.

예를 들어 다음은 서로 다른 Parameter Store 항목이다.

```text
/tradar/prod/database-url
/tradar/prod/openai-api-key
/tradar/prod/desktop-worker-token
```

IAM 정책의 다음 resource는 `/tradar/prod/` 아래 parameter들을 읽을 수 있게 허용한다는 뜻이다.

```text
arn:aws:ssm:ap-northeast-2:<AWS_ACCOUNT_ID>:parameter/tradar/prod/*
```

여기서 `*`는 실제 parameter 이름이 아니라 IAM wildcard다.

## 2. 이 프로젝트에는 SSM을 읽는 경로가 두 개 있다

### 경로 A: ECS가 task 시작 시 secret을 환경 변수로 주입

현재 `ecs/task-definition.json`에는 다음 구조가 있다.

```text
Parameter Store
  -> ECS task definition의 containerDefinitions[].secrets[].valueFrom
  -> ecsTaskExecutionRole 권한으로 ECS agent가 값을 조회
  -> 컨테이너 환경 변수 DATABASE_URL, OPENAI_API_KEY 등으로 주입
```

확인된 파일 위치:

- `ecs/task-definition.json:8`: `executionRoleArn`
- `ecs/task-definition.json:23-74`: Parameter Store parameter를 참조하는 `secrets`

따라서 이 경로에서는 애플리케이션 Python 코드가 값을 직접 읽는 것이 아니라, ECS가 task를 시작하면서 환경 변수로 전달한다. 이때 사용하는 주체는 **task execution role**이다.

### 경로 B: 실행 중인 애플리케이션이 boto3로 직접 조회

현재 애플리케이션에는 별도의 runtime 조회 코드도 있다.

```text
FastAPI 애플리케이션
  -> app/services/ssm_params.py
  -> boto3 SSM get_parameter
  -> tradar-ecs-task-role 권한 사용
```

관련 파일:

- `app/services/ssm_params.py:26-32`: `APP_ENV=prod`이면 SSM 조회 활성화
- `app/services/ssm_params.py:49-53`: `get_parameter(..., WithDecryption=True)`
- `app/services/worker_settings.py:54-76`: desktop worker token, timeout, top-k, worker allowlist 조회

이 코드에서는 환경 변수가 먼저 있으면 환경 변수를 사용하고, 없을 때 SSM을 조회한다. 이 경로의 AWS 권한은 컨테이너의 **task role**이 제공한다.

### 두 IAM role의 차이

| Role | 사용 주체 | 이 프로젝트에서의 역할 |
|---|---|---|
| `ecsTaskExecutionRole` | ECS/Fargate agent | ECR image pull, 로그, task definition에 선언된 SSM secret 주입 |
| `tradar-ecs-task-role` | 컨테이너 안 애플리케이션 | boto3를 통한 runtime SSM 조회 등 |

따라서 두 role에 SSM 권한이 모두 있었던 것은 서로 다른 접근 경로 때문일 수 있다. 다만 `tradar-ecs-task-role`에 `AmazonECSTaskExecutionRolePolicy`까지 붙인 것은 일반적인 역할 분리 기준상 불필요할 가능성이 있으며, 삭제 전 정리 대상이므로 지금 수정할 필요는 없다.

## 3. GitHub Actions와 SSM의 관계

제공된 IAM custom policy에는 GitHub Actions용 user가 SSM을 읽을 수 있는 권한이 있다. 그러나 **현재 repository의 GitHub Actions workflow는 SSM API를 호출하지 않는다.**

- `.github/workflows/backend-deploy.yml`: ECR push, task definition 배포, ECS service update
- `.github/workflows/frontend-deploy.yml`: S3 upload, CloudFront invalidation

즉 “권한이 있다”와 “실제로 사용한다”는 다르다. 현재 코드 근거로는 GitHub Actions가 `/tradar/prod/*` 값을 직접 읽는다고 말할 수 없다.

## 4. 사용자 기록으로 다시 정리한 AWS 상태

다음은 실시간 상태가 아니라 제공된 기록의 의미를 정리한 것이다.

### 기록상 이미 삭제됨

| 리소스 | 기록상 이름 | 처리 |
|---|---|---|
| Amazon OpenSearch Service domain | `tradar-opensearch` | 다시 삭제하지 말고 없음만 확인 |
| RDS PostgreSQL | `tradar-db` | 다시 삭제하지 말고 없음만 확인 |
| NAT Gateway | `tradar-regional-nat` | 없음과 연결 EIP 잔존 여부 확인 |

### 기록상 생성되어 있었고 현재 존재 여부를 확인해야 함

| 서비스 | 기록상 리소스 |
|---|---|
| ECS | `tradar-cluster`, `tradar-backend-svc`, `tradar-backend` task definition |
| ECR | `tradar-backend` |
| Load Balancing | `tradar-alb`, `tradar-backend-tg` |
| CloudFront | frontend용 `tradar-frontend-cf`, API용 `tradar-api-cf`의 **2개 distribution** |
| S3 | `tradar-frontend`, `tradar-data` |
| SSM Parameter Store | `/tradar/prod/` 아래 개별 parameter들 |
| CloudWatch Logs | `/ecs/tradar-backend` |
| VPC | `tradar-vpc`, public/private subnet, route table, IGW, security group, ENI/EIP 가능성 |
| IAM | 사람/Actions/desktop worker user, ECS execution/task role, inline/custom policy |

### 기록상 만들지 않았거나 제거했을 가능성이 큼

- SQS queue 두 항목은 취소선으로 표시되어 있다. queue가 실제로 존재한다고 가정하지 말고 조회 후 없으면 건너뛴다.
- `tradar-onprem-worker` IAM user도 취소선이다. 대신 `tradar-desktop-worker`가 기록되어 있으므로 둘을 혼동하지 않는다.
- SQS용 custom IAM policy는 queue와 별개로 남아 있을 수 있으므로 IAM에서 확인한다.

## 5. “OpenSearch domain”은 인터넷 도메인이 아니다

AWS 콘솔의 `tradar-opensearch` **domain**은 OpenSearch Service cluster를 부르는 AWS 용어다. Route 53 hosted zone이나 웹사이트 도메인 등록과는 관계가 없다.

제공된 기록에는 Route 53 hosted zone 또는 Route 53 Domains에서 도메인을 구입했다는 내용이 없다. 현재 확인되는 주소도 CloudFront 기본 도메인이다. 따라서 문서의 Route 53 단계는 **존재 여부를 한 번 조회하고, 없으면 전부 건너뛰는 조건부 단계**다.

Cloudflare Pages의 `pages.dev` 주소만 사용할 때는 개인 도메인이 없어도 된다. 반면 `api.example.com` 같은 고정 hostname으로 Cloudflare Tunnel을 운영하려면 Cloudflare에서 관리하는 실제 도메인이 필요하다.

## 6. 현재 기록을 반영한 삭제 순서

서비스 중단을 허용하더라도 secret 유출 대응과 데이터 보존은 별도 문제다.

1. GitHub의 기존 AWS 배포 workflow를 disable한다.
2. 노출된 machine access key를 즉시 비활성화/삭제하고, AWS 삭제 작업은 MFA가 설정된 관리자 세션으로 계속한다.
3. `tradar-data` S3 object 중 필요한 것과 로컬 DB/데이터를 백업한다.
4. ECS service desired count를 0으로 만들고 service/cluster를 삭제한다.
5. ALB/listener/target group을 삭제한다.
6. frontend/API CloudFront distribution 2개를 각각 disable 후 삭제한다.
7. ECR repository를 삭제한다.
8. 필요한 데이터를 검증한 뒤 `tradar-frontend`, `tradar-data` bucket을 비우고 삭제한다.
9. CloudWatch log와 `/tradar/prod/` SSM parameter를 삭제한다. SSM은 새 로컬 환경 변수 구성이 끝난 뒤 삭제한다.
10. VPC의 ENI, security group, subnet, route table, IGW를 의존 관계에 맞춰 삭제한다. NAT Gateway는 기록상 삭제됐으므로 EIP만 확인한다.
11. 남은 ECS IAM role, policy, user를 삭제한다. 단, 노출된 access key 자체는 2단계에서 먼저 폐기한다.
12. 모든 리전과 global service, Billing/Cost Explorer에서 잔존 리소스를 다시 확인한다.

RDS/OpenSearch/NAT는 “삭제 실행” 목록이 아니라 “정말 없는지 확인” 목록으로 변경한다. Route 53과 SQS도 조회 결과가 없으면 건너뛴다.

## 7. 보안상 즉시 조치

공유된 기록에는 실제 형식의 AWS access key와 여러 서비스 secret이 포함되어 있다. 값이 아직 유효한지와 무관하게 **모두 노출된 것으로 간주**한다.

- 공개 ChatGPT share link를 비공개 처리하거나 삭제한다.
- AWS machine user access key를 비활성화한 뒤 삭제한다.
- GitHub repository의 기존 AWS secrets를 삭제한다.
- OpenAI/Gemini/Hugging Face/KIPRIS key를 각 제공자에서 재발급한다.
- desktop worker token, admin password, cookie secret을 새 값으로 교체한다.
- 기존 값을 새 문서나 `.env.example`에 복사하지 않는다.

AWS Parameter Store 항목을 삭제하는 것만으로 외부 API key가 무효화되지는 않는다. 반드시 발급 서비스에서 revoke/rotate해야 한다.

## 8. 공식 참고 문서

- AWS Systems Manager Parameter Store: <https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html>
- Parameter Store hierarchy: <https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-hierarchies.html>
- ECS task definition secret: <https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_Secret.html>
- ECS task IAM role: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html>
