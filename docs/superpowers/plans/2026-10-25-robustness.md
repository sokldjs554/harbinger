# Robustness Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 요청한 세 종류의 평가를 실제 실행하고 합성 결과의 범위를 명확히 보고한다.
**Architecture:** scripts/robustness의 순수 평가 함수와 실행기를 기존 모델/특징 API에 연결. 운영 src 및 AWS는 변경하지 않는다.
**Tech Stack:** Python, pandas, NumPy, scikit-learn, PyTorch, pytest.
**Spec:** docs/superpowers/specs/2026-10-25-robustness-design.md

## Global Constraints

- 생성 시드 20260101/20260102/20260103 × 학습 시드 17/29, scale=1, 36개월.
- 메모 누락 25/50%, 문자 삭제 10/30%, 점검 기록 지연 3/7일.
- 30일 purge, 공통 검증 분모, 테스트로 방법 선택 금지.
- 기존 AWS/모델/정적 평가 보존, 외부 유료 호출 없음.

## Review Focus

- 지연 조건에서 결정 시각 이후 정보 또는 미도착 원문이 노출되지 않는지.
- 동일 시각·설비 정답과 공통 분모로 비교하는지.
- 같은 설비의 반복 행이 group+time 보정 양쪽에 섞이지 않는지.
- 단일 클래스·미성숙·빈 fold를 성공/0점으로 처리하지 않는지.
- 시드·데이터·코드 버전과 실제 원시 결과가 일치하는지.

### Task 1: 평가 계약과 실패 회귀 검사
**Files:** scripts/robustness/contracts.py, tests/test_robustness.py
**Interfaces:** perturb_memos, calibration_splits, select_calibration, latest_available, weekly_metrics.
- [x] 테스트를 먼저 작성하고 모듈 부재 실패 확인.
- [x] 결정론적 손상, 보정 분할/선택, 가용성·주간 정답 비교 함수를 구현.
- [x] 테스트 통과, 기존 전체 테스트 통과.

### Task 2: 실행기와 전체 실험
**Files:** scripts/robustness/run.py, docs/verification/robustness-20261025/*
**Interfaces:** Task 1 계약을 사용하고 기존 train_hgb/train_logistic/train_deep/build_features/Refresher 호출.
- [x] 작은 smoke 실행으로 학습→선택→예측→원시 결과→요약의 실제 경로 검사.
- [x] 사전 고정한 3×2 전체 조건 실행, 조건별 체크포인트 저장.
- [x] 원시 결과로 요약 재계산, 해시와 분모 대조.

### Task 3: 해석과 제출 안내
**Files:** docs/verification/robustness-20261025/README.md, docs/user-review.md, README.md
- [x] 결과가 악화한 조건과 보정 채택/보류 근거를 정확히 기록.
- [x] 지인에게 전달할 요청·과업·기록 절차를 간단히 연결.
- [x] 독립 코드 검토와 관련 수정.
- [ ] 최종 자료를 포함한 CI와 PR 통합.

## Execution ledger

- 2026-10-25: 사용자 요청 범위에서 실험 설계를 고정. 기존 CI d9b5d7a 성공 및 깨끗한 기준 확인.

- Independent review: no Critical; two Important reproducibility findings (stale stress caches and late overwrite guard). Both reproduced with failing tests before fixes. Stress frames now always rebuild, world cache checks generator/source/config provenance, output existence is checked before preparation or writes.
- Review scope decisions: full-scale empirical findings are checked after execution using saved predictions; real-customer/usability evidence stays unverified; unchanged architectures are compared as-is rather than redesigned. The experiment measures existing model sensitivity, not a new deployed model.
- Calibration asset grouping refers only to calibrator fitting records. The underlying predictor may have seen those assets in the earlier training period; this is not an entirely unseen-customer experiment.

- Full execution: three scale=1, 36-month worlds × two learning seeds completed (911.7s / 870.4s / 879.9s per world). All six raw prediction/fold/hash rechecks passed. Final report discloses the large PyTorch memo-missing sensitivity and conditional calibration choice.
