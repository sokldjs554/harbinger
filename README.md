# harbinger

**사람이 쓴 점검 기록에서 설비 고장의 전조를 읽는다.** 센서가 없는 건물에서, 점검자가 남긴 체크리스트·한국어 메모·고장 이력·에너지 검침만으로
30일 내 고장 확률과 생존곡선을 추정하고, **오늘 먼저 볼 설비·권고 점검 주기·근거 문장**으로 바꿔 API 와 리포트로 내보내는 분석 엔진입니다.

> 모든 데이터는 **합성(SYNTHETIC)** 입니다. 실제 고객·설비·점검자 정보 없음. 생성 모델은 [docs/synthetic-generator.md](docs/synthetic-generator.md) 에 전부 공개되어 있고, 아래 숫자는 그 모델 아래에서의 값입니다.

![console](docs/images/console.png)

## 왜 이 주제인가

(주)디더블유아이는 센서 회사가 아닙니다. 15년간 **사람이 설비 앞에 가서 NFC·비콘을 찍고 체크하고 메모를 적는 일**을 앱으로 옮긴 회사이고(유비스 마스터, 정부청사 13곳 G-FMS),
2026년형 모델에 "축적된 데이터로 장애를 예측하고 최적 운영 시나리오를 제시하는 AI" 를 넣겠다고 공표했습니다. 그 회사에 쌓인 데이터는 센서 시계열이 아니라
**불규칙한 시점의, 사람이 쓴, 주관적이고 결측 많은 점검 기록**입니다. 흔한 센서 기반 예지보전(RUL 회귀)은 그 데이터에 맞지 않습니다.

harbinger 는 그 데이터 형태를 그대로 받아들입니다. 조사 과정과 "회사가 어떤 지원자를 원하는가"에 대한 판단은 [docs/company-research.md](docs/company-research.md) 에 있습니다.

## 무엇이 다른가

| 흔한 접근 | harbinger |
|---|---|
| 센서 시계열 → RUL 회귀 | **체크리스트 + 한국어 메모 + 고장 이력 + 월 검침**만으로 30일 고장 확률·생존곡선 |
| 메모는 버린다 | 메모의 **약신호**("약간의 소음", "미세 진동", "누유 흔적 소량")를 렉시콘 + 문자 CNN 으로 신호화. 메모에 등장한 증상군 수(와 그 롤링 합)가 SHAP 중요도에서 체크리스트 항목들보다 위 |
| 모든 점검 기록을 같은 무게로 | **점검 품질 감사**(복붙 메모·체류 수초·지연)를 피처이자 **증거 가중치**로 — 형식적으로 찍은 "양호"는 덜 믿는다 |
| 고객사마다 모델 하나 | 정부청사·병원·호텔·오피스 25개 사이트를 한 모델로, **신규 고객사(콜드스타트)** 는 leave-one-site-out 으로 따로 측정 |
| 확률만 내고 끝 | **처방**: 기대손실 순 순찰 상위 K(법정점검 강제 포함, 동선 정렬) · 위험 예산 기반 권고 점검 주기 · SHAP + **실제 메모 원문 인용** |
| 노트북 | FastAPI · 모델 레지스트리 · PSI 드리프트 · Prometheus · Docker · Cloud Run / App Runner 구성 · 실증 리포트 엔드포인트 |

## 제품 흐름

```
점검 기록(체크리스트·메모·체류·지연) ─┐
고장수리·예방정비·부품교체 이력      ─┼─▶ point-in-time 피처 102개 ─▶ HGB 분류기(isotonic) ──▶ P30
사이트 일별 에너지(기온·재실 보정)   ─┘                              └▶ 이산시간 위험 네트(메모 CNN·사이트 임베딩) ─▶ S(t)
                                                                                  │
          오늘 순찰 상위 K ◀── 기대손실 × 법정기한 × 동선 ◀──────────────────────────┤
          권고 점검 주기   ◀── 1 − S(Δ) ≤ 5 %, 법정 상한 ◀──────────────────────────┤
          근거 문장        ◀── SHAP 상위 기여 + 메모 원문·지적 항목·이력 ◀───────────┘
          실증 리포트(md)  ◀── 위 전부 + 에너지 이상 + 점검자 신뢰도
```

