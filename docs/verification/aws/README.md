# AWS에서 실제 CSV 계산을 확인했습니다

이 문서는 최초 배포의 이력입니다. 현재 소스·모델과 실제 서버 검증은 [2026-10-25 재배포 기록](../aws-20261025/README.md)을 확인하세요.

검증일: **2026-10-24 한국 시간**. [실제 계산 데모](https://sokldjs554.github.io/harbinger/live.html) · [AWS 직접 주소](https://13.236.137.0/console/) · [실제 자동검증 조작 33초](../../demo/aws-checks.mp4)

기본 자료와 학습 모델은 합성 데이터입니다. AWS 데모는 입력 조건과 업로드 CSV로 새 결과를 계산합니다. 실제 고객 성능이나 장기간 고객 운영을 검증한 결과는 아닙니다.

| 확인 항목 | 근거 |
|---|---|
| 소스 | `5e54df21b6b7c31473689526c20b0e7881e75dee` |
| 서버 | Sydney EC2 `c7i-flex.large` 한 대, 2 vCPU·4GiB, 암호화 gp3 30GiB, IMDSv2 |
| 네트워크 | 공개 80/443, API 8000은 localhost 연결, 임시 SSH 규칙 제거 확인 |
| 모델 | `v20261023-161741`, scale=1·36개월·seed=20260101, [생성 조건](deployment.json) |
| 전체 CI | [39983663133](https://github.com/sokldjs554/harbinger/actions/runs/39983663133): 83개 통과·선택적 TensorFlow 1개 제외, API·브라우저·Docker 성공 |
| AWS 배포 | [39983662792](https://github.com/sokldjs554/harbinger/actions/runs/39983662792): 성공, [결과](deployment-result.json) |
| 별도 실행 서버의 HTTPS | [39986629164](https://github.com/sokldjs554/harbinger/actions/runs/39986629164): health·배포 SHA·live 모델 메타데이터 확인, [게시 시 재확인](public-https.json) |
| 재시작·갱신 | EC2 재부팅 후 같은 모델과 HTTPS 복구, Certbot 갱신 모의시험과 Nginx reload hook 통과, 서비스·갱신 timer active |

## 실제 서버에서 확인한 동작

[브라우저 검사](browser-checks.json)의 `static`은 `false`, JavaScript 오류는 0개입니다.

- 설비 목록·상세·점검일, 검색·정렬·필터, 돌아가기와 초점 복원
- 모델·규칙의 선택 대상 일치, 미적용 조건과 내보내기 분리, 관측 기간 부족 시 평가 보류
- 고객사 조건, CSV·JSON·Markdown 다운로드
- 잘못된 CSV와 분석 실패 후 기존 자료 유지, 지원 CSV의 실제 모델 계산, 수식형 메모 이스케이프
- 320·390·650px의 필터·조건·스크롤·기록 이동, 모바일 전체 화면의 가로 넘침
- 세션 종료와 업로드 후 새로고침 안내

33초 영상은 자동 브라우저 검사 중 녹화한 실제 조작입니다. 빠른 화면 전환과 다운로드 검사가 포함됩니다. 사용 흐름을 설명하는 [기존 80초 영상](../../demo/walkthrough.mp4)은 저장 예제 화면입니다. [녹화·변환 정보](recording.json) · [파일 해시](sha256.json)

## 데스크톱과 모바일

실제 AWS 서버의 전체 합성 모델로 촬영했습니다. 설비 2,312개, 기준일 2025-11-17의 화면입니다.

![AWS 실제 계산 데스크톱](list.png)

[모바일 목록](mobile-list.png) · [모바일 상세](mobile-detail.png) · [잘못된 CSV 검사](upload-error.png)

## 모델과 평가 파일

[runtime/](runtime/)에 이번 배포의 재학습 평가 파일을 보존했습니다. HGB는 동일한 관측 완료 테스트 18,439행에서 AUROC 0.7696088847, PR-AUC 0.2444964125, Brier 0.0683772796입니다. README의 기존 실험 수치는 기존 `artifacts/`와 정적 예제 버전을 기준으로 유지합니다. 배포 학습은 `--skip-loso`이므로 이 런타임에서 고객사 전체 LOSO를 새로 수행했다고 주장하지 않습니다.

## 운영 범위

IP 인증서는 6시간마다 갱신을 확인하도록 설정했고 이번에는 갱신 모의시험과 reload hook을 검증했습니다. 실제 만료 시점의 갱신이나 장기간 무중단 운영을 관측한 기록은 아닙니다. 기본 합성 자료와 모델은 디스크에 남지만, 업로드 CSV·세션은 메모리에 있어 재시작 시 사라집니다.

EC2·디스크·공인 IPv4·전송량은 계정의 과금·크레딧 정책을 따릅니다. 중지 방법, 남을 수 있는 디스크 비용과 재시작 시 IP 변경은 [운영 안내](../../../deploy/aws/README.md)를 확인하세요.
