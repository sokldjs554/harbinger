# 검증 기록 — 2026-10-21

전체 합성 모델 버전은 **v20261021-103259**, 비교 기준 원본 커밋은 **fd346c75ddae39fa6383096d7dd6adabccfdb044**다. 초기 main은 변경하지 않고 `codex/dwi-evaluation-web`에서 작업했다. 최초 미커밋 변경과 AGENTS.md는 없었고 원본은 별도 worktree에도 보존했다.

## 직접 확인한 실행

- 원본 전체 실험: [로그](full-before.txt), bundle v20261021-102542, 1,097.5초.
- 수정 후 전체 실험: [로그](full-after.txt), bundle v20261021-103259, 1,536.0초. 시드 20260101, scale 1, 36개월, HGB·로지스틱·Cox/AFT·PyTorch 3변형·8사이트 LOSO. 최대 40 epoch 설정을 유지하고 검증 NLL 조기종료를 적용했다.
- 두 실행은 같은 원자료 SHA-256 및 같은 패키지 환경을 사용했다. OMP/BLAS/PyTorch 스레드 1. 원본 실행은 소스 수정 없이 런타임 torch 스레드만 1로 제한했다.
- 경계 회귀 테스트: [수정 전 실패](boundary-before.txt), [수정 후](boundary-after.txt). 이후 미래 기록 변형 후 입력·정답·학습 결과 불변 테스트를 추가했다.
- 생존의 정확한 구간 경계: [수정 전 실패](survival-edge-before.txt), [수정 후](survival-edge-after.txt). [전체 데이터 영향 확인](survival-edge-impact.txt): 해당 경계에 정확히 일어난 사건 0행이므로 기존 전체 실험 모델의 정답 할당은 바뀌지 않았다.
- 독립 코드 검토 후 무작위 비교군·과거 재현 평가 보류: [수정 전](review-regressions-before.txt), [수정 후](review-regressions-after.txt).
- 앞선 API 포함 전체 테스트 **62 passed, 1 skipped**, 117.89초: [실행 로그](integration-earlier.txt). 이 로그 이후 소규모 수정이 있어 최종 전체 통과 기록으로 부르지 않는다. TensorFlow 미설치로 패리티 1개를 건너뛰었다.
- 최종 네트워크 독립 테스트 **48 passed, 1 skipped**: [실행 로그](final-offline-tests.txt). 모델 실제 학습·예측, CSV 검증, 경계·평가 계약을 포함한다.
- 정적 데모 데이터는 수정 후 실제 모델로 2개 기준일 × 전체 및 25개 고객사 조건을 계산했다. 임의 업로드/날짜 실행으로 표현하지 않는다. `scripts/release_manifest.py --check`로 결과·소스·데모의 해시 및 모델 버전을 대조한다.

## 아직 확정하지 않은 항목

로컬 환경은 소켓 생성/연결, Chromium IPC 및 Docker 소켓 접근을 `Operation not permitted`로 차단한다. 실행 권한 확장 요청은 완료되지 않고 대기하다 사용자에 의해 중단됐다. 자동 승인 심사에서 거절됐다는 응답을 받은 것은 아니다.

- 앞선 Docker 이미지 빌드는 성공했지만 현재 최종 코드의 컨테이너 실행 검증은 미완료다.
- 앞선 Chromium 탐색은 예제·원문·탭·다운로드까지 실행됐고 날짜 상한 처리에서 실패했다. 수정 후 최종 브라우저 통과 기록은 아직 없다. `browser/` 기존 이미지는 그때의 **축소 모델 부분 실행**으로 최종 제출 화면이 아니다.
- 80초 실제 조작 영상 생성 스크립트는 준비했으나 현재 최종 영상은 아직 없다.
- 기존 공개 데모 주소는 확인했으나 새 브랜치의 공개 배포 여부는 아직 미확정이다.
- GitHub Actions에 실제 API 브라우저 조작·비루트 Docker 실행·정적 데모 검증/영상 녹화를 추가했다. 실행 결과를 확인하기 전에는 완료로 표시하지 않는다.

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
