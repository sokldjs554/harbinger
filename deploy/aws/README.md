# AWS 데모 운영

[현재 실제 계산 데모](https://sokldjs554.github.io/harbinger/live.html) · [배포 검증과 캡처](../../docs/verification/aws/README.md)

이 구성은 Sydney(`ap-southeast-2`)의 단일 EC2에서 합성 데이터로 학습한 모델과 FastAPI를 실행합니다. GitHub Pages의 저장 결과 재생과 달리 업로드 CSV를 검사하고 새 결과를 계산합니다. 실제 고객 성능을 검증한 서비스는 아닙니다.

## 배포 흐름

`.github/workflows/aws-ec2.yml`은 `main`의 배포·소스·런타임 의존성 파일 변경 또는 수동 실행으로 동작합니다. 기존 서버가 있으면 읽기 전용 AWS 조회로 SSH 신원을 먼저 확인합니다. 같은 커밋의 전체 CI 통과를 확인한 후 이미지 빌드와 전체 합성 모델 학습을 완료하고 서버를 준비합니다. `deploy.py`는 계정·리전·소유 태그·중복 서버를 검사합니다.

GitHub Actions 저장소 시크릿은 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`입니다. 세션 자격 증명을 쓸 때만 `AWS_SESSION_TOKEN`을 추가합니다. 키를 서버나 저장소 파일에 복사하지 않습니다. 필요한 권한은 [배포 정책](ec2-deploy-policy.json)에 있습니다.

현재 무료 계정 플랜에서 허용되는 유형을 AWS API로 조회해 `c7i-flex.large`(2 vCPU·4GiB)를 선택했습니다. 인스턴스 유형과 Ubuntu 이미지의 `FreeTierEligible` 값을 확인하며, 이 표시는 크레딧 소모 없이 무제한으로 실행할 수 있다는 뜻이 아닙니다. [AWS 무료 플랜의 EC2 조건](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html)

서버는 `c7i-flex.large`, 암호화한 30GiB gp3 디스크, IMDSv2를 사용합니다. API 컨테이너의 8000 포트는 서버 내부에서만 열고 Nginx를 통해 80/443을 제공합니다. SSH는 배포 실행자의 IPv4 한 개에만 임시로 열며, EC2 Instance Connect의 단기 접속 키를 사용하고, AWS 콘솔 출력 또는 아래의 명시적인 인스턴스별 공개키로 서버 신원을 검증합니다. OpenSSH 사용자 설정과 다른 신뢰 파일은 사용하지 않습니다. 완료·실패 시 임시 SSH 규칙을 제거합니다.

## 재배포에서 서버 공개키가 보이지 않을 때

EC2 콘솔 출력이 남아 있어도 최초 부팅 때 출력된 SSH 공개키는 포함되지 않을 수 있습니다. 2026-10-24에는 최신·기본 출력 모두에서 공개키가 없어 재배포가 서버 파일 복사 전에 중단됐습니다. [진단 결과](../../docs/verification/audit-20261024/host-identity-diagnostics.json)

이 경우 **이미 신뢰하는 관리 연결**에서 다음 공개키를 확인합니다.

```bash
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

`.pub` 파일의 공개키만 사용합니다. 같은 이름에서 `.pub`가 없는 파일은 개인키이므로 읽거나 공유하지 않습니다. 처음 보는 SSH 연결의 확인 질문을 무조건 수락하거나 `ssh-keyscan` 결과를 그대로 믿어서는 안 됩니다. 신뢰 가능한 관리 연결이 없다면 먼저 소유자가 서버 신원을 복구해야 합니다.

GitHub 저장소의 Actions secret **`AWS_EC2_SSH_HOST_IDENTITY`**에 아래 형태의 JSON을 등록합니다. 아래의 `실제...` 값은 예시 자리이며 실행 가능한 키가 아닙니다.

```json
{"instance_id":"실제 EC2 인스턴스 ID","host_key":"ssh-ed25519 실제 공개키 본문"}
```

현재 진단한 인스턴스 ID는 `i-0aaec13273afe3197`입니다. 등록 전 AWS 콘솔에서 대상 인스턴스를 다시 확인합니다. 키 뒤의 주석은 있어도 되며 저장 시 신뢰 파일에는 알고리즘과 공개키 본문만 사용합니다. 이 값은 AWS access key나 EC2 접속용 개인키와 다릅니다.

배포는 인스턴스 ID, Ed25519 키의 전체 바이너리 구조, 중복 JSON 필드와 추가 필드를 검사합니다. AWS 콘솔에 키가 남아 있다면 등록값과 일치해야 합니다. 인스턴스 교체나 호스트 키 재생성 후에는 소유자가 새 신원을 확인하고 등록값을 갱신해야 합니다. 확인할 키가 없으면 사전 검사에서 중단하며 신원 검사를 끄지 않습니다.

시크릿 등록 후 **AWS EC2 live demo → Run workflow → main**으로 다시 실행합니다. 이 값은 테스트용 가짜 키로 채우지 않습니다.

## 검증과 복구

배포는 신뢰 가능한 HTTPS, 실제 모델 API, 인증서 갱신 시험과 Nginx reload hook, 재부팅 후 복구, CSV 처리·다운로드·데스크톱·모바일 조작을 확인한 뒤 확정합니다. 신규 서버 또는 중지 상태에서 다시 켠 서버가 검증에 실패하면 중지합니다. 실행 중인 기존 서버를 업데이트하다 실패하면 이전 릴리스로 복구를 시도합니다. 강제 실행 종료나 AWS 장애까지 자동 복구를 보장하지는 않습니다.

릴리스는 `/opt/harbinger/releases/<commit>`에 보관하고 `current` 심볼릭 링크로 선택합니다. 모델과 기본 합성 자료는 디스크에 남습니다. **업로드한 CSV와 분석 세션은 메모리에만 있으며 서버 재시작 시 사라집니다.**

Let's Encrypt IP 인증서는 유효기간이 짧아 6시간마다 systemd timer로 갱신을 확인합니다. `harbinger-cert-renew.timer` 상태와 `harbinger-cert-renew.service` 로그를 확인할 수 있습니다. Docker 로그는 파일당 10MB·3개로 제한하고, Nginx access log에는 세션 토큰을 포함한 URI를 기록하지 않습니다.

## 비용과 중지

EC2 실행 시간, EBS 디스크, 공인 IPv4와 전송량은 계정의 과금·크레딧 정책에 따릅니다. 무료 제공을 보장하는 구성이 아닙니다. AWS Billing에서 잔여 크레딧과 실제 사용액을 확인하세요.

사용하지 않을 때는 Sydney EC2 목록에서 `Project=harbinger`, `Name=harbinger-demo`인 서버를 **중지**합니다. 중지해도 EBS 디스크 요금은 남을 수 있습니다. 재시작하면 공인 IP가 바뀔 수 있으므로 GitHub Actions에서 배포를 다시 실행해 새 IP에 맞는 인증서·URL을 확인합니다. `docs/demo/live.html`의 목적지도 새 주소로 갱신해 GitHub Pages에 반영해야 고정 진입 링크가 새 서버로 연결됩니다. 서버 **종료**는 디스크와 모델을 삭제하므로 재사용이 필요 없다면 선택합니다.

검증 파일과 캡처는 각 Actions 실행의 `aws-deployment-verification` artifact에서 14일간 받을 수 있습니다. 실패 시 먼저 해당 실행 로그를 확인하고, 비용 발생을 막아야 한다면 EC2의 실제 상태가 중지인지 직접 확인하세요.
