# PR #16 후속 평가·운영·제출 검증

기준 소스는 `5a7f947146dd24b43eb79a8e4744449615dabc17`이다. 기존 기록을 보존하고 별도 작업 브랜치에서 진행했다. 사전 계약은 `744e6d0`, 평가 통합은 `def9c94`에 기록했다. 모든 성능은 합성 자료의 결과이며 실제 고객 실증·현장 개선·개인 경력을 뜻하지 않는다.

[PR #16](https://github.com/sokldjs554/harbinger/pull/16) · [최종 PR 검사](https://github.com/sokldjs554/harbinger/pull/16/checks) · [AWS 실행](https://github.com/sokldjs554/harbinger/actions/workflows/aws-ec2.yml) · [Pages 실행](https://github.com/sokldjs554/harbinger/actions/workflows/pages.yml)

## 원인·수정·실제 확인

| 항목 | 원인과 수정 | 실행 결과·근거 |
|---|---|---|
| 메모 누락 반복 | 과거 실험의 중복 사이트 마스크·에너지 특징을 수정한 정확한 기준 소스로 3세계×2학습 재실행 | 기존 계약 재통과. 선택 정책의 25/50% 누락 이득 +5.297→+5.100%p, 정상 변화 +0.170→+0.139%p. [720개 전후 값·변동·모든 예측](memo/README.md) |
| HGB 기본값 | 이미 본 테스트로 선택하지 않도록 새 생성 시드의 검증→선택 해시 고정→미사용 테스트 단계 분리 | 전체 HGB 유지. 새 테스트 평균 AUROC 0.772578, PR-AUC 0.257555, Brier 0.066285, P@10 25.8909%; 메모 제외는 0.767690/0.255462/0.066442/25.5212%. [검증 조건·원시 예측·선택](default/README.md) |
| 실제 순찰 선택 | 위험 순위와 중요도·필수 점검 선택이 달랐음. 선택 함수를 공유하고 비교군에도 같은 필수 조건 적용 | 새 전체 번들의 위험순 P@10 23.8444%, 서비스 적중률 20.3111%. 4,500선택/914적중/613필수/초과0. 필수>K는 별도 회귀·실제 API/브라우저에서 확인. [기술 결과](technical-results.md), [선택 원본](../../../artifacts/patrol-observations.json.gz) |
| 점추정·구간 | 날짜 가중 평균과 고객사 bootstrap의 추정대상이 달랐음 | 둘 다 고객사 내 날짜 평균→고객사 동일 가중. 균등 자료는 일치, 불균등 진단 P@10 24.8617→23.9422%. 9개 실제 Store 선택 대조와 저장 행 기반 구간 재계산 통과. [근거](patrol/actual/summary.json) |
| 요청 제한 | 2개 슬롯이 차면 즉시 429여서 짧은 동시 burst도 대부분 거절 | 슬롯2 유지·FIFO 대기4·대기10초. 동시4에서 각 경로 성공2/20→20/20, 429 90%→0%, 5xx·전송 실패0. 성공 p95는 분석0.348→0.629초, 업로드2.241→4.463초, 다운로드0.291→0.787초로 증가. [CPU/RSS·전체 원시 요청·한계](operations/README.md) |
| 경보 복구 검사 | 과거 복구 알림이 있으면 이후 재발화를 놓쳤음 | 현재 rule inactive와 마지막 수신 resolved를 함께 요구. 초기 기록을 보존하고 동일 조건 재시험. 전후 두 경보 모두 발화→로컬 수신→최종 해제 확인. [엄격 재시험](operations/strict/), [회귀 RED→GREEN](checks/ops-recovery-green.txt) |
| 출력 일관성 | 순찰 API의 오래 미점검 비교가 필수 조건을 제외했고, 초과 선택을 K개로 표기 | 실제/필수/초과 수 표기, 같은 필수 조건 비교군. 빈 자료는 비교 보류. 모바일 기존 미리보기의 폭 넘침도 최소 폭 제약 수정. [실제 화면 검사](browser-patrol/checks.json) |

## 최종 로컬 실행과 파일 버전

전체 학습·8개 고객사 보류 평가를 1,493.6초에 실행했다. 로컬/저장 데모 번들은 **`v20261026-093937`**, 특징 정의는 **3**, 전체 HGB 특징은 **116개**다. 단일 세계의 성숙 테스트 18,439행에서 AUROC **0.767992**, PR-AUC **0.240558**, Brier **0.068648**이다. 새 3세계 선택 실험의 평균과 다른 평가 집단이다.

[학습 로그](checks/final-training.log), [학습·모델·자료 소스 해시](../../../artifacts/training-provenance.json), [현재 소스·산출물·데모 해시](../../../artifacts/release.json)를 함께 본다. 학습 당시 평가 소스는 `def9c94` 스냅샷이며, 원시 순찰 멤버십을 압축 파일로 옮기는 포장만 적합 후 적용했다. 그 과정에서 선택·예측·지표를 재학습하거나 바꾸지 않았다. 약 30MB 원시 JSON은 1.1MB 압축 근거로 보존하고 API 요약 전송에서 분리했다. 참조 해시도 검사한다.

과거 현재 산출물은 [archive/pre-completion-5a7f947](../../../artifacts/archive/pre-completion-5a7f947/)에 보존했다. 기존 메모·안정성·경계 수정 실험도 그대로 남겼다. AWS는 배포 workflow에서 같은 소스로 다시 학습하므로 저장 예제와 번들 시각/버전이 다를 수 있다. 실제 공개 버전은 `/version`과 배포 `deployment.json`으로 확인해야 하며 로컬 버전을 AWS 버전으로 추정하지 않는다.

## 검사와 화면

- [전체 검사](checks/final-tests.txt): TensorFlow를 설치한 환경에서 **356 passed**, 건너뜀 없음. 이후 추가한 경보 복구 회귀 2개도 통과했다. 최종 커밋의 전체 검사·TensorFlow 전용 작업·실제 Docker 이미지 실행은 위 PR 검사 링크에서 커밋별로 확인한다.
- [실제 API](api/api.json): 새 모델로 분석, CSV 업로드 후 계산, JSON/CSV/Markdown 다운로드, 짧은 에너지 관측 보류 확인. 이 파일은 로컬 Python 서버 결과이며 Docker 결과로 부르지 않는다.
- [주 화면 실제 API](browser-live/), [저장 예제](browser-static/): 데스크톱·모바일 필터, 목록↔상세 이동·상태 복원, 업로드·다운로드 조작 통과.
- [에너지·순찰 모바일](browser-energy-final/checks.json): 자료 없음·관측 부족, 실제 선택 수·빈 결과·가로 넘침 확인.
- 변경 화면: [순찰 데스크톱](browser-patrol/patrol-desktop.png), [모바일 수정 전](browser-patrol/mobile-before-overflow.png), [수정 후](browser-patrol/patrol-mobile.png), [빈 결과](browser-patrol/patrol-empty-mobile.png). 순찰 K=1에서 필수 설비가 초과하는 실제 합성 사례를 사용했다. 최초 S01 날짜 표본에서 초과 사례를 찾지 못한 시도도 로그에 남기고, 저장된 평가에서 확인한 S04 사례로 변경했다. 모델 채택 조건을 바꾼 것은 아니다.
- [새 저장 예제 영상](../../demo/walkthrough.mp4): 실제 브라우저 조작 79.96초. [모드·버전·해시](recording.json). Pages workflow도 배포할 데이터로 새 영상을 녹화한다.
- 독립 코드 검토에서 중요한 미해결 결함은 발견되지 않았다. 발견한 소스 기록 누락, 원시 압축 파일 해시, 빈 결과 표시, 경보 최종 상태 검사는 보완했다. 이것이 모든 약점의 부재를 증명하지는 않는다.

로컬 디스크 여유 약 1.4GiB와 Docker vfs 저장 방식 때문에 새 전체 이미지를 로컬에서 빌드했다고 주장하지 않는다. 최종 Dockerfile 빌드·UID·이미지/체크아웃 소스 해시·API/CSV/다운로드/에너지 보류는 CI의 `image` 작업과 `docker-audit` 산출물을 확인한다. 새 유료 리소스와 공개 서버 부하 시험은 수행하지 않는다.

## 재현과 남은 한계

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest -ra
python scripts/fill_numbers.py --check
python scripts/release_manifest.py --check
python docs/verification/completion-20261026/operations/verify_comparison.py
PYTHONPATH=src:. python docs/verification/completion-20261026/default/verify-executed.py
```

학습·메모·실제 순찰·부하의 입력 경로와 명령은 각 하위 보고서 및 execution/provenance 파일에 보존했다. `.venv`를 포함한 실행 바이너리와 원자료/모델 바이너리는 저장소에 중복 커밋하지 않는다. 합성 생성기 의존, 조건부 고객사 bootstrap, 작은 세 세계, 검증의 보정/조기종료 재사용, 단일 프로세스, 선택 수가 적은 지연 표본, 실제 고객 자료·사람의 재측정 부재가 남는다. [공고 대응](../../job-requirements-audit.md)과 [개인 역할·Codex 지원 범위](../../submission-evidence-20261026.md)는 이를 유지한다.
