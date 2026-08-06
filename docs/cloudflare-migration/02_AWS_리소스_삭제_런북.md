# 02. AWS 리소스 삭제 런북

## 목적과 핵심 순서

서비스 중단을 허용하고 AWS로 rollback하지 않는다는 전제에서 유료 리소스를 의존 관계에 맞춰 영구 삭제한다.

> 사용자 기록 반영: RDS `tradar-db`, OpenSearch Service domain `tradar-opensearch`, NAT Gateway `tradar-regional-nat`는 이미 삭제된 것으로 적혀 있다. 이들은 실제로 없으면 건너뛴다. Route 53은 사용 근거가 없고 SQS는 생성 항목이 취소선이므로 조회 결과가 있을 때만 처리한다.

> 보안 예외: IAM은 일반적으로 마지막에 삭제하지만, 이미 노출된 GitHub Actions/worker **access key는 가장 먼저 비활성화하고 삭제**한다. 실제 정리는 MFA 관리자 세션 또는 새 임시 credential로 수행한다.

```text
자동 배포 중단 및 노출된 machine key 폐기
  -> ECS service/task 중단 및 삭제
  -> ALB/listener/target group 삭제
  -> NAT 없음 확인, VPC endpoint/EIP 정리
  -> frontend/API CloudFront 2개 disable/delete
  -> ECR 삭제
  -> S3 object version 포함 삭제 후 bucket 삭제
  -> CloudWatch/SSM/Secrets/ACM/Route 53 정리
  -> VPC 정리
  -> IAM/GitHub AWS credential 마지막 삭제
  -> 비용 및 모든 리전 재점검
```

## 1. 왜 이 순서인가

### ECS를 먼저 삭제하는 이유

ECS가 살아 있으면 새 task가 ECR image, subnet, security group, target group을 계속 참조한다. ECS service 삭제 후에도 ALB/target group은 자동 삭제되지 않으므로 별도로 삭제해야 한다.

### ALB와 NAT를 빠르게 삭제하는 이유

Task가 없어도 ALB와 NAT Gateway는 독립 리소스로 남을 수 있다. NAT Gateway 삭제 후 연결됐던 Elastic IP도 자동 release되지 않으므로 따로 release한다.

### CloudFront를 S3보다 먼저 삭제하는 이유

CloudFront가 S3 origin/OAC/OAI를 참조할 수 있다. distribution은 먼저 disable하고 배포 완료를 기다린 다음 삭제한다. 그 뒤 frontend bucket을 비운다.

### IAM을 마지막에 삭제하는 이유

ECS, ECR, S3, CloudFront, VPC를 삭제할 권한이 필요하다. IAM user/key/role을 먼저 삭제하면 나머지 정리 작업을 수행할 수 없게 된다.

## 2. 안전 변수 설정

```bash
export AWS_REGION=ap-northeast-2
export AWS_PAGER=""
export ECS_CLUSTER=tradar-cluster
export ECS_SERVICE=tradar-backend-svc
export ECR_REPOSITORY=tradar-backend
export FRONTEND_BUCKET=tradar-frontend
```

현재 account 확인:

```bash
aws sts get-caller-identity
```

각 삭제 명령 전에는 대상 ID를 다시 출력하고 사용자가 눈으로 확인한다.

```bash
printf 'cluster=%s service=%s region=%s\n' \
  "$ECS_CLUSTER" "$ECS_SERVICE" "$AWS_REGION"
```

## 3. ECS service와 cluster 삭제

현재 상태:

```bash
aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query 'services[0].{status:status,desired:desiredCount,running:runningCount,taskDefinition:taskDefinition,loadBalancers:loadBalancers}'
```

명시적으로 0으로 축소:

```bash
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --desired-count 0 \
  --region "$AWS_REGION"

aws ecs wait services-stable \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION"
```

실행 task가 없는지 확인:

```bash
aws ecs list-tasks \
  --cluster "$ECS_CLUSTER" \
  --service-name "$ECS_SERVICE" \
  --region "$AWS_REGION"
```

Service 삭제:

```bash
aws ecs delete-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --region "$AWS_REGION"
```

다른 service/task가 없는 경우에만 cluster 삭제:

```bash
aws ecs list-services --cluster "$ECS_CLUSTER" --region "$AWS_REGION"
aws ecs list-tasks --cluster "$ECS_CLUSTER" --region "$AWS_REGION"

aws ecs delete-cluster \
  --cluster "$ECS_CLUSTER" \
  --region "$AWS_REGION"
```

Task definition은 비용을 발생시키는 compute가 아니지만 AWS 흔적을 없애려면 revision을 조회해 deregister한다.