## 실측 결과 (테스트 기간 2025-07 ~ 2025-12)

숫자는 `scripts/fill_numbers.py` 가 `artifacts/*.json` 에서 채우고 CI 가 불일치를 검사합니다. 전체 표와 읽는 법은 [docs/evaluation.md](docs/evaluation.md).

**30일 내 비계획 고장 (점검 행 <!-- num:metrics.classifier.hgb_full.n|,d -->0<!-- /num -->개, 양성 <!-- num:metrics.classifier.hgb_full.pos_rate|.1% -->0<!-- /num -->)**

| | AUROC | PR-AUC | Brier | ECE |
|---|---:|---:|---:|---:|
| 마지막 점검 판정만 (현장의 현재 규칙) | <!-- num:metrics.baselines.last_inspection.auroc|.3f -->0<!-- /num --> | <!-- num:metrics.baselines.last_inspection.pr_auc|.3f -->0<!-- /num --> | <!-- num:metrics.baselines.last_inspection.brier|.4f -->0<!-- /num --> | – |
| **harbinger HGB** | **<!-- num:metrics.classifier.hgb_full.auroc|.3f -->0<!-- /num -->** | **<!-- num:metrics.classifier.hgb_full.pr_auc|.3f -->0<!-- /num -->** | **<!-- num:metrics.classifier.hgb_full.brier|.4f -->0<!-- /num -->** | **<!-- num:metrics.classifier.hgb_full.ece|.4f -->0<!-- /num -->** |
| 이산시간 위험 네트 (P30) | <!-- num:survival.deep.text+site.p30.auroc|.3f -->0<!-- /num --> | <!-- num:survival.deep.text+site.p30.pr_auc|.3f -->0<!-- /num --> | <!-- num:survival.deep.text+site.p30.brier|.4f -->0<!-- /num --> | <!-- num:survival.deep.text+site.p30.ece|.4f -->0<!-- /num --> |
| 오라클 — 숨은 열화 상태를 아는 상한 | <!-- num:metrics.baselines.oracle_latent_state.auroc|.3f -->0<!-- /num --> | <!-- num:metrics.baselines.oracle_latent_state.pr_auc|.3f -->0<!-- /num --> | <!-- num:metrics.baselines.oracle_latent_state.brier|.4f -->0<!-- /num --> | – |

**어떤 데이터가 기여하나 (절제, AUROC)**: 체크리스트만 <!-- num:ablation.checklist_only.auroc|.3f -->0<!-- /num --> → +메모 텍스트 <!-- num:ablation.+text.auroc|.3f -->0<!-- /num --> → +점검 품질 <!-- num:ablation.+text+quality.auroc|.3f -->0<!-- /num --> → +고장 이력 <!-- num:ablation.+text+quality+history.auroc|.3f -->0<!-- /num --> → +에너지 <!-- num:ablation.full(+energy).auroc|.3f -->0<!-- /num -->.
전체에서 메모를 빼면 <!-- num:ablation.full−text.auroc|.3f -->0<!-- /num -->.

![ablation](docs/images/ablation.png)

**오늘 순찰 상위 10개 — 그 뒤 30일에 실제로 고장난 비율** (<!-- num:patrol.days -->0<!-- /num -->일 × 25 사이트, 기본 고장률 <!-- num:patrol.base_rate|.1% -->0<!-- /num -->)

| 라운드로빈(가장 오래 안 본 순) | 무작위 | 마지막 점검 판정순 | **harbinger** |
|---:|---:|---:|---:|
| <!-- num:patrol.methods.round_robin.precision_at_k|.1% -->0<!-- /num --> | <!-- num:patrol.methods.random.precision_at_k|.1% -->0<!-- /num --> | <!-- num:patrol.methods.last_inspection.precision_at_k|.1% -->0<!-- /num --> | **<!-- num:patrol.methods.harbinger_hgb.precision_at_k|.1% -->0<!-- /num -->** (라운드로빈 ×<!-- num:patrol.methods.harbinger_hgb.lift_vs_round_robin|.1f -->0<!-- /num -->) |

