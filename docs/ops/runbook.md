# 운영 런북

## 구성

```
FMS DB(점검·WO·에너지) ──배치/이벤트──▶ features.parquet ──▶ [harbinger api] ──▶ FMS 앱/웹, 콘솔, 리포트
                                         models/<version>/ ◀── eval 파이프라인(재학습) ── 레지스트리 manifest.json
                                         /metrics ──▶ Prometheus
```

단일 컨테이너(2 vCPU · 2 GiB)로 25개 사이트·2,300 설비를 서빙한다. 기동 시 parquet 와 번들을 메모리에 올린다(약 3~6초). 번들이 없고 `HARBINGER_DEMO_BOOTSTRAP=1` 이면 축소 합성 데이터로 번들을 만든다(2~4분) — **운영에서는 0 으로 두고 번들을 마운트한다.**

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

재학습 트리거(권장): 월 1회 정기 + 드리프트 경보(`/v1/monitoring/drift` 의 `n_alert ≥ 3` 또는 예측 평균 PSI ≥ 0.25) + 사이트 신규 온보딩 후 3개월.

재학습 전 확인: (1) 최근 테스트 창의 AUROC/Brier 가 이전 버전보다 나쁘지 않은가 (`artifacts/metrics.json`), (2) 캘리브레이션 ECE < 0.02, (3) 순찰 precision@10 이 라운드로빈 대비 ≥ 2배. 하나라도 깨지면 배포하지 않고 `docs/evaluation.md` 의 절차로 원인을 본다.

## 알람 (Prometheus)

`deploy/monitoring/rules.yml`은 실제 exporter의 `*_bucket`, `*_count`, `*_sum`과
라우트 `/v1/sites/{site_id}/patrol/today`를 사용한다. 임계값은 합성 데모용 출발점이며
고객별 SLO 검증 결과가 아니다. `for` 기간 동안 조건이 지속되어야 발화하며 조건이 사라지면 복구된다.

| 경보 | 조건 / 지속 | 조치 |
|---|---|---|
| `HarbingerTargetDown` | `up{job="harbinger"} == 0` / 2분 | 프로세스·네트워크·`/metrics` 응답 확인 |
| `HarbingerScrapeMissing` | `up` 시계열 자체 없음 / 5분 | scrape job·서비스 발견·대상 설정 확인. 관측 없음은 정상 0이 아님 |
| `HarbingerModelUnavailable` | 정상 scrape에 모델 gauge가 없거나 로드값 1인 버전 없음 / 5분 | 로그·번들 볼륨·manifest 확인 |
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
Alertmanager 수신처·연락 경로 설정은 별도이며 이 규칙 파일만으로 알림이 전달되지는 않는다.
현재 검증은 고정 시계열에 대한 실제 promtool 실행이며 운영 사고·알림 전달 훈련을 완료했다는 뜻이 아니다.

공식 문서: [규칙 설정](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/),
[규칙 단위 검사](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/).

## 흔한 장애

- **기동 240초 초과 (Cloud Run startup probe 실패)**: 데모 부트스트랩이 느린 머신. `HARBINGER_DEMO_BOOTSTRAP=0` + 번들 마운트로 전환.
- **`/risk` 가 404**: 그 설비의 마지막 점검이 `as_of` 이후이거나 없음. `max_age_days` 는 순찰 목록에만 120일 제한이 있다.
- **SHAP 미설치/실패**: 설명기는 None 으로 내려가고 응답의 `contributions` 가 null — 규칙 기반 근거 문장은 계속 나온다.
- **메모리**: features.parquet(14만 행 × 110열) ≈ 150 MB 메모리. 사이트 100개 규모면 사이트별 샤딩 또는 DB 조회로 바꾼다.

## 보안·개인정보

점검자 ID 는 가명 처리된 식별자여야 한다. 메모에는 사람 이름·연락처가 들어올 수 있으므로 인제스트 단계에서 마스킹을 권장한다(합성 데이터에는 없다). 공개 데모는 익명이지만 [보호 모드](../protected-mode.md)에서 로그인·고객사 권한을 적용할 수 있다. SSO 연동·다중 서버 세션 공유는 범위 밖이다. 보호 모드의 `/metrics`는 관리자 쿠키 또는 읽기 전용 metrics bearer가 필요하며, 이 토큰으로 다른 API를 호출할 수 없다.
