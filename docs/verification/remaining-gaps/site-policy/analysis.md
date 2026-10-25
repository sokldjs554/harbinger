# harbinger 분석 보고서

- 데이터: synthetic-example
- 모델: v20261025-231343
- 예측 기준: 2026-10-25T14:28:12.607083
- 모델 관측 종료: 2023-09-01T00:00:00
- 정답 관측 종료: 2024-01-01T00:00:00
- 평가: withheld
- 사이트 S01: without_text / 정책 140b05c16fcd62bd05406e89eb214526443b281acccdc60d81798bb7a80caea7 / validation_brier
- 사이트 S03: baseline / 정책 140b05c16fcd62bd05406e89eb214526443b281acccdc60d81798bb7a80caea7 / baseline_not_improved
- 사이트 S04: baseline / 정책 140b05c16fcd62bd05406e89eb214526443b281acccdc60d81798bb7a80caea7 / baseline_not_improved
- 사이트 S02: baseline / 정책 140b05c16fcd62bd05406e89eb214526443b281acccdc60d81798bb7a80caea7 / baseline_not_improved

30일 내 비계획 고장 위험의 탐색적 순위. 합성 학습 모델이며 안전·고장 예방 효과를 보증하지 않습니다.

기준일 이후 30일의 관측이 완료되지 않았습니다.
사이트 모델 선택 이후 예약된 보류 평가 시작일 이전입니다.
양성·음성 설비가 각각 3개 이상이어야 성능을 비교합니다.

| 방법 | Precision@K | Recall@K | AUROC |
|---|---:|---:|---:|
| current_model | 평가 보류 | 평가 보류 | 평가 보류 |
| logistic | 평가 보류 | 평가 보류 | 평가 보류 |
| without_text | 평가 보류 | 평가 보류 | 평가 보류 |
| without_history | 평가 보류 | 평가 보류 | 평가 보류 |
| last_inspection_rule | 평가 보류 | 평가 보류 | 평가 보류 |
| age_rule | 평가 보류 | 평가 보류 | 평가 보류 |
| recent_repair_rule | 평가 보류 | 평가 보류 | 평가 보류 |
| oldest_inspection_rule | 평가 보류 | 평가 보류 | 평가 보류 |
| random_expectation | 평가 보류 | 평가 보류 | 평가 보류 |

고객사 보류(LOSO)는 별도 실험입니다. 단일 기준일 표에는 신뢰구간을 붙이지 않습니다.
반복 관측의 불확실성은 저장소 평가 산출물의 고객사 단위 bootstrap을 참고하세요.
이 보고서는 실제 고객 실증이나 인과 효과의 증거가 아닙니다.