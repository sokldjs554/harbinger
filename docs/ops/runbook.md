# 운영 런북

## 구성

```
FMS DB(점검·WO·에너지) ──배치/이벤트──▶ features.parquet ──▶ [harbinger api] ──▶ FMS 앱/웹, 콘솔, 리포트
                                         models/<version>/ ◀── eval 파이프라인(재학습) ── 레지스트리 manifest.json
                                         /metrics ──▶ Prometheus
```

기동 시 parquet와 번들을 메모리에 올린다. **2 vCPU·2 GiB는 구성 예시이며, 25개 사이트·2,300 설비의 처리 용량 보장이 아니다.** 기존 3~6초 기동·2~4분 부트스트랩 추정에는 동일 조건의 측정 근거가 없어 운영 기준에서 제외했다. 번들이 없고 `HARBINGER_DEMO_BOOTSTRAP=1`이면 축소 합성 자료로 학습한다. **운영에서는 0으로 두고 번들을 마운트한다.** 인스턴스 사양, Docker CPU/메모리 제한, 실제 프로세스 RSS/CPU 사용량은 서로 다른 값이다. 최신 로컬 측정의 환경·입력 해시·동시 요청 수는 [수정 전후 운영 검증](../verification/completion-20261026/operations/README.md)에 남긴다. 로컬 결과를 AWS 처리량으로 환산하지 않는다.

## 환경변수

| 이름 | 기본 | 뜻 |
|---|---|---|
| `HARBINGER_DATA_DIR` | `data` | parquet 위치 (`inspections, workorders, assets, sites, inspectors, energy, features`) |
| `HARBINGER_MODEL_DIR` | `models` | 레지스트리 (`manifest.json`, `v*/`) |
| `HARBINGER_ARTIFACT_DIR` | `artifacts` | 평가 산출물 JSON (콘솔 모델 탭) |
| `HARBINGER_DEMO_BOOTSTRAP` | `1` | 번들 없을 때 합성 부트스트랩 |
| `HARBINGER_LOG_LEVEL` | `INFO` | JSON 로그 레벨 |

## 재학습

```bash
harbinger features --data data                      # 새 데이터로 피처 재빌드
harbinger eval --data data --models models --artifacts artifacts
# → models/v<timestamp>/ 가 생기고 manifest.latest 가 갱신된다. 롤백은 manifest.latest 를 이전 버전으로 바꾸고 재기동.
```

다음 주기와 수치는 미검증 운영 예시이며 고객별 합의가 필요하다. 재학습 트리거(예시): 월 1회 정기 + 드리프트 경보(`/v1/monitoring/drift` 의 `n_alert ≥ 3` 또는 예측 평균 PSI ≥ 0.25) + 사이트 신규 온보딩 후 3개월.

재학습 전 확인 예시(실제 채택 정책은 [고정 선택 계약](../site-model-policy.md)을 따른다): (1) 최근 테스트 창의 AUROC/Brier 가 이전 버전보다 나쁘지 않은가 (`artifacts/metrics.json`), (2) 캘리브레이션 ECE < 0.02, (3) 순찰 precision@10 이 라운드로빈 대비 ≥ 2배. 하나라도 깨지면 배포하지 않고 `docs/evaluation.md` 의 절차로 원인을 본다.

## 알람 (Prometheus)

`deploy/monitoring/rules.yml`은 실제 exporter의 `*_bucket`, `*_count`, `*_sum`과
순찰과 주 화면의 분석·업로드·다운로드 라우트를 사용한다. `harbinger_workbench_seconds{route,outcome}`는 성공·5xx 실패·의도된 429 거절·기타 4xx를 구분한다. 성공 응답 p95에서 빠른 429를 제외하고, 모든 요청 지연은 기존 histogram에도 남긴다. 세션 토큰은 라벨에 넣지 않는다. 임계값은 합성 데모용 출발점이며
고객별 SLO 검증 결과가 아니다. `for` 기간 동안 조건이 지속되어야 발화하며 조건이 사라지면 복구된다.

