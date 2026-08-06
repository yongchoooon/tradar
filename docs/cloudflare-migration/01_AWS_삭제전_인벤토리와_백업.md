# 01. AWS 삭제 전 인벤토리와 백업

## 목적

AWS를 먼저 삭제하는 전환 방식에서 복구할 수 없는 데이터와 secret을 잃지 않도록 한다. 이 문서에서는 **조회와 백업만 수행**하고 실제 삭제는 [02 AWS 리소스 삭제 런북](./02_AWS_리소스_삭제_런북.md)에서 수행한다.

현재 구성과 `/tradar/prod/*`의 의미는 먼저 [00 현재 AWS 구성과 SSM의 정확한 설명](./00_현재_AWS_구성과_SSM_정확한_설명.md)을 읽는다. 사용자 기록상 RDS `tradar-db`, OpenSearch Service domain `tradar-opensearch`, NAT Gateway `tradar-regional-nat`는 이미 삭제됐다. 이 세 항목은 존재하지 않음을 확인하고, 없으면 삭제 단계에서 건너뛴다.

> 보안 경고: 제공된 작업 기록에 credential과 secret이 포함되어 있다. 노출된 machine access key와 외부 API key는 백업해서 재사용하지 말고 즉시 revoke/rotate한다. 삭제 작업은 MFA가 설정된 관리자 콘솔 세션 또는 새 임시 credential로 수행한다.

## 1. AWS CLI 실행 환경 확인

```bash
aws --version
aws sts get-caller-identity
aws configure get region
```

반드시 삭제할 AWS account ID와 로그인한 account ID가 같은지 확인한다. 출력은 문서에 붙이지 말고 로컬 보안 폴더에 저장한다.

```bash
export AWS_REGION=ap-northeast-2
export AWS_PAGER=""

aws sts get-caller-identity
```

권장 백업 디렉터리:

```bash
export MIGRATION_DIR="$HOME/tradar-migration-$(date +%Y%m%d)"
mkdir -p "$MIGRATION_DIR"/{aws-inventory,secrets,db,s3,checksums}
chmod 700 "$MIGRATION_DIR" "$MIGRATION_DIR/secrets"
```

이 디렉터리는 Git repository 밖에 둔다.

## 2. 배포 자동화부터 동결

삭제 작업 중 GitHub Actions가 리소스를 다시 생성하거나 ECS를 다시 배포하지 않도록 한다.

대상 workflow:

```text
.github/workflows/frontend-deploy.yml
.github/workflows/backend-deploy.yml
```

권장 방법:

1. GitHub Actions에서 진행 중인 두 workflow를 취소한다.
2. repository Settings에서 Actions workflow를 Disable한다.
3. 코드에서는 workflow를 `workflow_dispatch` 전용으로 바꾸거나 후속 구현 commit에서 제거한다.
4. 기록에 노출된 GitHub Actions AWS access key는 즉시 비활성화/삭제한다. AWS 정리 작업에는 MFA 관리자 세션 또는 별도의 새 임시 credential을 사용한다.

확인:

- [ ] 실행 중인 frontend/backend deploy 없음
- [ ] `main` push가 AWS deploy를 발생시키지 않음
- [ ] 삭제 중 ECR/ECS/S3가 다시 생성되지 않음

## 3. 모든 리전과 global 서비스 조회

활성 리전 목록:

```bash
aws ec2 describe-regions \
  --query 'Regions[].RegionName' \
  --output text | tr '\t' '\n' \
  | tee "$MIGRATION_DIR/aws-inventory/regions.txt"
```

T-RADAR는 레포상 `ap-northeast-2`를 사용하지만 다른 리전의 테스트 리소스도 확인한다. 다음은 서울 리전 기본 조회다.