테스트 기간 고장 <!-- num:patrol.recall_top20pct.breakdowns_evaluated|,d -->0<!-- /num -->건 중 <!-- num:patrol.recall_top20pct.recall|.0% -->0<!-- /num --> 는 고장 직전 마지막 점검 때 이미 사이트 위험 상위 20 % 안에 있었습니다.

**생존·콜드스타트·에너지**: Cox C-index <!-- num:survival.lifelines.cox.c_index|.3f -->0<!-- /num --> · 위험 네트 C-index <!-- num:survival.deep.text+site.c_index|.3f -->0<!-- /num --> (IBS <!-- num:survival.deep.text+site.ibs|.4f -->0<!-- /num -->) ·
처음 보는 사이트(LOSO, 자체 데이터 0개월) AUROC <!-- num:loso.mean_by_months.0.auroc|.3f -->0<!-- /num --> → 12개월 <!-- num:loso.mean_by_months.12.auroc|.3f -->0<!-- /num --> ·
일 전기 kWh 회귀 MAPE <!-- num:energy.test.mape|.1% -->0<!-- /num -->, 여름 잔차와 숨은 냉방설비 열화의 상관 <!-- num:energy.oracle_check.summer_corr_resid_vs_cooling_degradation|.2f -->0<!-- /num -->.