| 경보 | 조건 / 지속 | 조치 |
|---|---|---|
| `HarbingerTargetDown` | `up{job="harbinger"} == 0` / 2분 | 프로세스·네트워크·`/metrics` 응답 확인 |
| `HarbingerScrapeMissing` | `up` 시계열 자체 없음 / 5분 | scrape job·서비스 발견·대상 설정 확인. 관측 없음은 정상 0이 아님 |
| `HarbingerModelUnavailable` | 정상 scrape에 모델 gauge가 없거나 로드값 1인 버전 없음 / 5분 | 로그·번들 볼륨·manifest 확인 |
| `HarbingerWorkbenchSlow` | 각 주 화면 경로의 성공 p95 > 2초, 성공 ≥ 20 / 5분 | 자료 크기·동시 계산·모델 정책 검증 비용 확인 |
| `HarbingerWorkbenchFailures` | 각 주 화면 경로의 5xx 증가 / 2분 | 오류 로그·모델·입력 처리 확인 |
| `HarbingerWorkbenchCapacity` | 각 주 화면 경로의 429 증가 / 2분 | 계산 슬롯 2개·대기 최대 4개/10초·세션 한도 8개 확인. 실패율과 별도 집계 |
| `HarbingerPatrolSlow` | 최근 5분 p95 > 2초, 요청 ≥ 20 / 5분 | 설명기(SHAP) 비용·후보 수 확인. `explain=false` 비교. 20건 미만이면 이 경보는 판단 보류 |
| `HarbingerServerErrors` | 최근 5분 5xx 증가율 > 0 / 2분 | JSON 오류 로그와 요청 라우트 확인 |
| `HarbingerFeatureDrift` | 성공한 계산, 성공 시각이 24시간 이내, 경보 피처 ≥ 3 / 5분 | 입력 스키마·누락·분포·관측 창 확인 후 재학습 검토 |
| `HarbingerDriftInsufficientData` | `state="insufficient_data"` 값 1 / 15분 | 기준/현재 창 표본·성숙 관측 여부 확인. 정상 드리프트 0으로 해석하지 않음 |
| `HarbingerDriftError` | `state="error"` 값 1 / 5분 | 예측기·피처 오류 로그 확인. 이전 성공값으로 현재 상태를 대체하지 않음 |
| `HarbingerDriftNotInitialized` | `state="not_initialized"` 값 1 / 5분 | 초기화·모델 로드 로그 확인 |
| `HarbingerDriftMetricsMissing` | 정상 scrape에 드리프트 상태 시계열 없음 / 5분 | exporter 버전·수집 필터 확인 |
| `HarbingerDriftStale` | 마지막 기본 창 계산 시도 후 > 24시간 / 5분 | 입력 배치가 멈췄는지 확인. 재계산 주기는 고객 데이터 주기에 맞춰 조정 |

모니터링은 기동과 공유 인제스트 후 갱신된다. 현재 `/v1/monitoring/drift`는 캐시를 읽으므로
호출만으로 오래된 계산이 갱신되지는 않는다. 원인을 수정한 뒤 정상 인제스트 또는 재기동으로
재계산하고 `harbinger_drift_last_attempt_timestamp_seconds`,
`harbinger_drift_last_success_timestamp_seconds`, `harbinger_drift_status`를 함께 확인한다.
오류·표본 부족일 때 `harbinger_drift_alert_features`는 NaN이며 정상 0이 아니다.

Recording rules는 순찰 p95·요청 수·5xx 증가율과
`harbinger:prediction_p30:mean1h`를 제공한다. 예측 평균은
`rate(harbinger_p30_sum[1h]) / rate(harbinger_p30_count[1h])`이며 관측 건수가 0이면 보류한다.
이는 실제 `latest_rows` 요청에서 관측한 예측으로 같은 설비가 반복 포함된다.
전체 설비의 일별 평균이나 고객사 성능이 아니므로 단순한 전일 대비 2배 변화만으로 자동 경보하지 않는다.

저장소 루트에서 검증 및 로컬 Prometheus를 실행한다(`promtool`은 공식 Prometheus 배포본에 포함):

```bash
promtool check rules deploy/monitoring/rules.yml
promtool test rules deploy/monitoring/rules.test.yml
promtool check config deploy/monitoring/prometheus.yml
prometheus --config.file=deploy/monitoring/prometheus.yml --storage.tsdb.path=/tmp/harbinger-prometheus-data
```

로컬 config의 대상은 `127.0.0.1:8000`이다. Compose에서는 `deploy/prometheus.yml`에
`rule_files: ["/etc/prometheus/monitoring/rules.yml"]`를 넣고 Prometheus 서비스에
`./deploy/monitoring:/etc/prometheus/monitoring:ro` 볼륨을 마운트한다.
`http://localhost:9090/api/v1/rules`에서 평가 상태·최근 오류를,
`http://localhost:9090/api/v1/alerts`에서 pending/firing 상태를 확인한다.
규칙 파일만으로 이메일이 전달되지는 않는다. 실제 운영자 이메일 설정과 기존 AWS 연결·통제 시험은 [외부 알림 안내](external-alerts.md)를 따른다. 실제 수신 확인은 운영자의 회신과 별도 기록이 있어야 완료로 판단한다.
고정 시계열 promtool 검사는 유지한다. 별도로 `scripts/check_local_operations.py`는 실제 로컬 API → Prometheus → 로컬 Alertmanager v2 프로토콜 수신기 → 복구를 검사한다. 1초 수집·10초 관측·2초 지속의 가속 테스트 규칙과 고의 계산 예외를 사용한다. 외부 운영 수신처나 실제 사고 대응 훈련을 검증한 것은 아니다.