```bash
aws ecs list-task-definitions \
  --family-prefix tradar-backend \
  --region "$AWS_REGION"

aws ecs deregister-task-definition \
  --task-definition <task-definition-arn> \
  --region "$AWS_REGION"
```

## 4. ALB, listener, rule, target group 삭제

Load balancer 조회:

```bash
aws elbv2 describe-load-balancers \
  --region "$AWS_REGION" \
  --query 'LoadBalancers[].{Name:LoadBalancerName,Arn:LoadBalancerArn,DNS:DNSName,Vpc:VpcId}'
```

ECS service 인벤토리에서 기록한 target group ARN과 연결된 ALB를 확정한다.

```bash
export LOAD_BALANCER_ARN=<alb-arn>

aws elbv2 describe-listeners \
  --load-balancer-arn "$LOAD_BALANCER_ARN" \
  --region "$AWS_REGION"
```

Listener를 삭제하면 관련 listener rule도 함께 제거된다.

```bash
aws elbv2 delete-listener \
  --listener-arn <listener-arn> \
  --region "$AWS_REGION"
```

ALB 삭제:

```bash
aws elbv2 delete-load-balancer \
  --load-balancer-arn "$LOAD_BALANCER_ARN" \
  --region "$AWS_REGION"
```

ALB 삭제 완료 후 target group 삭제:

```bash
aws elbv2 delete-target-group \
  --target-group-arn <target-group-arn> \
  --region "$AWS_REGION"
```

`ResourceInUse`가 나오면 listener/rule 또는 다른 service가 target group을 참조하는지 다시 확인한다.

## 5. NAT Gateway와 Elastic IP 삭제

사용자 기록에는 `tradar-regional-nat`가 이미 삭제됐다고 되어 있다. 조회 결과가 비어 있으면 NAT 삭제 명령은 실행하지 않는다. 단, 연결됐던 Elastic IP는 자동으로 release되지 않았을 수 있으므로 반드시 확인한다.

조회:

```bash
aws ec2 describe-nat-gateways \
  --region "$AWS_REGION" \
  --filter Name=state,Values=available,pending \
  --query 'NatGateways[].{NatGatewayId:NatGatewayId,VpcId:VpcId,SubnetId:SubnetId,Addresses:NatGatewayAddresses}'
```

삭제:

```bash
aws ec2 delete-nat-gateway \
  --nat-gateway-id <nat-gateway-id> \
  --region "$AWS_REGION"
```

상태 확인:

```bash
aws ec2 describe-nat-gateways \
  --nat-gateway-ids <nat-gateway-id> \
  --region "$AWS_REGION" \
  --query 'NatGateways[0].State'
```

NAT Gateway 삭제는 연결된 EIP를 release하지 않는다. NAT inventory에서 allocation ID를 확인한 뒤 다른 리소스가 사용하지 않는 경우 release한다.

```bash
aws ec2 describe-addresses --region "$AWS_REGION"

aws ec2 release-address \
  --allocation-id <eip-allocation-id> \
  --region "$AWS_REGION"
```

Route table의 NAT route는 VPC 전체를 삭제할 계획이면 나중에 함께 제거된다. VPC를 유지한다면 blackhole route를 삭제한다.

## 6. VPC endpoint 정리

```bash
aws ec2 describe-vpc-endpoints \
  --region "$AWS_REGION" \
  --query 'VpcEndpoints[].{Id:VpcEndpointId,Service:ServiceName,Vpc:VpcId,State:State}'

aws ec2 delete-vpc-endpoints \
  --vpc-endpoint-ids <vpce-id-1> <vpce-id-2> \
  --region "$AWS_REGION"
```

T-RADAR 전용인지 확인하고 공유 endpoint는 삭제하지 않는다.

## 7. CloudFront disable 및 삭제

사용자 기록에는 다음 두 distribution이 있다. 레포 workflow에는 frontend distribution ID만 있으므로 API distribution을 놓치지 않는다.

- frontend: `tradar-frontend-cf`
- API: `tradar-api-cf`

실제 존재 여부와 ID를 다시 조회한다.

```bash
aws cloudfront list-distributions \
  --query 'DistributionList.Items[].{Id:Id,DomainName:DomainName,Enabled:Enabled,Origins:Origins.Items[*].DomainName}'
```

Console 방식이 가장 단순하다.

1. Distribution 선택
2. Disable
3. 상태가 `Deployed`, Enabled가 `False`가 될 때까지 기다림
4. Delete

CLI 방식:

