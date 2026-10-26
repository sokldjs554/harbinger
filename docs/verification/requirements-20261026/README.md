# 공고 요구 기술 감사 — 2026-10-26

[공고 전체 대응표](../../job-requirements-audit.md). 사용자가 제공한 공고 화면과 “FastAPI·AWS 유지, TensorFlow 실행 보완” 선택이 범위다. 기준 main은 `27051f07bd7597bd53442c98c281f9240f942e4f`, 작업 브랜치는 `audit/dwi-requirements-20261026`이다. 시작 시 미커밋 변경이 없었으며 기존 데이터·모델·브랜치·검증 기록을 보존했다. 이번 변경은 새 PR에서 검토하며 공개 AWS·Pages에 배포하지 않았다.

## 확인한 범위

- [모델·전처리·평가 감사](raw/model-audit.md), [API·운영 감사](raw/service-audit.md)에 실제로 읽은 파일과 제외한 범위를 기록했다. 파일 해시 목록을 모든 줄의 수동 검토로 표현하지 않는다.
- [전체 변경 검토](raw/final-review.md)의 Important I1은 이후 수정했다. 과거 v2 모델과 현재 v3 특징을 섞어 계산할 수 있던 경로를 차단했다. 과거 결과 읽기는 허용하고 새 업로드·점검 추가·가상 점검은 전처리와 모델을 함께 재학습하도록 안내한다. [실패](raw/legacy-rebuild-red.txt) → [수정 후](raw/legacy-rebuild-green.txt).
- 학력·경력은 잘 모르겠습니다. 실제 고객 실증, GCP 실행, 실제 고객 트래픽/SLA는 확인되지 않았다. Flask는 사용하지 않는다. AWS 공개 합성 데모의 기존 운영 근거와 이번 로컬 검증을 구분한다.

## 원인·수정·회귀

| 영역 | 재현 원인과 수정 | 실행 근거 |
|---|---|---|
| TensorFlow 사건 경계 | 30/60일 사건을 다음 구간에 넣던 floor를 PyTorch와 같은 `(왼쪽, 오른쪽]` 규칙으로 수정 | `tests/test_keras_parity.py`, `raw/tf-boundary-red.txt` |
| TensorFlow 결측·학습 대조 | 전부 결측인 열의 중앙값 NaN을 안전한 대치값으로 처리. 손실/로짓 기울기, 동일 가중치 네트워크 출력과 마지막 위험 출력층 커널 기울기 대조. 학습률·클리핑·조기종료 조건을 명시 | `raw/tf-missing-red.txt`, `raw/tf-controlled-tests.txt`, 아래 실제 학습 결과 |
| PyTorch 고객사 가리기 | 최초 30% 고정 마스크와 매 epoch 30%가 중복되어 기대 51%. 원래 입력을 보존하고 epoch마다 한 번 적용 | `raw/model-reproductions.json`, 전후 전용 회귀 12개 |
| 합성 자료 기간 | 시작 월을 무시한 연도 계산과 월말 날짜 오류. 달력 월 덧셈과 양의 정수 기간 검증 | `raw/model-regressions-red.txt`, `raw/model-regressions-final.txt` |
| 생존 평가·그림 | HGB만 성숙 분류 행에서 C-index 계산. 생존 비교는 검열 행을 포함한 동일 집단 사용. CNN 제거를 전체 메모 제거라고 표시하던 명칭과 IBS 지원 기간 수정 | `after/survival.json`, [새 그림](figures/survival.png) |
| 에너지 수치 | OLS 음수 예상량을 1e-6으로 바꾸어 비정상적으로 큰 잔차 생성. 비양수/비유한 예상량은 결측으로 보류 | `raw/energy-reproduction.txt`, `raw/energy-fresh-diagnostics.json` |
| 에너지 이상 보정 | 학습 7개 관측과 추론 7일 창 불일치. 7일·최소 3관측으로 통일하고 충분한 창이 없는 사이트에 전역 sigma를 대신 쓰지 않음 | `raw/energy-regressions-red.txt`, `raw/energy-regressions-green.txt` |
| 특징/모델 호환성 | 특징 정의 v3 도입, 캐시·모델 버전 불일치 거절. 과거 모델로 현재 특징 재생성을 시작하기 전에 거절 | `tests/test_feature_bundle_compatibility.py`, `raw/bundle-semantics-*.txt`, `raw/legacy-rebuild-*.txt` |
| API 자료·입력 경계 | 빈 이력 보고서 None 포맷 오류, what-if 체크 값 범위 누락, 짧은 CSV 기본 기준일이 첫 기록 이전, NaT/시간대 입력 오류 수정 | `tests/test_service_audit_regressions.py`, `raw/api-checks.json` |
| 캐시·배포 복구 | 점검 추가 후 재현 캐시 무효화. 같은 SHA 재배포마다 고유 디렉터리 생성, 이전 이미지 ID를 보존하여 실패 시 기존 태그/실행 환경 복원 | `raw/service-red.txt`, `raw/service-green.txt`. 배포 복구는 로컬 셸 대역 검사이며 실제 AWS 장애 실험 아님 |
| 설명 정확성 | 오라클은 미래 개입을 전부 반영한 진짜 확률/상한이 아닌 고정 위험률 참고선. 최소 점검 간격 7일이 위험 예산 5%를 항상 보장하지 않음을 명시 | 모델 설계·한계 문서 |