```bash
aws ecs list-clusters --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/ecs-clusters.json"

aws ecr describe-repositories --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/ecr.json"

aws elbv2 describe-load-balancers --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/load-balancers.json"

aws elbv2 describe-target-groups --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/target-groups.json"

aws ec2 describe-nat-gateways --region "$AWS_REGION" \
  --filter Name=state,Values=available,pending \
  > "$MIGRATION_DIR/aws-inventory/nat-gateways.json"

aws ec2 describe-addresses --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/elastic-ips.json"

aws ec2 describe-vpc-endpoints --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/vpc-endpoints.json"

aws ec2 describe-instances --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/ec2.json"

aws rds describe-db-instances --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/rds.json"

aws opensearch list-domain-names --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/opensearch-domains.json"
```

Global/별도 범위 서비스:

```bash
aws cloudfront list-distributions \
  > "$MIGRATION_DIR/aws-inventory/cloudfront.json"

aws s3api list-buckets \
  > "$MIGRATION_DIR/aws-inventory/s3-buckets.json"

aws route53 list-hosted-zones \
  > "$MIGRATION_DIR/aws-inventory/route53-hosted-zones.json"

aws route53domains list-domains --region us-east-1 \
  > "$MIGRATION_DIR/aws-inventory/route53-registered-domains.json"

aws iam list-users \
  > "$MIGRATION_DIR/aws-inventory/iam-users.json"

aws iam list-roles \
  > "$MIGRATION_DIR/aws-inventory/iam-roles.json"

aws logs describe-log-groups --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/log-groups.json"

aws ssm describe-parameters --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/ssm-parameters.json"

aws secretsmanager list-secrets --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/secrets-manager.json"

aws acm list-certificates --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/acm-regional.json"

aws acm list-certificates --region us-east-1 \
  > "$MIGRATION_DIR/aws-inventory/acm-us-east-1.json"
```

CloudFront용 ACM 인증서는 일반적으로 `us-east-1`에 있을 수 있으므로 서울 리전만 보지 않는다.

## 4. ECS 실제 연결 관계 기록

```bash
export ECS_CLUSTER=tradar-cluster
export ECS_SERVICE=tradar-backend-svc

aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/ecs-service-detail.json"
```

다음 항목을 기록한다.

- task definition ARN
- desired/running count
- load balancer target group ARN
- subnet과 security group
- service discovery 여부
- capacity provider

Task definition:

```bash
TASK_DEF_ARN=$(aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query 'services[0].taskDefinition' --output text)

aws ecs describe-task-definition \
  --task-definition "$TASK_DEF_ARN" \
  --region "$AWS_REGION" \
  > "$MIGRATION_DIR/aws-inventory/task-definition.json"
```

Task definition에는 secret의 실제 값이 아니라 SSM ARN이 있으므로 secret 값은 별도로 export해야 한다.

`/tradar/prod/*`는 파일 경로가 아니라 Parameter Store 이름 prefix다. task definition의 `secrets[].valueFrom`으로 참조된 값은 ECS가 task 시작 시 `ecsTaskExecutionRole` 권한으로 읽어 환경 변수에 주입한다. 별도로 `worker_settings.py`는 환경 변수가 없을 때 `tradar-ecs-task-role` 권한으로 일부 worker 설정을 runtime 조회한다.

## 5. 로컬 PostgreSQL 백업

현재 컨테이너 확인:

```bash
cd ~/workspace/tradar
docker compose ps db
```

레포 스크립트 우선 사용:

```bash
bash scripts/backup_postgresql_data.sh
```

직접 dump가 필요하면 실제 container와 credential에 맞춰 실행한다.

```bash
docker compose exec -T db \
  pg_dump -U postgres -d tradar -Fc \
  > "$MIGRATION_DIR/db/tradar.dump"

sha256sum "$MIGRATION_DIR/db/tradar.dump" \
  | tee "$MIGRATION_DIR/checksums/tradar.dump.sha256"
```

검증:

```bash
pg_restore --list "$MIGRATION_DIR/db/tradar.dump" | head
```

