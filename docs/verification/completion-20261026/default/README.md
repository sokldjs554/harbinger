# 전체 HGB 유지 결정과 분리된 테스트

새 합성 자료 시드 202610261/262/263 × 학습 시드 17/29, 36개월·scale1, 시간 분할 24/6/6개월이다. 전체 116개 특징과 메모 유래 특징을 모두 뺀 84개 특징을 비교했다. 점검 예산은 고객사·주간 기준일마다 10개이며 같은 성숙 설비 집단에서 비교했다.

[사전 계약](../../../superpowers/specs/2026-10-26-evaluation-completion.md)은 로컬 커밋 `744e6d0a7baa007a2897c5a661bdbc29244a099d`로 실험 전에 고정했다. 검증 구간은 확률 보정에도 사용했으므로 독립 테스트가 아니다. `selection.json`과 `freeze.json`을 먼저 생성한 뒤 테스트 예측을 계산했다. 검증 6회 모두 메모 제외 모델의 적중률이 낮고 Brier가 높아 **전체 HGB를 유지**했다. 이후 테스트 결과로 선택을 바꾸지 않았다.

- [선택 및 조건별 미달 이유](selection.json), [검증 자료 해시 고정](freeze.json)
- [전체 실행·평균·표준편차·범위](summary.json), [원시 예측 재계산 기록](verification.txt)
- 각 자료/학습 시드 아래 `validation`, `test`에 동일 대상 행, 두 모델의 예측 배열과 지표가 있다.
- 고객사 시계열 전체를 묶은 2,000회 bootstrap은 같은 세계의 두 학습 시드에 같은 재표집을 적용한다. 세 합성 세계에 조건부인 불확실성이며 실제 고객 구간이나 독립 표본 6개의 추론이 아니다.

실행 당시 스크립트는 `source-before-integrity-guard/default_model_selection.py`에 보존했다. 실험이 끝난 뒤 검토에서 **향후 테스트 실행 전 소스 해시 확인**을 보완했다. 당시 검증/테스트 파일과 선택·freeze 파일을 소급 수정하지 않았다. 현재 스크립트는 새 실험에서 데이터 생성기·특징·학습·평가 코드 해시를 적합 전에 기록하고, 모든 세계의 소스가 그대로인지 테스트 예측 전에 확인한다. 과거 실행의 해시를 현재 소스 해시로 바꾸어 주장하지 않는다.

저장 예측 재계산(모델 재학습 없음):

```bash
PYTHONPATH=src:. python docs/verification/completion-20261026/default/verify-executed.py
```

같은 고정 조건으로 새로운 빈 경로에서 전체 재실행:

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src
python -m scripts.default_model_selection validation --work /tmp/hb-default-new --out /tmp/hb-default-results
python -m scripts.default_model_selection freeze --work /tmp/hb-default-new --out /tmp/hb-default-results
python -m scripts.default_model_selection test --work /tmp/hb-default-new --out /tmp/hb-default-results
```

현재 결과를 알고 다시 실행하면 새 독립 실험이 아니다. 훈련된 바이너리와 생성 원자료는 저장소에 중복 넣지 않았으며, 해당 명령으로 복원한다. 공개 결과 폴더는 기존 실험의 원시 예측과 관측 행을 보존한다.