## 계산 요청의 대기와 거절

현재 코드는 한 프로세스에서 계산 **2개**를 유지하고, 먼저 들어온 순서대로 최대 **4개**를 기다리게 한다. 대기 시간 한도는 **10초**다. 4개는 활성 슬롯의 두 배로 제한한 구현자의 초기 burst 예산이며, 10초도 고객 합의 SLO나 보편적인 용량 기준이 아니다. 실제 계산을 시작한 뒤의 실행 시간을 강제로 끊는 기능은 아니다. 여러 worker를 추가하면 이 한도와 메모리 세션도 worker별로 분리되므로 전역 한도라고 해석하지 않는다.

계산 대기 초과의 429는 `X-Harbinger-Capacity: queue_full`, 대기 시간초과는 `wait_timeout`과 `Retry-After: 1`을 반환한다. 재시도 간격 안내가 곧 성공 보장은 아니다. 기존 세션 8개 한도의 429는 별도 사유이며 세션을 닫거나 만료를 기다려야 한다. 계산 예외·대기 시간초과 후에도 슬롯과 대기 자리를 반환한다. 기존 분석·업로드·다운로드의 성공/429/5xx 관측은 유지한다.

수정 전 즉시 거절 정책과의 비교는 같은 최종 모델·입력·호스트에서 순서대로 실행하고, 성공한 요청의 지연과 거절 비율을 별도로 비교한다. 고의 15초 지연으로 대기 초과/복구를 검사한 결과는 정상 처리량에 섞지 않는다. 원시 응답·CPU·RSS·환경·입력 해시는 [이번 완료 검증](../verification/completion-20261026/README.md)에 연결한다. 짧은 burst의 성공률이 높아져도 지속적인 처리량이나 AWS 용량이 늘었다고 주장하지 않는다.

공식 문서: [규칙 설정](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/),
[규칙 단위 검사](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/).

## 흔한 장애

- **기동 지연 (예시: probe 제한 240초로 구성한 경우; 보편적 기준 아님)**: 데모 부트스트랩이 느린 머신. `HARBINGER_DEMO_BOOTSTRAP=0` + 번들 마운트로 전환.
- **`/risk` 가 404**: 그 설비의 마지막 점검이 `as_of` 이후이거나 없음. `max_age_days` 는 순찰 목록에만 120일 제한이 있다.
- **SHAP 미설치/실패**: 설명기는 None 으로 내려가고 응답의 `contributions` 가 null — 규칙 기반 근거 문장은 계속 나온다.
- **메모리**: parquet 파일 크기와 로드 후 DataFrame·모델·업로드 세션 RSS를 구분한다. 기존 “150 MB, 사이트 100개부터 샤딩”은 실측 용량 기준이 아니므로 사용하지 않는다. 고객 자료 크기·동시 요청·세션 유지 조건으로 RSS와 CPU를 측정하고 컨테이너 제한에 여유를 둔다.

## 보안·개인정보

점검자 ID 는 가명 처리된 식별자여야 한다. 메모에는 사람 이름·연락처가 들어올 수 있으므로 인제스트 단계에서 마스킹을 권장한다(합성 데이터에는 없다). 공개 데모는 익명이지만 [보호 모드](../protected-mode.md)에서 로그인·고객사 권한을 적용할 수 있다. SSO 연동·다중 서버 세션 공유는 범위 밖이다. 보호 모드의 `/metrics`는 관리자 쿠키 또는 읽기 전용 metrics bearer가 필요하며, 이 토큰으로 다른 API를 호출할 수 없다.

## 기존 공개 환경 갱신

AWS 배포 workflow는 호스트 확인과 실제 배포 단계에 `HARBINGER_EXISTING_INSTANCE_ONLY=1`을 설정한다. 기존 프로젝트 태그의 서버를 찾지 못하면 새 인스턴스·볼륨을 만들지 않고 중단한다. 정확한 main 커밋의 CI 통과 후 기존 서버를 갱신한다. Pages는 `artifacts/release.json` 변경에도 재배포·검증하며, 저장 응답과 AWS 실제 계산을 구분한다. 배포 후 기능 확인은 소수의 순차 요청으로 진행하고 공개 서버에 부하 검사를 수행하지 않는다.

동일 커밋의 배포 재실행도 매번 별도의 릴리스 디렉터리를 사용합니다. 새 이미지를 로드하기 전에 기존 컨테이너의 이미지 ID를 보존하고, 롤백에서는 기존 태그까지 그 ID로 복구합니다. 이번 수정의 근거는 로컬 셸 계약 검사이며 새 AWS 서버 장애/롤백 실증으로 부르지 않습니다. 특징 버전 3으로 이동할 때에는 자료·특징·모델을 함께 생성해 배포해야 합니다.