## 동일 조건 전체 모델 재실행

원자료 7개 파일 SHA-256 일치, 합성 고객사 25개·36개월·131,201행, 시드 20260101, OMP/OpenBLAS 각 2스레드. quick/LOSO 생략 없이 이전 소스와 수정 소스를 각각 실행했다. 전체 테스트 22,001행 중 성숙 분류 18,439행을 채점한다. [정확한 수치·입력 해시](before-after.json), [수정 전 전체 산출물](before/metrics.json), [수정 후 전체 산출물](after/metrics.json), [원시 로그](raw/full-after.txt).

| 지표 | 수정 전 재실행 | 수정 후 재실행 |
|---|---:|---:|
| HGB AUROC | 0.7696088847 | 0.7679922529 |
| HGB PR-AUC | 0.2444964125 | 0.2405582502 |
| HGB Brier ↓ | 0.0683772796 | 0.0686477635 |
| HGB 상위 10개 적중률 | 24.8444% | 23.8222% |
| PyTorch 문자+사이트 AUROC | 0.7642697909 | 0.7638045028 |
| 에너지 회귀 MAE | 335.7359364 | 335.7359364 |
| 에너지 MAPE / R² | 0.0255411 / 0.9969997 | 0.0255411 / 0.9969997 |

**주요 성능은 낮아졌다.** 결함 수정이 성능 향상을 뜻하지 않는다. 여러 수정을 함께 적용한 결과라 한 수정의 인과 효과로 분해하지 않는다. 저장 데모의 과거 모델은 그대로이며 새 로컬 모델은 `v20261026-074224`, 수정 전 재실행 모델은 `v20261026-072939`다. 커밋 전 작업 트리에서 학습했으므로 번들의 `git_sha`는 조상 커밋일 뿐, 학습 소스는 [파일별 해시](source-provenance.json)로 식별한다. 각 모델 파일 해시는 `before/model-hashes.json`, `after/model-hashes.json`에 있다.

수정 후 시간 보류 절제 결과는 전체 AUROC 0.7679923, 메모 유래 특징 제거 0.7731927, 고장 이력 제거 0.7459891이다. 이 한 실행에서 메모 추가의 향상을 주장할 수 없다. 고객사 보류는 25개 중 선정한 8개이며 에너지 특징을 제외한다. 이전/이후 무보정 평균 AUROC는 모두 0.7706076이고 자체 정답 보정은 Brier를 개선하지 않았다. [절제 원시 값](after/ablation.json), [고객사 보류](after/loso.json). 실제 현장 일반화의 근거가 아니다.

HGB 생존 C-index의 과거 0.7051561은 18,439개 성숙 분류 행이었다. **같은 과거 예측**을 생존 공통 22,001행으로 다시 계산하면 0.7088413이다([근거](raw/model-artifact-check.json)). 새 모델 공통 집단은 0.7072246이다. 집단을 바꾼 수치 상승을 모델 개선으로 해석하지 않는다. IBS는 30·60·90·180일만 지원하며 360일은 보류한다.

## TensorFlow 실제 실행과 실패 보존

별도 Python 3.12.14 / TensorFlow CPU 2.21.0 / Keras 3.15.1 / Torch 2.14.1+cpu. 작은 합성 자료 10개월·scale 0.12·자료 시드 11, 학습 5개월·검증 2개월, 학습 시드 0·요청 12 epoch. 두 점수 모두 조기종료에 사용한 **검증 점수이며 독립 테스트가 아니다**.

| 실험 | Torch NLL | Keras NLL | NLL 차이 | 기존 `<0.25` 기준 |
|---|---:|---:|---:|---|
| 독립 초기화 | 0.5667100 | 0.8363211 | 0.2696111 | **실패** |
| 별도 통제: 학습 전 초기 가중치 공유 | 0.5667100 | 0.5626722 | 0.0040378 | 통과 |