```bash
export CF_DISTRIBUTION_ID=<distribution-id>
mkdir -p /tmp/tradar-cloudfront-delete

aws cloudfront get-distribution-config \
  --id "$CF_DISTRIBUTION_ID" \
  > /tmp/tradar-cloudfront-delete/current.json

jq '.DistributionConfig.Enabled = false | .DistributionConfig' \
  /tmp/tradar-cloudfront-delete/current.json \
  > /tmp/tradar-cloudfront-delete/disabled-config.json

ETAG=$(jq -r '.ETag' /tmp/tradar-cloudfront-delete/current.json)

aws cloudfront update-distribution \
  --id "$CF_DISTRIBUTION_ID" \
  --if-match "$ETAG" \
  --distribution-config file:///tmp/tradar-cloudfront-delete/disabled-config.json

aws cloudfront wait distribution-deployed \
  --id "$CF_DISTRIBUTION_ID"

NEW_ETAG=$(aws cloudfront get-distribution-config \
  --id "$CF_DISTRIBUTION_ID" \
  --query ETag --output text)

aws cloudfront delete-distribution \
  --id "$CF_DISTRIBUTION_ID" \
  --if-match "$NEW_ETAG"
```

위 절차를 **두 distribution 각각에 반복**한다. OAC/OAI가 별도로 남으면 다른 distribution이 참조하지 않는지 확인한 후 삭제한다.

## 8. ECR repository 삭제

ECS task가 모두 중지된 후 수행한다.

```bash
aws ecr describe-repositories \
  --repository-names "$ECR_REPOSITORY" \
  --region "$AWS_REGION"

aws ecr list-images \
  --repository-name "$ECR_REPOSITORY" \
  --region "$AWS_REGION"

aws ecr delete-repository \
  --repository-name "$ECR_REPOSITORY" \
  --force \
  --region "$AWS_REGION"
```

이미지는 Git repository의 Dockerfile로 다시 만들 수 있다는 전제다.

## 9. S3 bucket 영구 삭제

CloudFront 삭제 후 frontend bucket을 처리한다.

### Versioning 확인

```bash
export BUCKET="$FRONTEND_BUCKET"

aws s3api get-bucket-versioning --bucket "$BUCKET"
aws s3api get-object-lock-configuration --bucket "$BUCKET" 2>/dev/null || true
```

Versioning이 없으면:

```bash
aws s3 rm "s3://$BUCKET" --recursive
aws s3api delete-bucket --bucket "$BUCKET" --region "$AWS_REGION"
```

Versioning이 활성화/중지된 bucket은 단순 `aws s3 rm`으로 과거 version과 delete marker가 제거되지 않는다. Console의 `Empty` 기능에서 all versions를 제거하거나 version ID를 포함해 삭제한다.

CLI 조회:

```bash
aws s3api list-object-versions \
  --bucket "$BUCKET" \
  --query '{Versions:Versions[].{Key:Key,VersionId:VersionId},DeleteMarkers:DeleteMarkers[].{Key:Key,VersionId:VersionId}}'
```

대량 version 삭제는 pagination과 Object Lock을 고려해야 하므로 Console의 bucket Empty 또는 검증된 전용 스크립트를 사용한다. 빈 bucket 확인:

```bash
aws s3api list-objects-v2 --bucket "$BUCKET" --max-items 1
aws s3api list-object-versions --bucket "$BUCKET" --max-items 1
```

Object Lock retention/legal hold가 있으면 retention이 끝나기 전에는 일부 version을 삭제할 수 없다.

Data bucket은 `01` 문서의 복사 검증이 끝난 뒤 같은 방식으로 처리한다.

## 10. CloudWatch 정리

```bash
aws logs describe-log-groups \
  --region "$AWS_REGION" \
  --query 'logGroups[].logGroupName'

aws logs delete-log-group \
  --log-group-name /ecs/tradar-backend \
  --region "$AWS_REGION"

aws cloudwatch describe-alarms --region "$AWS_REGION"
```

필요한 감사/사용량 로그가 있다면 삭제 전에 export한다.

## 11. SSM과 Secrets Manager 삭제

새 로컬 env로 API/worker 기동에 성공했거나 secret export가 안전하게 보존됐는지 확인한 후 수행한다.

`/tradar/prod`는 로컬 디렉터리가 아니라 AWS Systems Manager Parameter Store의 계층형 이름이다. `*`라는 단일 parameter를 삭제하는 것이 아니라 조회된 개별 이름을 삭제한다.

```bash
aws ssm get-parameters-by-path \
  --path /tradar/prod \
  --recursive \
  --region "$AWS_REGION" \
  --query 'Parameters[].Name' --output text
```

한 번에 10개 이하로 삭제하거나 반복 처리한다.

```bash
aws ssm delete-parameters \
  --names <parameter-name-1> <parameter-name-2> \
  --region "$AWS_REGION"
```