`pg_restore --list` 성공만으로 완전한 복구 테스트를 대신할 수 없다. 가능하면 별도 테스트 DB에 실제 restore한다.

## 6. OpenSearch 보존 판단

```bash
curl -fsS http://127.0.0.1:9200/_cluster/health?pretty \
  | tee "$MIGRATION_DIR/aws-inventory/local-opensearch-health.json"

curl -fsS 'http://127.0.0.1:9200/_cat/indices?format=json' \
  | tee "$MIGRATION_DIR/aws-inventory/local-opensearch-indices.json"
```

판단:

- PostgreSQL/원본 JSON에서 `scripts/sync_opensearch.sh`로 재생성 가능: index 목록과 재생성 절차만 보존 가능
- OpenSearch에만 존재하는 데이터가 있음: snapshot repository 구성 후 snapshot 필요

Docker volume 디렉터리를 실행 중인 OpenSearch에서 단순 복사하는 것은 일관된 snapshot으로 간주하지 않는다.

## 7. `~/workspace/tradar-data` 백업

```bash
du -sh ~/workspace/tradar-data
find ~/workspace/tradar-data -type f | wc -l
```

별도 디스크가 있다면:

```bash
rsync -aH --info=progress2 \
  ~/workspace/tradar-data/ \
  /path/to/backup/tradar-data/
```

중요 manifest 예시:

```bash
find ~/workspace/tradar-data -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$MIGRATION_DIR/checksums/tradar-data.sha256"
```

대용량 데이터에서는 manifest 생성 시간이 오래 걸릴 수 있으므로 최소한 파일 수, 총 용량, 핵심 파일 checksum을 기록한다.

## 8. S3 bucket별 보존 여부 결정

버킷 목록과 리전을 확인한다.

```bash
aws s3api list-buckets --query 'Buckets[].Name' --output text | tr '\t' '\n'
```

각 bucket에 대해:

```bash
export BUCKET=<bucket-name>

aws s3api get-bucket-location --bucket "$BUCKET"
aws s3api get-bucket-versioning --bucket "$BUCKET"
aws s3api get-object-lock-configuration --bucket "$BUCKET" 2>/dev/null || true
aws s3 ls "s3://$BUCKET" --recursive --summarize
```

분류표:

| 종류 | 예 | 보존 판단 |
|---|---|---|
| frontend build | `tradar-frontend` | Git에서 재빌드 가능하므로 일반적으로 불필요 |
| 질의 이미지 | `queries/...` | 사용자 기록이 필요하면 복사 |
| search/simulation log | `logs/...` | 연구/감사에 필요하면 복사 |
| 원본 dataset | 대용량 상표 이미지 | 로컬 원본과 동일한지 검증 후 결정 |

로컬 백업 예시:

```bash
mkdir -p "$MIGRATION_DIR/s3/$BUCKET"
aws s3 sync "s3://$BUCKET" "$MIGRATION_DIR/s3/$BUCKET"
```

R2가 이미 준비됐다면 R2로 복사할 수 있지만, 삭제 우선 전략에서는 먼저 로컬로 내려받아도 된다.

## 9. SSM/Secrets Manager 값 보존

`ecs/task-definition.json`에서 확인되는 주요 값:

- Hugging Face token
- `DATABASE_URL`
- `OPENSEARCH_URL`
- OpenAI/Gemini/KIPRIS key
- LLM model 설정
- admin password/cookie secret
- desktop worker token
- CORS origin

Parameter 이름 조회:

```bash
aws ssm get-parameters-by-path \
  --path /tradar/prod \
  --recursive \
  --with-decryption \
  --region "$AWS_REGION" \
  > "$MIGRATION_DIR/secrets/ssm-tradar-prod.json"

chmod 600 "$MIGRATION_DIR/secrets/ssm-tradar-prod.json"
```

이 JSON은 평문 secret을 포함한다. 공유하거나 Git에 커밋하지 않는다. 새 로컬 `.env`에 필요한 값을 옮긴 뒤 원본 export 파일을 암호화하거나 안전하게 제거한다.