통제 실험 AUROC는 0.4258035 / 0.4263875로 차이 0.0005839가 기존 `<0.12` 기준을 통과했다. **둘 다 0.5 미만이므로 성능 우수성 근거로 쓰지 않는다.** 독립 초기화의 실패를 통제 실험의 통과로 덮지 않았다. 기준을 완화하지 않았고, 통제 조건은 [실행 전 계약](raw/tf-controlled-contract.json)에 남겼다. 배치 순서·dropout까지 동일한 학습은 아니다.

[독립 초기화 실패 원본](raw/tf-comparison-initialized-independently.json), [통제 실행 JSON](raw/tf-controlled-comparison.json), [실행 로그](raw/tf-controlled-comparison-stable.txt). CLI 종료 0은 유한한 계산 완료를 뜻한다. 차이 기준 통과 여부는 JSON `comparison_passed`를 확인해야 한다. CI 테스트는 별도로 두 기준을 assert한다. 12개 TensorFlow 검사와 전체 311개 검사에서 건너뜀 없이 실행했다.

## 통합 검증

- 변경 전 **264 통과·선택 TensorFlow 1 건너뜀**, 최종 **311 통과·4개의 기존 DataFrame 단편화 경고**: [기준](raw/baseline-tests.txt), [최종](raw/full-tests-final-green.txt).
- 최종 중간 실행의 5건 실패도 [보존](raw/full-tests-final.txt)했다. 신규 호환성 검사가 오래된 모니터링 테스트용 번들의 버전 누락을 검출했다. 테스트용 캐시/번들에 현재 버전을 함께 명시했으며, 원래 drift 검증과 실제 코드의 호환성 검사를 우회하지 않았다.
- 새 전체 모델의 **실제 로컬 API**: 건강/준비/버전, 빈 보고서, 날짜·체크 값 거절, 에너지 자료 없음/2일 관측 보류 [결과](raw/api-checks.json).
- 실제 API 브라우저: CSV 업로드·모델 계산, 세 가지 다운로드, 오류 시 기존 기록 유지, 목록↔상세·날짜·초점, 모바일 320/390/650px 필터·스크롤/조건 복원 [결과](browser/checks.json). 에너지 정상/관측 부족/자료 없음 데스크톱·모바일 [결과](energy-browser/checks.json). JS 페이지 오류 0. 브라우저 검사는 일부 오류 응답을 의도적으로 주입하여 오류 보존 동작도 확인하며 정상 계산은 실제 API다.
- 주요 문서 6개의 자동 숫자 마커 **37개**, 추가 과거 주요 숫자 **17개** 대조: [자동](raw/marked-number-checks.json), [추가](raw/manual-number-checks.json). 모든 과거 원시 행을 사람이 하나씩 검증했다는 의미가 아니다.
- Docker는 로컬 디스크 여유가 약 1.6GB라 새 이미지를 로컬에서 빌드하지 않았다. 대신 [구현 커밋 CI](https://github.com/sokldjs554/harbinger/actions/runs/40289442379)의 TensorFlow·통합·이미지 작업이 **모두 통과**했다. Docker 이미지 빌드와 실제 분석/CSV/세 형식 다운로드/에너지 보류, 소스 78개 해시·UID 10001을 확인했다. [CI 요약](ci/summary.json), [Docker API](ci/docker-api.json), [이미지 해시](ci/docker-image.json). 문서 기록만 추가한 후속 커밋의 최종 CI 상태는 [PR #16](https://github.com/sokldjs554/harbinger/pull/16/checks)에서 확인할 수 있다.
- CI의 Docker 런타임 모델은 작은 부트스트랩 `v20261026-081423`(6개 합성 고객사·24개월·666설비)이며 전체 25개 고객사 재학습 모델과 구분한다. `/version.git_sha`는 컨테이너 안에 Git 저장소가 없어 null이다. 소스 식별은 CI 체크아웃과 이미지의 78개 파일 해시 일치로 검증했다. 2 CPU·2GiB는 **컨테이너 제한**으로, 실제 사용량이나 AWS 사양이 아니다.
- CI 로컬 API 부하는 분석·업로드·다운로드 × 동시 1/4 × 각 20건 = 120건이다. 서버/전송 실패율 0, 동시 4에서는 각 경로 20건 중 18건이 의도된 429였다. 순차 p95는 분석 0.152초·업로드 0.653초·다운로드 0.137초, 최대 표본 RSS 589,361,152바이트였다. 전체 측정값과 조건은 [원시 요약](ci/load-summary.json), [환경/입력](ci/manifest.json)에 있다. [부하 후 세 경로 정상 복구](ci/load-recovery.json), [실제 Prometheus 경보 발화·로컬 수신·해제](ci/alert-result.json)도 확인했다. 경보는 명시한 시험용 임계값을 사용했으며 운영 임계값을 낮추지 않았다. AWS 처리량으로 해석하지 않는다.

### 이번 실행 캡처

기존 승인된 디자인을 유지했다. 아래는 새 모델을 연결한 로컬 검증 화면이며 공개 배포 화면이 아니다.

[데스크톱 목록](browser/list.png) · [상세](browser/detail.png) · [모바일 필터 접힘](browser/mobile-filter-collapsed.png) · [펼침](browser/mobile-filter-expanded.png) · [적용](browser/mobile-filter-applied.png) · [모바일 상세](browser/mobile-detail.png) · [에너지 관측 부족](energy-browser/energy-mobile-insufficient.png)

커밋한 실행 로그 사본은 Git 공백 검사를 위해 줄 끝 공백만 제거했다. 실패 메시지·수치·검사 결과는 보존했으며 원래 작업 경로의 로그는 변경하지 않았다.

## 재현 명령

기본 환경은 `pip install -c constraints.txt -e '.[dev]'`, TensorFlow 환경은 [실행 문서](../../running.md#tensorflow-대조-검사)를 따른다. 기존 원자료·모델은 덮어쓰지 않는다.

```bash
# 전체 검사 (TensorFlow를 설치한 환경)
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1 pytest -ra
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/fill_numbers.py --check
python scripts/release_manifest.py --check

# 수정 전: 해당 커밋을 별도 체크아웃하고 같은 data/*.parquet 원자료를 복사한다.
# 수정 후: 현재 소스에서 별도 출력 경로 사용. features.parquet/meta는 이전 캐시를 복사하지 않는다.
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 harbinger eval \
  --data /tmp/hb-requirements-after/data --models /tmp/hb-requirements-after/models \
  --artifacts /tmp/hb-requirements-after/artifacts --seed 20260101

harbinger synth --out /tmp/hb-tf-fixture/data --start 2024-01-01 --months 10 --scale 0.12 --seed 11
harbinger features --data /tmp/hb-tf-fixture/data
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1 \
  python scripts/keras_parity_check.py --features /tmp/hb-tf-fixture/data/features.parquet \
  --train-months 5 --val-months 2 --epochs 12 --seed 0 --shared-initialization --out /tmp/tf-controlled.json

HARBINGER_DATA_DIR=/tmp/hb-requirements-after/data HARBINGER_MODEL_DIR=/tmp/hb-requirements-after/models \
  HARBINGER_ARTIFACT_DIR=/tmp/hb-requirements-after/artifacts HARBINGER_DEMO_BOOTSTRAP=0 \
  uvicorn harbinger.api.main:app --host 127.0.0.1 --port 18021
# 다른 터미널; Playwright Chromium 설치 필요
python scripts/check_browser.py --url http://127.0.0.1:18021/console/ --out /tmp/browser-checks
python scripts/check_energy_browser.py --url http://127.0.0.1:18021/console/advanced.html#energy --out /tmp/energy-checks
python docs/verification/requirements-20261026/raw/check_api.py
```

수정 전 재현은 기준 커밋의 코드를 별도 경로에 풀고 `PYTHONPATH`를 그 `src`로 지정했다. 원자료 해시와 패키지 버전은 각각 `before-after.json`, `source-provenance.json`을 확인한다. 의존성/하드웨어가 바뀌면 부동소수점·학습 결과가 완전히 같다고 보장하지 않는다.

## 남은 한계·미실행

이번 소스를 공개 배포하거나 실제 AWS 롤백 장애를 유발하지 않았다. 새 유료 리소스·공개 서버 부하 시험도 하지 않았다. 과거 메모 강건성의 3세계×2학습 반복 실험 전체는 수정 후 다시 실행하지 않았으므로 과거 구현의 결과로 표시했다. TensorFlow 독립 초기화 기준 실패, IPCW 동시 사건/검열 규칙·검열 가정, 불균등 고객사 관측에서 순찰 bootstrap 추정대상의 정합성, 단일 프로세스/메모리 세션, 실제 고객·장기 SLA는 남은 한계다. 상세는 [한계 문서](../../limitations.md)와 원래 감사 보고서에 있다. 테스트 통과로 모든 약점이 없어졌다고 선언하지 않는다.