Secrets Manager secret은 기본적으로 recovery window가 적용될 수 있다. 즉시 영구 삭제 여부는 secret 보존 정책에 따라 결정한다.

## 12. ACM 및 Route 53 정리 — 존재할 때만

제공된 기록에는 Route 53이나 custom domain 사용 내역이 없다. OpenSearch의 “domain”은 Route 53 DNS domain이 아니다. 목록 조회 결과가 비어 있으면 Route 53 삭제/이전 작업을 하지 않는다.

### ACM

인증서를 참조하던 CloudFront/ALB가 먼저 삭제되어야 한다.

```bash
aws acm list-certificates --region "$AWS_REGION"
aws acm list-certificates --region us-east-1

aws acm delete-certificate \
  --certificate-arn <certificate-arn> \
  --region <certificate-region>
```

### Route 53 hosted zone

Cloudflare nameserver 전환과 DNS 확인을 완료한 후 custom record를 제거하고 hosted zone을 삭제한다. NS/SOA 기본 record는 hosted zone 삭제 시 처리된다.

Domain registration이 Route 53에 있다면 hosted zone 삭제와 domain transfer를 혼동하지 않는다. AWS 사용을 완전히 끝내려면 domain을 다른 registrar로 이전 완료한 후 Route 53 Domains 상태를 확인한다.

## 13. Security group과 VPC 삭제

T-RADAR 전용 VPC인 경우에만 진행한다. 순서:

1. ECS/EC2/RDS/OpenSearch/ALB/NAT/VPC endpoint 없음 확인
2. Network interface 확인
3. 사용자 정의 security group 삭제
4. route table/subnet 삭제
5. internet gateway detach/delete
6. VPC 삭제

Network interface 확인:

```bash
export VPC_ID=<tradar-vpc-id>

aws ec2 describe-network-interfaces \
  --filters Name=vpc-id,Values="$VPC_ID" \
  --region "$AWS_REGION"
```

ENI가 남아 있으면 description과 owner를 보고 원본 서비스를 먼저 삭제한다. ENI를 무조건 강제 삭제하지 않는다.

## 14. IAM과 GitHub secret 마지막 정리

대상 후보:

- GitHub Actions IAM user/access key
- `ecsTaskExecutionRole`
- `tradar-ecs-task-role`
- AWS 배포 전용 policy

Role 삭제 전:

1. attached managed policy detach
2. inline policy delete
3. instance profile에서 제거
4. role delete

GitHub repository에서 삭제:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
기존 AWS VITE_API_BASE_URL
```

R2 key는 AWS key와 이름이 비슷하므로 GitHub frontend secret에 넣지 않는다. R2 secret은 로컬 backend 전용이다.

## 15. 최종 잔존 리소스 검사

서울 리전과 사용한 모든 리전에서 다음을 다시 조회한다.

- ECS/ECR
- EC2/ELB/NAT/EIP
- RDS/OpenSearch Service
- VPC endpoint
- S3
- CloudFront
- CloudWatch Logs
- SSM/Secrets Manager
- Route 53/ACM
- IAM access key

Cost Explorer 비용은 실시간이 아닐 수 있으므로 삭제 당일만 보고 종료하지 않는다. 다음 날과 다음 청구서에서도 확인한다.

## 16. 자주 발생하는 삭제 실패

| 오류 | 원인 | 해결 |
|---|---|---|
| TargetGroup `ResourceInUse` | listener/rule 참조 | listener/rule 또는 ALB 먼저 삭제 |
| CloudFront delete 비활성 | 아직 enabled/deploying | disable 후 Deployed까지 대기 |
| S3 BucketNotEmpty | version/delete marker 남음 | 모든 version과 marker 삭제 |
| VPC dependency violation | ENI/NAT/endpoint/IGW 남음 | ENI description으로 원본 서비스 제거 |
| Security group dependency | 다른 SG/ENI가 참조 | 참조 rule/ENI 제거 |
| IAM DeleteConflict | policy/profile 남음 | detach/delete 후 role/user 삭제 |
| EIP 비용 잔존 | NAT 삭제가 EIP를 release하지 않음 | allocation ID를 직접 release |

## 17. 완료 조건

- [ ] ECS/ECR/ALB/NAT/EIP가 없다.
- [ ] CloudFront distribution이 없다.
- [ ] 삭제 대상 S3 bucket과 모든 object version이 없다.
- [ ] AWS 전용 CloudWatch/SSM/Secrets가 없다.
- [ ] Route 53 domain/DNS 처리가 완료됐다.
- [ ] AWS 배포용 IAM key와 GitHub secret이 없다.
- [ ] 모든 사용 리전을 다시 확인했다.
- [ ] 다음 날 Cost Explorer에서 예상 외 비용이 없다.
