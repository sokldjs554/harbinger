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

| 조건 | 뜻 | 조치 |
|---|---|---|
| `harbinger_model_loaded == 0` 5분 | 번들 로드 실패 | 로그의 `store loaded` 부재 확인, 볼륨·버전 확인 |
| `histogram_quantile(0.95, harbinger_request_seconds{route="/v1/sites/{id}/patrol/today"}) > 2s` | 설명기(SHAP) 비용 | `explain=false` 로 호출하거나 후보 수(3k) 축소 |
| `harbinger_drift_alert_features >= 3` | 피처 분포 이동 | 재학습 검토, 데이터 파이프라인 변경 여부 확인 |
| `rate(harbinger_requests_total{status=~"5.."}[5m]) > 0` | 서버 오류 | 로그 `exc` 필드 |
| `harbinger_p30` 분포의 평균이 하루 새 2배 이동 | 입력 데이터 문제(결측·단위) | 인제스트 소스 확인 |

## 흔한 장애

- **기동 240초 초과 (Cloud Run startup probe 실패)**: 데모 부트스트랩이 느린 머신. `HARBINGER_DEMO_BOOTSTRAP=0` + 번들 마운트로 전환.
- **`/risk` 가 404**: 그 설비의 마지막 점검이 `as_of` 이후이거나 없음. `max_age_days` 는 순찰 목록에만 120일 제한이 있다.
- **SHAP 미설치/실패**: 설명기는 None 으로 내려가고 응답의 `contributions` 가 null — 규칙 기반 근거 문장은 계속 나온다.
- **메모리**: features.parquet(14만 행 × 110열) ≈ 150 MB 메모리. 사이트 100개 규모면 사이트별 샤딩 또는 DB 조회로 바꾼다.

## 보안·개인정보

점검자 ID 는 가명 처리된 식별자여야 한다. 메모에는 사람 이름·연락처가 들어올 수 있으므로 인제스트 단계에서 마스킹을 권장한다(합성 데이터에는 없다). 콘솔은 인증이 없다 — FMS 의 SSO 뒤에 두거나 Cloud Run IAM / App Runner VPC 로 접근을 제한한다.