**정직하게 적어야 할 것**: 오라클 상한은 생성 모델의 열화-고장 결합 강도(`BETA_SCALE`)에 달려 있고, 그 값은 "모델 간 차이가 보이도록" 올린 것입니다([왜 그랬는지](docs/synthetic-generator.md#2-숨은-열화와-고장)).
콜드스타트 오프셋은 Brier 를 거의 바꾸지 못했습니다. 로그손실로 학습한 HGB 는 이미 잘 캘리브레이션돼 있어 isotonic 은 검증 구간에서 Brier 가 좋아질 때만 채택합니다(이번 번들: <!-- num:metrics.classifier.hgb_full.calibration_adopted -->-<!-- /num -->). 메모 **문자 CNN** 은 렉시콘 피처가 이미 있는 상태에서 AUROC 를 <!-- num:survival.deep.notext+site.p30.auroc|.3f -->0<!-- /num --> → <!-- num:survival.deep.text+site.p30.auroc|.3f -->0<!-- /num --> 로밖에 올리지 못했고 학습 시간은 수십 배였습니다 — 템플릿으로 만든 합성 메모에서는 렉시콘이 거의 전부를 잡기 때문이고, 실제 현장 메모에서는 다시 재야 합니다. 메모 피처의 기여는 "성실한 점검자는 체크리스트가 넘어가기 전에 메모에 먼저 쓴다"는 가정에서 나옵니다. 실데이터에서 **가장 먼저 확인할 것들**이 [docs/real-data-checklist.md](docs/real-data-checklist.md) 에 있습니다.

## 공고의 요구 기술이 저장소 어디에 있나

| 공고 | 저장소 |
|---|---|
| Python 기반 데이터 전처리 및 분석 (Pandas, NumPy) | `synth/` 생성기(13만 점검 약 40초) · `features/build.py` point-in-time 피처 102개 · 누수 테스트 |
| 머신러닝 기본 (Regression, Classification) | `models/classify.py` HGB + isotonic · `models/energy.py` HGB 회귀 → 잔차 이상 · 로지스틱·연식·마지막점검 베이스라인 |
| 딥러닝 모델 설계 및 성능 개선 (PyTorch / TensorFlow) | `models/deep.py` 이산시간 위험 네트 — 문자 CNN 메모 인코더 + 사이트 임베딩 드롭아웃, 중도절단 NLL · `models/keras_parity.py` 같은 명세의 Keras 구현과 패리티 테스트 |
| 생존·불확실성 | `models/survival.py` Cox PH / Weibull AFT (lifelines) · IPCW Brier · 캘리브레이션(ECE) |
| 분석 결과를 API / 웹 서비스로 (FastAPI) | `api/` 17개 엔드포인트 · 인제스트 → 위험도 즉시 갱신 · 실증 리포트(md) · `console/` 대시보드 |
| 데이터 시각화 | `console/` 바닐라 SVG 차트(라이트/다크, 접근성 팔레트) · `scripts/make_figures.py` 문서 그림 |
| 클라우드 (AWS, GCP) | `Dockerfile`(CPU torch, 비루트) · `deploy/gcp/` Cloud Build + Cloud Run · `deploy/aws/` ECR + App Runner |
| 실제 서비스 운영 | 모델 레지스트리·버전 롤백 · PSI 드리프트 · Prometheus 메트릭 · JSON 로그 · [런북](docs/ops/runbook.md) · CI(린트·테스트·스모크·숫자 검사·이미지 빌드) |
| 실증 프로젝트 및 고객 맞춤형 모델 | 아키타입 4종 25 사이트 · LOSO 콜드스타트 · 사이트 오프셋 · `/report` · [실데이터 4주 체크리스트](docs/real-data-checklist.md) |

## 실행

```bash
# 1) 로컬 (Python 3.11+)
make install            # CPU torch + 개발 의존성
make pipeline           # synth → features → eval → figures → numbers  (약 30분, 4 vCPU)
make serve              # http://localhost:8000/console/  ·  http://localhost:8000/docs

# 2) 컨테이너 — 번들이 없으면 기동 시 축소 합성 번들을 만든다(2~4분)
docker compose up --build
```

```bash
curl -s "localhost:8000/v1/sites/S01/patrol/today?k=8" | jq '.items[] | {rank, name, p30, mandatory, reasons}'
curl -s "localhost:8000/v1/sites/S01/assets/A-S01-0007/risk" | jq '{p30, recommendation, memos: [.explanation.evidence.recent_inspections[].memo_highlighted]}'
curl -s "localhost:8000/v1/sites/S01/report?format=md"
```

## 저장소 구조

```
src/harbinger/
  synth/       생성 모델 — 아키타입·설비·열화·점검자 성향·한국어 메모·고장·에너지
  features/    point-in-time 피처 — 체크리스트·텍스트 렉시콘·점검 품질·이력·에너지 잔차
  models/      HGB 분류·Cox/AFT·PyTorch 위험 네트·에너지 회귀·캘리브레이션·콜드스타트·레지스트리·Keras 패리티
  eval/        시간 분할·베이스라인·절제·IPCW·순찰 시뮬레이션·LOSO
  prescribe/   순찰 우선순위·권고 주기·SHAP+근거 인용
  api/         FastAPI 라우터·스토어·인제스트·리포트     console/  대시보드     monitoring/  드리프트·메트릭
tests/         생성기 결정론·누수·라벨·NLL 폐형해·처방 불변식·API·Keras 패리티
deploy/        Cloud Run · App Runner · Prometheus         docs/  설계·평가·한계·런북·회사 조사
```

## 문서

- [회사 조사 — 왜 이 주제인가](docs/company-research.md)
- [데이터 모델 (역추론 스키마, 실데이터 전환 지점)](docs/data-model.md)
- [합성 데이터 생성 모델 — 전부 공개](docs/synthetic-generator.md)
- [모델링](docs/modeling.md) · [평가](docs/evaluation.md) · [API](docs/api.md)
- [운영 런북](docs/ops/runbook.md) · [한계](docs/limitations.md) · [실데이터 적용 체크리스트](docs/real-data-checklist.md)
- [이 저장소가 만들어진 방식](docs/how-this-was-built.md)

## 범위

실데이터 없음 · 콘솔은 인증 없는 데모 · 단일 프로세스 메모리 적재(사이트 100개 이상이면 저장소 분리) · 유비스 하이(환자이송)는 설계 메모만([한계 §8](docs/limitations.md)).
