# 공개 증거 복구와 최종 제출 정리 — 2026-10-27 KST

기준은 [PR #16](https://github.com/sokldjs554/harbinger/pull/16)의 병합 커밋 `e33072bc88652dc8e4bc50f9e3c68b9d44966379`이다. 최종 작업 커밋은 `55d658fd3e741565d2951167237eb03d33238f76`이다. 이번 후속 변경은 증거 복구·문서·재검토 준비와 외부 수신 검증을 대상으로 하며, 기존 실험 수치를 다시 선택하거나 바꾸지 않는다.

## 1. 클론에서 실패하던 운영 증거

`operations/comparison.json`은 수정 전·후 `api.log`, `prometheus.log`, `run.log` 6개의 해시를 포함하지만, 저장소의 `*.log` 제외 규칙 때문에 파일이 커밋되지 않았다. 로컬에는 원본이 있어 이전 검사가 통과했고, Git이 추적한 파일만 있는 새 작업 디렉터리에서는 [비교 불일치](clean-checkout-before.txt)를 재현했다. 이전 로컬 통과만으로 공개 재현을 확인했다고 판단한 것이 검증 누락이었다.

6개 원본의 바이트가 기존 해시와 모두 일치함을 확인하고 그대로 복구했다. 같은 원인으로 누락된 학습·최초 운영 시험·브라우저 기록 16개도 함께 복구했다. [22개 원본의 경로·크기·해시](log-recovery.json)를 남겼으며, 원래 빈 로그는 빈 상태로 보존하고 성공 증거로 부르지 않는다. 기존 `comparison.json`과 `verify_comparison.py`는 수정하지 않았다. [음성 대조](evidence-negative-controls.json)에서 로그 삭제·변조는 여전히 실패하고 원본 복구 후 통과한다. CI는 새 checkout에서 같은 검사를 실행한다.

재현 명령(저장소 루트, Python 표준 라이브러리만 필요):

```bash
python docs/verification/completion-20261026/operations/verify_comparison.py
```

성공 조건은 종료 코드 0과 `raw_measurement_checks_passed=true`, `overall_passed=true`, 전후 `alert_settlement=true`다. 공개 브랜치를 새로 클론하여 통과했다. 명령·확인한 커밋·실행 결과는 [fresh-clone.json](fresh-clone.json)에 기록했다. 이 증거는 로컬 부하·로컬 수신 시험이며 운영자 이메일 수신 증거가 아니다.

## 2. 확정된 PR #16 병합·배포

| 확인 대상 | 확정 값·실행 |
|---|---|
| 서비스 소스 | `e33072bc88652dc8e4bc50f9e3c68b9d44966379` |
| PR 최종 CI | [40340725505](https://github.com/sokldjs554/harbinger/actions/runs/40340725505), 성공 |
| main CI | [40343231689](https://github.com/sokldjs554/harbinger/actions/runs/40343231689), test·tensorflow·image 성공 |
| AWS | [40343231411](https://github.com/sokldjs554/harbinger/actions/runs/40343231411), 성공; 모델 `v20261026-151241` |
| Pages | [40343231487](https://github.com/sokldjs554/harbinger/actions/runs/40343231487), 성공; 저장 모델 `v20261026-093937` |
| 특징 호환성 | 두 전체 번들 모두 특징 정의 3·116개; 원자료 7개 해시 일치 |

이 표의 모델 ID와 `completion-20261026` 폴더 날짜는 기존 UTC 생성 식별자이며, 배포 완료는 한국 시간 2026-10-27이다. 후속 문서/알림 변경 커밋을 PR #16 모델의 학습 커밋으로 소급 표기하지 않는다.

[배포 원본](release/aws/deployment.json), [배포 확인 원본](release/aws/deployment-result.json), [학습 지표](release/aws/metrics.json), [공개 브라우저](release/aws/browser-checks.json), [에너지·순찰 모바일](release/aws/energy-checks.json)를 원래 산출물에서 복사해 영구 보관했다. [전체 출처·해시](release/manifest.json). 새 인스턴스 생성 없이 HTTPS·인증서 갱신 시험·재부팅 복구·임시 SSH 제거·CSV 실제 계산·세 가지 다운로드·모바일 필터·목록/상세 상태 복원을 확인했다.

Docker는 CI에서 비루트 UID 10001·소스 80개 해시·실제 API를 확인했다. 작업 환경의 직접 AWS 조회는 TLS IP 이름 검증에 실패했으며 검증을 끄지 않았다. 공개 접속 증거는 정상 TLS를 사용한 GitHub Actions 결과다. AWS 에너지 JSON의 고정 `backend` 문구는 “local API”지만 실제 대상은 상위 브라우저 JSON과 workflow 명령에 기록된 공개 AWS다. AWS 배포 학습은 LOSO를 생략했고, 8개 고객사 보류 평가는 별도 전체 로컬 실행에서 수행했다.

## 3. 제출 문장과 사람의 재검토

[자소서 프로젝트 문장](../../application-update.md), [포트폴리오](../../submission.md), [공고 대응](../../job-requirements-audit.md), [역할·확정 수치](../../submission-evidence-20261026.md)를 현재 실험과 배포 기록에 맞춘다. 과거 경계 수정 실험은 과거 수치로 표시하고 현재 번들·새 시드 평균과 혼합하지 않는다.

사용자의 확인된 역할은 문제·제품 방향과 기술 범위 선택, 검토 의견 전달과 결과 확인이다. 구현·실험 설계의 세부 기준·코드 작성·검증·문서화에는 Codex 지원을 사용했다. 개인의 학력·고용 경력·독립 코딩 능력은 저장소로 확인할 수 없다.

동료 A·친구 B의 의견과 “추가 문제 없음”이라는 전달 회신은 기존 기록으로 보존한다. 참가자별 실제 날짜·버전·7과업 결과·도움·시간을 갖춘 새 재검토는 아직 수신하지 않았다. [재검토 안내](../../user-reviews/retest-guide.md)와 참가자별 빈 양식을 준비하며 실제 회신 전에는 성공률·시간 단축을 작성하지 않는다.

## 4. 외부 알림 상태

운영자는 프로젝트 소유자이며 이메일 수신을 선택했다. 수신 주소와 SMTP 비밀값은 공개 저장소에 기록하지 않는다. [외부 알림 실행 안내](../../ops/external-alerts.md)에 네이버 SSL 465 설정, 실제 시험 발화·복구·운영자 수신 회신을 기록했다. 로컬 Prometheus 수신기 통과와 외부 수신 확인은 별도 증거로 구분한다. 시스템 전송·복구 결과와 운영자 실제 수신을 분리해 아래 후속 기록에 남긴다.

모든 모델 성능은 합성 데이터 검증이다. 실제 고객 성능, 장기 SLA, AWS 처리량, 사람의 미측정 개선 효과는 확인되지 않았다.

## 5. 후속 변경의 개발 검증

[독립 검토와 실패 경로 수정](review.md), [전체 테스트](checks/full-tests-final.txt), [재검토 도구 조작](checks/retest-recorder-checks.json), [최종 로컬 SSL 시험](checks/mail-final-result.json)과 [로컬 수신 기록](checks/mail-final-smtp.json)을 남겼다. `mail-local-*`와 `mail-portable-*`는 이전 로컬 시험 원본이며, JSON의 범위 문구가 운영 호스트로 남아 있던 점을 최종 도구/기록에서 수정했다. 어느 로컬 기록도 네이버 또는 운영자 수신을 의미하지 않는다. 로컬 Docker 시험은 이미지 다운로드 중 디스크 부족으로 완료하지 못했고, 실제 컨테이너 검증은 CI와 운영 workflow에서 별도로 확인한다.

## 6. 후속 PR #17 병합과 외부 시험

[PR #17](https://github.com/sokldjs554/harbinger/pull/17)은 `3e6b3da81bbd4cab705c2de0027f9740cafedb8d`로 병합했다. [PR CI](https://github.com/sokldjs554/harbinger/actions/runs/40362387991)와 [병합본 CI](https://github.com/sokldjs554/harbinger/actions/runs/40364278833)의 test·tensorflow·image가 모두 통과했다. [병합본 원본 검사·해시](main-ci/manifest.json)를 보관했다. 이 CI의 소규모 합성 모델은 검사 전용이며 공개 AWS/Pages 모델을 교체하지 않았다.

[첫 외부 이메일 시험](https://github.com/sokldjs554/harbinger/actions/runs/40366576243)은 실패했다. SMTP 전송 성공을 확인하지 못했으며 운영자 수신도 미확인이다. [실패 사실·로그 발췌](external-alerts/attempt-1-summary.json), [별도 종료 후 AWS 조회 원본](external-alerts/attempt-1-host-state.json)을 보존했다. 숨김 폴더 때문에 결과 JSON 업로드가 누락된 문제를 수정하고, 당시에는 사용자 SMTP 사용 설정 저장 회신에 따라 재시험을 준비했다. 첫 실패 시점에는 외부 알림 연결 완료라고 표현하지 않았으며 실제 재시험 결과는 다음 절에 기록한다.

## 7. PR #18 병합과 네이버 SSL 재시험

[PR #18](https://github.com/sokldjs554/harbinger/pull/18)은 `530faf0f8ae678f6f29c85c1e222edc742e7d83c`로 병합했다. [PR CI](https://github.com/sokldjs554/harbinger/actions/runs/40369464258), [병합본 CI](https://github.com/sokldjs554/harbinger/actions/runs/40371570771)의 test·tensorflow·image가 모두 통과했다. PR #18 당시 로컬 전체 검사는 378개 통과이며, 실제 로컬 SSL 정상 전송과 SMTP 535 거절·정리를 CI에서도 검증했다.

사용자가 SMTP 사용 설정을 저장했다고 회신한 후 [재시험 40373254666](https://github.com/sokldjs554/harbinger/actions/runs/40373254666)을 실행했다. `mail-40373254666-1`의 장애·복구 이메일 전송 성공, 시험 규칙 제거, health 정상, 모델 `v20261026-151241` 유지, 남은 firing 경보 없음, 임시 SSH 제거를 확인했다. 새 인스턴스나 공개 부하 시험은 없었다. [원본 결과·출처·해시](external-alerts/manifest.json), [상세 시각과 수신 상태](../../ops/external-alerts.md).

첫 실패 결과도 다음 시험 전에 원격 원본을 회수해 [그대로 보존](external-alerts/attempt-1-result.json)했다. 이전 결함으로 업로드되지 않았던 JSON을 새로 만들어 채우지 않았다. 기존의 첫 실패 요약은 당시 상태로 유지한다.

운영자가 해당 시험 번호의 장애·복구 두 메일 수신을 회신했다. [별도 실제 회신 기록](external-alerts/operator-receipt.json)을 남겼다. 운영자가 추가로 전달한 표시 시각은 2026-10-27 02:58 KST(분 단위)다. 메일별 시각 구분·메일함 종류는 미제공이며, 자동 전송 시각을 실제 도착 시각으로 바꾸거나 전달 지연을 계산하지 않는다. 동료 A·친구 B의 새 7과업 재검토도 아직 미수신이며 양식 준비와 도구 검증까지만 완료했다. 실제 서비스/Pages 소스·모델은 PR #16의 배포 상태를 유지하고, 이후 커밋은 증거·문서·모니터링 변경으로 구분한다.

## 8. 알림 설정 지속성 후속 수정

PR #19 이후 마지막 파일 정리까지 점검하여 첫 실패 후 재설치 시 활성 설정 삭제 가능성을 재현했다. 이전 메일 전송·수신을 부정하는 결과는 아니며, 기존 검증에 없던 재기동 지속성의 결함이다. [원인·회귀 검사·독립 검토](review.md)에 기록했다. 정상 설정을 사용한 실제 모니터링 재생성과 마지막 정리 후 활성 파일 보존을 별도 운영 검증한다. 해당 후속 운영 실행 전에는 재기동 검증 완료로 표시하지 않는다.