Secrets Manager를 실제 사용한다면 secret별로 `get-secret-value`를 수행한다. `list-secrets`는 secret 본문을 반환하지 않는다.

## 10. Route 53 domain과 DNS 확인 — 존재할 때만

제공된 기록에는 Route 53 사용 내역이 없다. `tradar-opensearch`의 “domain”은 OpenSearch Service cluster 이름이며 DNS domain이 아니다. 다음 조회 결과가 비어 있으면 이 절 전체를 건너뛴다.

`hosted zone`과 `domain registration`은 서로 다른 리소스다.

- Hosted zone: DNS record를 관리하며 월 비용이 발생할 수 있음
- Domain registration: 도메인 소유권/갱신을 관리

확인:

```bash
aws route53 list-hosted-zones
aws route53domains list-domains --region us-east-1
```

Route 53에 domain이 등록되어 있다면 AWS account나 domain registration을 먼저 닫지 않는다. Cloudflare DNS zone을 만든 뒤 registrar의 nameserver를 Cloudflare nameserver로 바꾸고 DNS 전파를 확인한다. AWS 자체를 완전히 사용하지 않으려면 이후 다른 registrar로 domain registration도 이전한다.

기존 DNS record export:

```bash
export HOSTED_ZONE_ID=<hosted-zone-id>
aws route53 list-resource-record-sets \
  --hosted-zone-id "$HOSTED_ZONE_ID" \
  > "$MIGRATION_DIR/aws-inventory/route53-records.json"
```

## 11. 삭제 승인표

실제 삭제 전에 다음 표를 채운다.

| 리소스 | 식별자 | 보존 데이터 | 삭제 승인 | 비고 |
|---|---|---|---|---|
| ECS service | `tradar-backend-svc` | 없음 | [ ] | 로컬 API로 대체 |
| ECR | `tradar-backend` | 이미지 | [ ] | Git/Dockerfile로 재생성 |
| CloudFront frontend | `tradar-frontend-cf`의 실제 ID | 설정 export | [ ] | disable 후 삭제 |
| CloudFront API | `tradar-api-cf`의 실제 ID | 설정 export | [ ] | disable 후 삭제 |
| frontend S3 | `tradar-frontend` | 불필요 | [ ] | Git에서 재빌드 |
| data S3 | `tradar-data` | 필요 여부 | [ ] | 복사 완료 확인 |
| ALB/target group | `tradar-alb` / `tradar-backend-tg` | 없음 | [ ] | ECS 삭제 후 |
| NAT/EIP | NAT는 기록상 삭제 | 없음 | [ ] | NAT 없음과 EIP 잔존 확인 |
| RDS/OpenSearch | 기록상 삭제 | 없음 | [ ] | 없음만 확인 |
| SSM | `/tradar/prod/` 아래 parameter | 필요한 설정만 새 값으로 구성 | [ ] | 로컬 env 이전 후 |
| SQS | 기록상 생성 취소 | 없음 | [ ] | 조회 결과가 없으면 건너뜀 |
| Route 53 | 사용 근거 없음 | 해당 시 DNS/domain | [ ] | 조회 결과가 없으면 건너뜀 |

## 12. 완료 조건

- [ ] AWS account ID를 확인했다.
- [ ] 모든 사용 리전과 global 서비스 인벤토리를 저장했다.
- [ ] GitHub AWS 자동 배포를 중지했다.
- [ ] PostgreSQL dump와 checksum이 있다.
- [ ] `tradar-data`의 별도 백업 또는 보존 결정을 완료했다.
- [ ] 필요한 S3 object를 복사했다.
- [ ] SSM/Secrets 값을 안전하게 export했다.
- [ ] Route 53 domain/DNS 상태를 확인했다.
- [ ] 리소스별 삭제 승인표를 작성했다.
