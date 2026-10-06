#!/usr/bin/env bash
# ECR 에 이미지를 올리고 App Runner 서비스를 만들거나 갱신한다.
#   AWS_REGION=ap-northeast-2 AWS_ACCOUNT_ID=123456789012 ./deploy/aws/push_ecr.sh
set -euo pipefail
: "${AWS_REGION:=ap-northeast-2}"
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID 필요}"
REPO="harbinger/api"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO}"
aws ecr describe-repositories --repository-names "$REPO" --region "$AWS_REGION" >/dev/null 2>&1 || aws ecr create-repository --repository-name "$REPO" --region "$AWS_REGION" >/dev/null
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker build -t "${URI}:${TAG}" -t "${URI}:latest" .
docker push --all-tags "$URI"
if aws apprunner list-services --region "$AWS_REGION" --query "ServiceSummaryList[?ServiceName=='harbinger-api'].ServiceArn" --output text | grep -q arn; then
  ARN=$(aws apprunner list-services --region "$AWS_REGION" --query "ServiceSummaryList[?ServiceName=='harbinger-api'].ServiceArn" --output text)
  aws apprunner update-service --region "$AWS_REGION" --service-arn "$ARN" --source-configuration "ImageRepository={ImageIdentifier=${URI}:${TAG},ImageRepositoryType=ECR,ImageConfiguration={Port=8000,RuntimeEnvironmentVariables={HARBINGER_DEMO_BOOTSTRAP=1}}}" >/dev/null
else
  aws apprunner create-service --region "$AWS_REGION" --service-name harbinger-api \
    --source-configuration "ImageRepository={ImageIdentifier=${URI}:${TAG},ImageRepositoryType=ECR,ImageConfiguration={Port=8000,RuntimeEnvironmentVariables={HARBINGER_DEMO_BOOTSTRAP=1}}},AutoDeploymentsEnabled=false,AuthenticationConfiguration={AccessRoleArn=arn:aws:iam::${AWS_ACCOUNT_ID}:role/service-role/AppRunnerECRAccessRole}" \
    --instance-configuration "Cpu=2 vCPU,Memory=4 GB" \
    --health-check-configuration "Protocol=HTTP,Path=/health,Interval=20,Timeout=5,HealthyThreshold=1,UnhealthyThreshold=5" >/dev/null
fi
echo "pushed ${URI}:${TAG}"
