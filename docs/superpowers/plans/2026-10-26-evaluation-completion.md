# 평가·처리량·제출 마무리 실행 계획

> **For agentic workers:** Use the task contracts below with RED→GREEN regressions and one final whole-branch review. Independent experiment execution and selection-evaluator work may be delegated without overlapping file ownership.

**Goal:** 사용자가 명시한 네 기술 보완, 운영 처리량 비교, 제출/기존 배포를 끝낸다.
**Architecture:** 기존 HGB/PyTorch/FastAPI와 승인된 UI를 유지한다. 이전 자료 재실행과 새 자료의 검증 선택/평가를 분리한다. 실제 서비스 선택 함수와 평가를 공유한다.
**Tech Stack:** 기존 Python·Pandas/NumPy·sklearn·PyTorch·TensorFlow·FastAPI·Docker·AWS/Pages.
**Spec:** `docs/superpowers/specs/2026-10-26-evaluation-completion.md`.

## Global Constraints

기준5a7f947, 과거 기록 보존, 새 유료 리소스/공개 부하/새 기능 금지, 결과를 보고 선택 기준 수정 금지. 사용자가 이번 범위의 병합·공개 배포를 승인했다.

## Review Focus

- 새 HGB 선택에 test 점수/라벨을 전달하지 않음; 선택 파일 해시 고정 후 평가.
- 필수 설비>K인 실제 선택과 고정K 순위의 분모/이름 구분.
- 고객사별 날짜 수 불균등/한 고객사/불완전 쌍에서 같은 추정대상 또는 보류.
- 계산 대기열이 유한하고 예외/시간초과 후 슬롯을 누수하지 않음.
- 새 모델 선택이 업로드·원문/설명·모델 추적·배포 버전에 일관 적용됨.

## Tasks

- [x] 상태·기준 커밋 확인, 별도 `finish/evaluation-20261026` 브랜치, 사전 설계 고정.
- [ ] 1. `scripts/memo_robustness.py`, `memo_summary.py`를 기준 커밋 고정 체크아웃에서 그대로 실행. 기존3×2 계약/원자료해시 대조, 새 결과 디렉터리와 전후 표. 새 선택을 위한 독립 테스트로 주장하지 않음.
- [ ] 2. `scripts/default_model_selection.py`와 `tests/test_default_model_selection.py`: 미래 테스트를 읽지 않는 validation 단계/선택freeze/test 단계. 고정 새 시드·원자료/특징/선택/예측 해시, AUROC/PR/Brier/주간K10 및 실행 변동. 통과 후보 선택·미달 기본유지·test 변경 불변을 RED→GREEN. 실제 결과에 따른 기본 모델/설명 변경은 별도 테스트 후 적용.
- [ ] 3~4. `src/harbinger/prescribe/priority.py`, `eval/patrol.py`, 필요시 `eval/patrol_summary.py`, `tests/test_service_patrol_evaluation.py`: 실제선택 공유, 동일필수조건/예산, 초과수와 공통대상, 순위·서비스 두 결과. 불균등날짜/균등날짜·빈자료/한사이트·동점·반복블록 회귀 RED→GREEN. `eval/run.py` 연결은 root 통합.
- [ ] 기술 1~4의 결과를 확인한 뒤에만 5 진행.
- [ ] 5. `api/routers/workbench.py` 계산 제한과 `scripts/check_local_operations.py` 측정 검토. 동일 새 모델로 기준5a7 제한과 수정 제한을 비교. 필요시 `api/compute.py`, `tests/test_compute_limits.py`: 고정슬롯·유한대기·시간초과·초과429·예외반환을 RED→GREEN. 순차/동시4/초과부하·실제 경보/복구. 성능 목표 수치를 본 뒤 바꾸지 않음.
- [ ] 6. 최종 학습·산출물·문서/저장데모 설명·제출 수치/역할 명세 갱신. 관련 회귀·전체311+·TF·API·실제브라우저/모바일·Docker·CI, 별도 reviewer 및 확인된 중요 결함 수정.
- [ ] PR16 업데이트·최종CI·병합·mainCI·기존AWS/Pages배포·버전/기능 확인. 링크·미완료 이유와 한계 기록.
