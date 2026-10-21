# 검증 기록 — 2026-10-21

전체 합성 모델 버전은 **v20261021-103259**, 비교 기준 원본 커밋은 **fd346c75ddae39fa6383096d7dd6adabccfdb044**다. 초기 main은 변경하지 않고 `codex/dwi-evaluation-web`에서 작업했다. 최초 미커밋 변경과 AGENTS.md는 없었고 원본은 별도 worktree에도 보존했다.

## 점검대장 UI 개편

기존 카드 중심 화면을 왼쪽 기능 목록·중앙 설비 대장·오른쪽 개별 기록으로 교체했다. 모바일에서는 선택한 설비의 기록을 별도 화면으로 열며, 돌아가기/Esc로 닫고 선택한 설비에 초점을 복원한다. 실제 모델 및 평가 수치는 그대로이고 전체 합성 모델 버전도 `v20261021-103259`다.

- 전체 테스트 **70 passed, 1 skipped**, 41.98초: [로그](ledger-tests.txt). 선택적 TensorFlow 패리티만 제외했다.
- 실제 전체 모델 API 및 저장 데모 양쪽에서 예제·원문·탭·고객사·평가 보류·다운로드·모바일 상세/복귀를 확인했다. 실제 API에서는 정상/오류 CSV와 빈 결과도 확인했다. [API 체크](ledger-live/checks.json), [저장 데모 체크](ledger-static/checks.json). JavaScript 오류 0개.
- 1440×1080 데스크톱과 390×844 모바일 Chromium에서 직접 조작했다. [대장 화면](ledger-static/priority.png), [첫 화면](ledger-static/landing.png), [모바일 대장](ledger-static/mobile.png), [모바일 개별 기록](ledger-static/mobile-record.png), [업로드 오류](ledger-live/upload-error.png).
- 새 UI로 실제 조작 영상 **80.00초**를 다시 녹화했다. [영상](../demo/walkthrough.mp4), [녹화 정보](ledger-recording.json).
- 전체 예제 CSV 재업로드 중 기존 다운로드에 관측 종료 이후 점검 2건이 포함되는 결함을 발견했다. [수정 전 회귀 실패](ledger-export-before.txt)를 확인한 뒤 API와 정적 CSV 생성 모두 선언된 관측 종료까지만 내보내도록 수정했다. 수정된 전체 예제 7,352행의 검증과 실제 웹 업로드가 통과했다. 모델 학습·평가 계산을 변경한 수정은 아니다.
- 코드·데모·예제 CSV의 릴리스 해시와 README 수치 검사도 통과했다. 아래의 이전 검증 기록과 화면은 당시 버전의 이력으로 보존한다.

## 직접 확인한 실행

- 원본 전체 실험: [로그](full-before.txt), bundle v20261021-102542, 1,097.5초.
- 수정 후 전체 실험: [로그](full-after.txt), bundle v20261021-103259, 1,536.0초. 시드 20260101, scale 1, 36개월, HGB·로지스틱·Cox/AFT·PyTorch 3변형·8사이트 LOSO. 최대 40 epoch 설정을 유지하고 검증 NLL 조기종료를 적용했다.
- 두 실행은 같은 원자료 SHA-256 및 같은 패키지 환경을 사용했다. OMP/BLAS/PyTorch 스레드 1. 원본 실행은 소스 수정 없이 런타임 torch 스레드만 1로 제한했다.
- 경계 회귀 테스트: [수정 전 실패](boundary-before.txt), [수정 후](boundary-after.txt). 이후 미래 기록 변형 후 입력·정답·학습 결과 불변 테스트를 추가했다.
- 생존의 정확한 구간 경계: [수정 전 실패](survival-edge-before.txt), [수정 후](survival-edge-after.txt). [전체 데이터 영향 확인](survival-edge-impact.txt): 해당 경계에 정확히 일어난 사건 0행이므로 기존 전체 실험 모델의 정답 할당은 바뀌지 않았다.
- 독립 코드 검토 후 무작위 비교군·과거 재현 평가 보류: [수정 전](review-regressions-before.txt), [수정 후](review-regressions-after.txt).
- 앞선 API 포함 전체 테스트 **62 passed, 1 skipped**, 117.89초: [실행 로그](integration-earlier.txt). 이 로그 이후 소규모 수정이 있어 최종 전체 통과 기록으로 부르지 않는다. TensorFlow 미설치로 패리티 1개를 건너뛰었다.
- 최종 네트워크 독립 테스트 **49 passed, 1 skipped**: [실행 로그](final-offline-tests.txt). 모델 실제 학습·예측, CSV 검증, 경계·평가 계약을 포함한다.
- 정적 데모 데이터는 수정 후 실제 모델로 2개 기준일 × 전체 및 25개 고객사 조건을 계산했다. 임의 업로드/날짜 실행으로 표현하지 않는다. `scripts/release_manifest.py --check`로 결과·소스·데모의 해시 및 모델 버전을 대조한다.

## 최종 API·브라우저 확인

