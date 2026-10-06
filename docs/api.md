# API

`harbinger serve` 또는 `docker compose up` 후 <http://localhost:8000/docs> (OpenAPI). 콘솔은 <http://localhost:8000/console/>.

모든 `as_of` 는 `YYYY-MM-DD`, 생략하면 데이터 끝 시점. 응답의 `model_version` 은 레지스트리 버전이다.

| 메서드 | 경로 | 무엇을 돌려주나 |
|---|---|---|
| GET | `/health` `/ready` `/version` | 생존 · 모델 로드 여부 · 모델/데이터 메타(헤드라인 지표, git sha, 피처 해시) |
| GET | `/v1/sites?as_of=` | 사이트 목록 + 설비 수 + 평균/최대 P30 |
| GET | `/v1/sites/{site}` | 사이트 요약: 고위험 수, 최근 90일 고장·다운타임, 종류별 P30 |
| GET | `/v1/sites/{site}/assets?sort=p30&limit=` | 설비별 P30, 마지막 점검, 판정 |
| GET | `/v1/sites/{site}/assets/{asset}/risk?explain=true` | **P30(HGB·캘리브레이션), 위험 네트 P30, 12구간 생존곡선, 권고 점검 주기, SHAP 기여도, 근거(최근 메모 원문·지적 항목·이력)** |
| GET | `/v1/sites/{site}/patrol/today?k=10` | **오늘 먼저 볼 k개** — 기대손실 순, 법정 기한 임박 강제 포함, 동선 정렬, 근거 문장 |
| GET | `/v1/sites/{site}/schedule` | 설비별 권고 점검 주기(생존곡선 기반, 법정 상한 적용)와 현재 주기 대비 단축/연장 수 |
| GET | `/v1/sites/{site}/energy/anomalies?days=120` | 기대 전기사용량 vs 실측, 잔차 7일 이동평균 z, 이상일 |
| GET | `/v1/sites/{site}/quality?days=180` | 점검자별 기록 신뢰도(형식적 메모·직전 복사·짧은 체류·지연·전부양호) |
| GET | `/v1/sites/{site}/report?format=json\|md` | **실증(PoC) 리포트** — 위 모두를 한 문서로 |
| POST | `/v1/sites/{site}/inspections` | 새 점검 기록 인제스트 → 해당 사이트 피처 재계산 → 갱신된 P30 반환 (202) |
| GET | `/v1/models` | 레지스트리 버전 목록 |
| GET | `/v1/monitoring/drift?window_days=60` | 피처 PSI(경고/경보), 예측 분포 이동 |
| GET | `/v1/artifacts/{name}` | 평가 산출물 JSON (metrics·ablation·calibration·survival·energy·patrol·loso·importance) |
| GET | `/metrics` | Prometheus |

## 예

```bash
curl -s localhost:8000/v1/sites | jq '.sites[0]'
curl -s "localhost:8000/v1/sites/S01/patrol/today?k=8" | jq '.items[] | {rank, name, p30, mandatory, reasons}'
curl -s "localhost:8000/v1/sites/S01/assets/A-S01-0007/risk" | jq '{p30, recommendation, contributions: .explanation.contributions[:3], memos: [.explanation.evidence.recent_inspections[].memo_highlighted]}'
curl -s "localhost:8000/v1/sites/S01/report?format=md"
curl -s -X POST localhost:8000/v1/sites/S01/inspections -H 'content-type: application/json' -d '[{
  "inspection_id":"N-NEW-1","asset_id":"A-S01-0007","inspector_id":"I-S01-01",
  "scheduled_at":"2026-01-05T09:00:00","performed_at":"2026-01-05T10:12:00","method":"beacon","dwell_seconds":95,
  "overall":1,"items":{"noise":1,"vibration":0},"memo":"소음 증가, 미세 진동 감지","photo_count":1}]'
```

## 설계 메모

- **읽기 전용 분석 API + 인제스트 1개.** 영속화는 FMS DB 의 몫이다. 인제스트는 "새 점검이 들어오면 위험도가 바로 바뀐다"를 보여 주기 위한 메모리 상태 변경이며, 운영에서는 FMS 의 점검 저장 이벤트(아웃박스/큐)를 구독해 같은 함수를 호출한다.
- **설명은 두 겹.** SHAP 기여도(수치 피처가 확률을 얼마나 움직였나) + 근거 인용(그 피처를 만든 실제 메모·항목·이력). 공공 고객 보고서에는 후자가 들어간다.
- **as_of 를 모든 조회에 둔 이유.** 실증(PoC)은 "지난 6월 1일 기준으로 이 목록을 줬으면 그 뒤 30일에 무엇이 났나"를 보여 주는 일이다. 과거 시점 재현이 API 1급 기능이어야 한다.
- 메트릭 라우트 라벨은 `{id}` 로 접어 카디널리티를 막는다.
