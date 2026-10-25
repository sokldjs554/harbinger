# 고객사 모델 정책: 검증·활성화·롤백

이 기능은 운영 절차를 재현하는 선택형 기능입니다. 합성 자료에서 동작을 확인하며 실제 고객별 최적화·고장 예방 효과·운영 성능을 입증하지 않습니다. 정책 파일이 없으면 기존 HGB 기본 예측을 그대로 사용합니다.

## 선택 계약

`PYTHONPATH=src:. python scripts/site_policy.py select`는 이미 로드 가능한 로컬 번들의 기본 HGB와 `logistic`, `without_text`, `without_history`만 비교합니다. 정책에서 모델 파일 경로나 임의 pickle을 지정할 수 없습니다. JSON 정책을 읽는 과정에는 역직렬화가 없습니다. 로컬 번들 자체는 기존 레지스트리의 **관리자 신뢰 파일**이어야 합니다.

선택 기간은 모델의 `boundary_version=2`, `max_observed_at`(학습뿐 아니라 보정 관측 종료) **이후**여야 합니다. 같은 사이트·설비·점검 기준시각의 동일한 행과 완전한 30일 결과로 모든 후보를 평가합니다. 결측 결과, 미성숙 라벨, 중복 대상, 잘못된 확률, 누락된 관측 메타데이터를 거부합니다. CLI는 피처 provenance의 원본 parquet 해시를 확인합니다. `--outcomes-complete`는 데이터 담당자가 고장 기록 완전성을 확인했다는 명시적 입력이며, 자동으로 완전성을 추정하지 않습니다.

사이트별 기본 기준은 검증 행 50개, 양성·음성 각 3개, 기본 모델 대비 Brier 오차 0.001 이상 감소 및 정상 입력 Brier 오차 비증가입니다. 부족하거나 개선이 없으면 기본 모델을 유지합니다. 이 기준은 운영 임계값 검증이 아니며 반복 행은 독립 표본으로 해석하지 않습니다. 후보별 Brier와 행 수, 결과·예측값·대상 식별자를 증거 JSON에 보존합니다. 검증 결과로 피처·가중치를 다시 학습하지 않습니다.

정책에는 번들 버전/전체 구성 파일 SHA-256, 데이터 파일 집합 해시, 검증 구간, 관측 종료, 선택 시각, 후보별 선택, 증거 파일 SHA-256이 들어갑니다. 검증 결과의 30일 성숙 시점은 실제 선택 시각(UTC)을 넘을 수 없습니다. 새 정책의 가용 시점은 `max(검증 종료 + 30일, 실제 선택 시각)`입니다. 활성화 기록 시각도 서빙 하한입니다. 과거 날짜로 선택 시각을 지정하는 옵션은 없습니다. 따라서 오늘 고른 정책을 과거 백테스트에 소급 적용하지 않습니다.

`--test-start`는 아직 시작하지 않은 별도의 보류 평가 경계여야 하며 선택 및 최초 활성화는 그 전에 끝나야 합니다. 선택기는 이 구간을 읽거나 채점하지 않습니다. 분석·재현도 활성 정책의 `policy_test_start` 이전에는 시간 보류 성능으로 인정하지 않습니다. 기존 합성 평가의 과거 test 구간을 새 검증 기간으로 사용했다면 그 기간은 새 정책의 미사용 test가 아닙니다. 신규 보류 평가 성능은 별도로 수집해야 합니다.

## 실행

```bash
OMP_NUM_THREADS=1 PYTHONPATH=src:. python scripts/site_policy.py select \
  --data-dir data --model-dir models \
  --validation-start 2025-01-01 --validation-end 2025-06-01 \
  --test-start 2027-01-01 --outcomes-complete --output proposal.json

PYTHONPATH=src:. python scripts/site_policy.py activate \
  --model-dir models --proposal proposal.json --expected-revision none

# 다음 활성화에는 이전 명령이 반환한 revision을 사용합니다.
PYTHONPATH=src:. python scripts/site_policy.py activate \
  --model-dir models --proposal next-proposal.json --expected-revision PRIOR_SHA256

PYTHONPATH=src:. python scripts/site_policy.py rollback \
  --model-dir models --to-revision OLD_SHA256 --expected-revision CURRENT_SHA256
```

예시 날짜는 실제 번들의 학습·보정 종료 및 관측 종료에 맞춰 바꿔야 합니다. 최초 정책 이전의 기본 모델로 복귀하려면 `rollback --to-revision none --expected-revision CURRENT_SHA256`을 사용합니다. 이 기본 모델 복귀도 새 리비전과 `baseline_restored` 이유로 기록됩니다. 정책 파일을 수동 삭제하는 방식은 감사 가능한 rollback이 아닙니다.

POSIX 파일 잠금과 이전 revision 비교(CAS)가 동시 변경을 방지합니다. 증거는 `models/site-policy-evidence/<hash>.json`, 리비전은 `models/site-policy-history/<revision>.json`, 현재 포인터는 `models/site-policy.json`에 보존합니다. 파일과 디렉터리를 fsync하고 같은 디렉터리의 임시 파일에서 원자 교체합니다. 활성 포인터 교체 전에 장애가 나면 이전 리비전이 남고 새 이력은 참조되지 않은 상태로 남을 수 있습니다. rollback은 과거 내용을 새 리비전으로 기록하므로 변경 시점과 이전 포인터가 보존됩니다. 단일 호스트 파일 저장소용이며 분산 파일 시스템의 잠금 보장은 별도 검증이 필요합니다.

## 서빙과 설명

한 번의 혼합 사이트 추론은 동일한 정책 스냅샷을 사용합니다. 실제 선택 후보가 `p30`을 계산하며 asset·분석 JSON·CSV·Markdown·순찰·주기·재현 결과에 `selected_model`, `policy_revision`, `policy_reason`을 기록합니다. what-if도 마지막 점검 기준일에 사용할 수 있는 동일 모델로 기준/시나리오를 비교합니다. 비기본 후보의 SHAP는 `unavailable_for_selected_model`이며 기본 HGB의 기여도를 대신 보여 주지 않습니다. 규칙 기반 기록 근거는 모델 기여도와 다릅니다. 기존 deep 위험/생존 출력은 별도 보조 모델 출력입니다.

번들 파일 변경, 로드 시점과 현재 가중치 해시 불일치, 증거 변경, 후보 누락, 잘못된 정책은 `invalid_policy`로 기본 모델에 복귀합니다. 시간 경계 이전은 `selection_not_available`, 검증에 없는 사이트는 `unlisted_site`입니다. 정책이 있는 재현 요청은 캐시를 재사용하지 않아 증거·가중치 변경을 검사합니다. 활성 정책을 사용하는 동안 모델/증거 파일을 직접 수정하지 마세요.

해시는 우발적 변조·출처 불일치를 감지합니다. 관리자 파일 권한을 가진 공격자가 증거와 모든 해시를 함께 다시 쓰는 경우를 막는 전자서명은 아닙니다. 모델 디렉터리 쓰기 권한은 서버 일반 사용자에게 주면 안 됩니다. 오프라인 CLI만 제공하며 웹 활성화 API는 없습니다.