구현 소스 커밋 `524879a17fdb43f2a9b412cb2e8e50beb7973c59`에서 [CI 테스트 작업](https://github.com/sokldjs554/harbinger/actions/runs/39597165426/job/119212226434)이 통과했다.

- 전체 테스트 **69 passed, 1 skipped**. TensorFlow 선택 의존성의 패리티 1개를 제외했다. 70개 수집 목록과 CI 진행 출력으로 확인했다.
- Ruff 검사·포맷, 실제 seed 7 / scale 0.15 / 12개월 모델 학습·평가, API 스모크, 문서 수치·릴리스 해시 검사 통과. [출력 발췌](ci-api-browser.txt).
- 실제 FastAPI에 연결한 Chromium에서 예제, 원문, 모든 탭, 고객사 선택, 관측 부족, 빈 결과, 잘못된 CSV와 정상 CSV 업로드, CSV/JSON/Markdown 다운로드, 모바일, 세션 닫기를 확인했다. 페이지 JavaScript 오류 0개. [체크 결과](browser-live/checks.json), [모바일](browser-live/mobile.png), [업로드 오류](browser-live/upload-error.png).
- 이 API 화면의 모델은 CI에서 새로 학습한 **축소 합성 모델**이다. README 성능과 정적 제출 화면의 전체 모델 `v20261021-103259`와 혼동하지 않는다. `browser/`에는 이전 부분 실행 화면을 보존하며 최종 검증 근거는 `browser-live/`다.
- 정적 데모는 [최종 verify 작업](https://github.com/sokldjs554/harbinger/actions/runs/39597159691/job/119212205715)에서도 통과했다. 예제·원문·탭·고객사·평가 보류·다운로드·모바일·세션 닫기 및 실제 조작 영상 79.88초를 확인했다. 저장소 [영상](../demo/walkthrough.mp4)과 [화면](browser-static/checks.json)은 동일 전체 모델의 직전 성공 실행(39596071478, 영상 79.84초)에서 가져왔다. 최종 실행에서는 초기 로딩 중 클릭 방지도 확인했다.

## 공개 배포와 컨테이너 실행

로컬 환경은 소켓 생성/연결, Chromium IPC 및 Docker 소켓 접근을 `Operation not permitted`로 차단했다. 권한 확장 요청도 완료되지 않아 GitHub Actions에서 실제 API·브라우저 및 컨테이너를 검증한다. 이는 자동 승인 심사에서 거절됐다는 응답과는 다르다.

- **Docker 이미지 빌드와 실행 통과.** [image 작업](https://github.com/sokldjs554/harbinger/actions/runs/39597165426/job/119213518062)에서 컨테이너가 합성 모델을 새로 학습(평가 72.8초)하고 서버를 시작했다. `/health`, `/v1/workbench/info` HTTP 200 및 실행 UID 10001을 확인했다. [출력 발췌](docker-runtime.txt). 컨테이너 예제 버전은 `v20261021-121613`으로 전체 실험 번들과 다르다.
- **공개 배포 완료.** 사용자 승인 후 [PR #1](https://github.com/sokldjs554/harbinger/pull/1)을 main에 병합했다. 기존 `github-pages` 보호 규칙은 변경하지 않았다. [main 배포 실행](https://github.com/sokldjs554/harbinger/actions/runs/39599050299)에서 정적 브라우저 검증·영상 녹화·배포·공개 파일 대조가 통과했다. [공개 데모](https://sokldjs554.github.io/harbinger/)의 HTML·JS·CSS·모델 응답 JSON·예제 CSV 5개를 저장소 파일과 SHA-256으로 비교했고 모델 `v20261021-103259` 및 MP4 제공을 확인했다. [확인 로그](public-deploy.txt). 공개 서버는 저장 응답 재생이며 실제 업로드·새 계산은 FastAPI/Docker에서 실행한다.

## CI에서 발견한 추가 결함

최신 전체 테스트는 통과했으나 12개월 축소 데이터(seed 7) 스모크에서 성숙 보정 정답이 24행만 남아 일부 KFold 학습에 한 클래스만 존재하는 오류가 발생했다. 이를 재현하고 보정 보류·원시 모델 유지로 수정했다. [수정 전](calibration-sparse-before.txt), [수정 후](calibration-sparse-after.txt). [전체 실험 영향](calibration-full-impact.txt): pooled 및 8개 LOSO의 모든 fold에 두 클래스가 있어 기존 전체 실험의 선택·확률은 변하지 않는다.

## 재현 명령

README의 환경 설치 후:

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/fill_numbers.py --check
python scripts/release_manifest.py --check
harbinger serve --port 8000
# 별도 터미널
python scripts/check_browser.py --url http://localhost:8000/console/
python scripts/record_workbench.py --url http://localhost:8000/console/
docker compose up --build api
```

수정 전후 비교는 원본 소스를 별도 worktree에서 동일 생성 데이터로 평가한 뒤 `scripts/compare_boundary.py --before-data <원본데이터> --before-models <원본모델> --before-artifacts <원본산출물>`을 실행한다. 첫 과다 스레드 시도와 중단된 테스트는 최종 실행에 합산하지 않았다.

## 해석 제한

합성 데이터의 단일 시드 실험이다. 고객사별 LOSO는 25곳 중 유형별 선정 8곳이며 미선정 17곳을 기록한다. 메모의 전체 모델 추가 이득은 확인하지 못했고 고객사별 개선도 일관되지 않는다. 익명화된 실제 고객 데이터·반장 순찰 정책·비용 절감·수리 인과 효과는 검증하지 않았다. 같은 설비·주간 창이 겹치므로 주간 성능은 고객사 묶음 bootstrap을 사용했다. 단일 기준일 웹 지표는 기술통계이며 유의성을 주장하지 않는다.
