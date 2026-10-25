# 사용자 검토 반영 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 설비 탐색·시간 해석·업로드 확인에 관한 두 검토의 혼란을 줄인다.
**Architecture:** 기존 FastAPI 세션 분석과 vanilla JS 점검대장을 확장한다. 미확인 평가 차단은 서버에서 수행하며 정적 예제는 기존 응답을 보존한다.
**Tech Stack:** Python / FastAPI / pandas / JavaScript / Playwright.
**Spec:** docs/superpowers/specs/2026-10-25-usability-design.md

## Global Constraints
- 실측·재검토·수리 상태를 만들어 넣지 않는다.
- 기존 모델/성능 산출물을 재학습 없이 보존한다.
- 업로드 API 기본값은 observation_confirmed=false. 합성 기본 예제는 생성 범위가 알려져 있다.

## Review Focus
- 미확인 업로드의 충분한 30일 기간도 음성 정답·지표를 노출하지 않아야 한다.
- 고객/JSON/CSV/Markdown 경로 모두 동일한 확인 여부를 적용한다.
- 파일·종료일 변경 시 이전 체크가 다른 데이터로 넘어가지 않아야 한다.
- 저장 예제의 위치 미제공을 허구로 채우지 않아야 한다.
- 좁은 화면·조건 변경 중 실패에도 실제 적용된 날짜와 내보내기를 보존한다.

### Task 1: API·입력 오류 계약
Files: src/harbinger/api/analysis.py, api/upload.py, api/routers/workbench.py; tests/test_workbench.py, tests/test_upload.py.
Interfaces: analyze(..., observation_confirmed=True); upload query observation_confirmed=false; analysis assets include floor/zone.
- [x] 회귀 테스트: 미확인/확인 세션의 동일 예측과 다른 평가 노출, 층/구역, 헤더 포함 행 오류. 기존 코드에서 실패 확인.
- [x] 최소 구현 후 해당 테스트 통과.
- [x] pytest 전체 통과 후 커밋.

### Task 2: 화면과 실제 브라우저 동작
Files: src/harbinger/console/{index.html,workbench.js,reports.js,workbench.css}, scripts/check_review_usability.py, scripts/check_browser.py, docs/demo 동기화.
Interfaces: floor/zone and observation_confirmed from Task 1; saved evidence fallback uses same asset/date only.
- [x] 브라우저에서 층 검색, 미적용 날짜, 미확인 업로드/해제 테스트 작성 및 기존 화면 실패 확인.
- [x] 위치·과거 기준·현재 상태 미확인·조건 적용·선택적 완전성 안내 반영.
- [x] 저장 예제·실제 API·320/390/650px 회귀 검증과 캡처.

### Task 3: 검토 기록·배포·검증
Files: docs/user-reviews/*, docs/user-review-template.md, README.md, docs/upload-format.md, docs/verification/usability-20261025/*, artifacts/release.json.
- [x] A 원문 보존/빈 양식 복구, B 전달 기록과 미확인 항목, 개선 대응표 및 재검토 절차.
- [x] README/입력 명세/릴리스 해시 갱신; 테스트·린트·브라우저 검사.
- [ ] 독립 코드 검토 후 중요한 결함 수정, PR/CI/Docker 통과, 병합 및 기존 AWS·Pages 배포 확인.
