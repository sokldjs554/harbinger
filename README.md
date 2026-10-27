# harbinger · 시설 점검 기록 분석

시설 점검 기록으로 **먼저 확인할 설비를 고르고, 점검 원문과 이후 고장 결과로 판단을 검토하는 서비스**입니다. Python으로 이력을 전처리하고 모델을 비교한 뒤, FastAPI와 웹 화면으로 연결했습니다.

[AWS 실제 계산 데모](https://sokldjs554.github.io/harbinger/live.html) · [저장 예제](https://sokldjs554.github.io/harbinger/) · [80초 예제 영상](https://sokldjs554.github.io/harbinger/walkthrough.mp4) · [로컬 실행](#실행) · [평가 방법](docs/evaluation.md)

기본 예제와 아래 성능은 **합성 데이터**에 기반합니다. **AWS 데모에서는 CSV 업로드와 새 계산을 바로 사용할 수 있습니다.** 저장 예제는 미리 계산한 모델 응답을 재생합니다. 실제 고객 성능을 검증한 결과는 아닙니다.

![설비 목록에서 점검 원문과 판단 근거로 이동하는 화면](docs/verification/aws/list.png)

## 감사 지적 보완

[공고의 업무·자격·우대 항목 전체 대조](docs/job-requirements-audit.md)에서 코드·실행 근거와 확인할 수 없는 조건을 구분했습니다. FastAPI·AWS를 유지하며 TensorFlow 실제 학습·수치 대조를 추가했습니다. 에너지 전처리·사이트 가리기·평가 집단의 결함을 수정하고, 메모 누락 재실행·새 검증 시드의 HGB 선택·실제 순찰 평가·고객사 가중 집계를 보완했습니다. 아래 현재 평가 표의 번들은 **<!-- num:metrics.bundle_version -->v20261026-093937<!-- /num -->**이며 `artifacts/*.json`에서 수치를 채웁니다. 교체 전 단일 실행은 [이전 산출물 보관본](artifacts/archive/pre-completion-5a7f947/)에, 반복 실험은 각 검증 문서에 보존합니다. [평가 보완 1–4의 근거](docs/verification/completion-20261026/technical-results.md)와 [초기 감사의 수정 전후 재실행](docs/verification/requirements-20261026/README.md)을 구분합니다.

고객사 모델 선택은 같은 기준일의 상위 10개 적중률과 Brier를 함께 확인하고, 반복 설비·날짜의 안정성이 부족하면 기본 모델을 유지하도록 수정했습니다. 에너지는 자료 없음·모델 없음·관측 부족을 정상/0일과 구분합니다. 주 분석·업로드·다운로드는 실패와 429를 별도로 관측합니다. [재현·수정·로컬 부하와 경보 검증](docs/verification/audit-20261026/README.md)에 원시 결과와 한계를 남겼습니다. 최신 배포 상태는 [AWS 배포 실행](https://github.com/sokldjs554/harbinger/actions/workflows/aws-ec2.yml)과 [Pages 배포 실행](https://github.com/sokldjs554/harbinger/actions/workflows/pages.yml)에서 확인할 수 있습니다.

## 주제를 선택한 이유

디더블유아이의 유비스 마스터가 모바일 시설점검과 작업관리를 연결하는 제품이라는 점에서 출발했습니다. 점검할 수 있는 설비 수가 정해져 있다면, 쌓인 기록으로 다음에 확인할 대상을 고르고 그 이유를 검토할 수 있어야 한다고 보았습니다. 회사의 실제 고객 자료를 확보한 프로젝트는 아니며, 공개 제품 맥락을 바탕으로 문제를 정의했습니다. [회사·공고 조사 범위](docs/company-research.md)

예측 시점 이후의 기록을 입력에 섞지 않고, 같은 조건에서 모델과 점검 규칙을 비교했습니다. 화면에서는 설비 목록으로 대상을 고른 뒤 별도 상세에서 점검 날짜별 원문과 판단 항목을 확인하도록 구성했습니다.

## 데모에서 확인할 내용

1. **설비 목록**에서 층·구역·설비 검색과 고객사·종류·정렬 조건으로 대상을 좁힙니다.
2. 설비를 선택해 **점검 원문·고장 이력·모델 판단 항목**을 확인합니다. 기여도는 고장의 원인을 증명하는 값이 아닙니다.
3. **과거 검증**에서 같은 날짜·설비·점검 수를 기준으로 모델과 규칙의 선택 결과를 비교합니다. 이후 30일의 관측이 부족한 날짜는 **평가 보류**로 표시합니다.
4. **고객사별 결과**와 보고서 내보내기를 확인합니다. 한 기준일의 고객사별 표와 별도 고객사 보류 실험은 구분해 표시합니다.

| 기능 | 저장 예제 | AWS·로컬 API |
|---|---|---|
| 설비 목록·상세·원문 탐색 | 저장된 합성 예제 | 현재 분석 자료 |
| 과거 검증·모델 비교 | 미리 계산한 날짜와 조건 | 입력 조건으로 새 계산 |
| CSV 업로드 | 실제 계산 데모 안내 | 업로드 검사 후 분석 |
| CSV·JSON·한국어 Markdown 내보내기 | 저장된 결과 | 마지막으로 적용한 계산 결과 |

목록으로 돌아오면 필터·정렬·페이지·스크롤·초점을 복원합니다. CSV 검사나 분석이 실패하면 이전 기록을 유지하며, 내보내기에는 마지막 계산에 실제로 적용한 조건을 기록합니다. [모바일 화면](docs/verification/dense-static/mobile-list.png) · [동작 검증 기록](docs/verification/README.md)

## 사용자 의견을 반영한 개선

시설관리 동료와 비전공자 친구에게서 전달받은 검토 의견을 바탕으로 층·구역 검색, 당시 예측 날짜, 현재 조치 상태 미확인 표시, 조건 변경 안내, 한국어 CSV 오류를 보완했습니다. 기록 완전성을 확인하기 어려운 사용자는 확인란을 선택하지 않고 탐색할 수 있으며, 이후 결과와 성능은 서버에서 평가 보류합니다.

[검토 기록·개선 대응·재검토 절차](docs/user-reviews/README.md)에 근거와 한계를 구분했습니다. 수정 후 추가 문제가 없다는 회신을 사용자에게 전달받았습니다. 응답자별 과업 결과와 재측정 시간은 받지 않았으며, 친구 B의 최초 시간 실측 여부도 미확인입니다. 저장 예제의 위치 검색은 상세 근거가 저장된 설비에 한정됩니다.

## 현재 평가 산출물의 모델 비교와 선택

점검 시점에 알 수 있는 정보로 향후 30일 내 비계획 고장 가능성을 추정합니다. 시간 순서로 학습·보정·테스트를 나누고, 30일의 관측이 끝난 테스트 <!-- num:metrics.classifier.hgb_full.n|,d -->18,439<!-- /num -->행에서 비교했습니다.

| 모델 | AUROC ↑ | PR-AUC ↑ | Brier ↓ |
|---|---:|---:|---:|
| HGB 분류 모델 | <!-- num:metrics.classifier.hgb_full.auroc|.4f -->0.7680<!-- /num --> | <!-- num:metrics.classifier.hgb_full.pr_auc|.4f -->0.2406<!-- /num --> | <!-- num:metrics.classifier.hgb_full.brier|.4f -->0.0686<!-- /num --> |
| 로지스틱 회귀 | <!-- num:metrics.baselines.logistic_full.auroc|.4f -->0.7518<!-- /num --> | <!-- num:metrics.baselines.logistic_full.pr_auc|.4f -->0.2140<!-- /num --> | <!-- num:metrics.baselines.logistic_full.brier|.4f -->0.0702<!-- /num --> |
| PyTorch 생존 모델¹ | <!-- num:survival.deep.text+site.p30.auroc|.4f -->0.7637<!-- /num --> | <!-- num:survival.deep.text+site.p30.pr_auc|.4f -->0.2266<!-- /num --> | <!-- num:survival.deep.text+site.p30.brier|.4f -->0.0702<!-- /num --> |

기본 HGB의 전체 특징 유지 결정은 이 단일 실행 표와 별도로, 새 자료 시드 202610261/262/263 × 학습 시드 17/29의 검증 결과에서 고정했습니다. 메모 제외 후보가 정한 교체 조건에 못 미쳐 전체 모델을 유지했고, 이후 여섯 테스트를 계산했습니다. [선택·동결·평균과 실행별 편차](docs/verification/completion-20261026/technical-results.md#2-hgb-기본-모델의-새-검증-선택)를 확인할 수 있습니다. 생존 모델은 고장까지의 시간과 관측 종료를 다루며, 건물 에너지 회귀는 별도로 평가합니다. AUROC·PR-AUC는 높을수록, 확률 오차인 Brier는 낮을수록 좋습니다.

¹ 메모·사이트 임베딩을 포함한 `text+site` 변형입니다. 모든 PyTorch 변형 중 최고 결과라는 뜻은 아닙니다. 현재 재학습은 epoch마다 한 번 새로 뽑는 30% 고객사 ID 마스크와 특징 정의 v3를 사용합니다. 과거 중복 마스크의 기대 51%는 이전 저장 모델·반복 실험에 해당하며 현재 표의 학습 설정이 아닙니다. [모델 설계](docs/modeling.md) · [평가 조건과 변형별 결과](docs/evaluation.md)

## 입력별 기여도와 우선 점검 결과

| 입력 조건 | 시간 보류 AUROC | 시간 보류 PR-AUC |
|---|---:|---:|
| 전체 모델 | <!-- num:ablation.full(+energy).auroc|.4f -->0.7680<!-- /num --> | <!-- num:ablation.full(+energy).pr_auc|.4f -->0.2406<!-- /num --> |
| 메모 및 메모 파생 특징 제거 | <!-- num:ablation.full−text.auroc|.4f -->0.7732<!-- /num --> | <!-- num:ablation.full−text.pr_auc|.4f -->0.2470<!-- /num --> |
| 고장·정비 이력 제거 | <!-- num:ablation.full−history.auroc|.4f -->0.7460<!-- /num --> | <!-- num:ablation.full−history.pr_auc|.4f -->0.2163<!-- /num --> |

이 표는 현재 단일 합성 실행의 입력 제거 비교입니다. 메모의 예측 이득을 모든 자료에서 같다고 가정하지 않습니다. 별도의 새 합성 세계 검증에서는 전체 HGB가 메모 제외 후보보다 평균 P@10·AUROC·PR-AUC가 높고 Brier가 낮아 전체 특징을 유지했습니다. 반대로 메모 제외가 높았던 과거 조건과 새 테스트의 일부 실행도 보존합니다. 원문 메모는 모델 선택 결과와 별개로 사용자가 기록과 설명을 검토하는 데 제공합니다.

교체 전 저장 예제의 [과거 8개 고객사 LOSO 비교](artifacts/archive/pre-completion-5a7f947/contribution.json)에서 평균 AUROC는 전체 0.7706, 메모 제거 0.7620, 이력 제거 0.7429였습니다. 현재 번들의 LOSO 결과는 [현재 산출물](artifacts/loso.json)에서 따로 확인합니다. 25곳 전체 LOSO가 아니며 고객별 변화도 일관되지 않습니다. 실제 고객 일반화나 통계적 유의성을 주장하지 않습니다. 자체 정답을 더한 보정도 항상 좋아지지 않았습니다.

현재 순수 위험순 평가는 <!-- num:patrol.methods.harbinger_hgb.n_sites|,d -->25<!-- /num -->개 합성 고객사의 <!-- num:patrol.days|,d -->18<!-- /num -->개 주간 기준일에서 고객사별 상위 10개를 선택합니다. 고객사 안의 날짜별 적중률을 평균한 뒤 고객사를 같은 가중으로 평균합니다. **선택한 설비 중 이후 30일 내 고장이 발생한 비율**은 현재 모델 **<!-- num:patrol.methods.harbinger_hgb.precision_at_k|.1% -->23.8%<!-- /num -->**, 로지스틱 **<!-- num:patrol.methods.logistic.precision_at_k|.1% -->21.0%<!-- /num -->**, 최근 점검 판정 규칙 **<!-- num:patrol.methods.last_inspection.precision_at_k|.1% -->12.2%<!-- /num -->**, 무작위 기대치 **<!-- num:patrol.random_expected_precision|.1% -->7.2%<!-- /num -->**입니다. 현재 모델의 고객사 블록 bootstrap 95% 구간과 최근 판정 규칙 대비 paired 차이는 [순찰 산출물](artifacts/patrol.json)의 `site_cluster_ci95`와 `delta_vs_last_inspection_ci95`에 보존합니다. 현장의 숙련자 판단과 직접 비교한 결과는 아닙니다.

주 점검대장의 기본 위험순 목록은 원시 P30 순위입니다. 고급 순찰은 **모든 필수 대상 포함 후 확률 × 중요도 가중(1/1.8/3)**으로 나머지 예산을 채우므로 다른 선택 정책입니다. 같은 후보·날짜·요청 K로 평가한 실제 순찰 선택 적중률은 HGB **<!-- num:patrol.service_policy.methods.harbinger_hgb.selection_hit_rate|.1% -->20.3%<!-- /num -->**, 최근 점검 판정 규칙 **<!-- num:patrol.service_policy.methods.last_inspection.selection_hit_rate|.1% -->11.2%<!-- /num -->**입니다. 필수 수가 K를 넘으면 모두 선택하므로 이 값을 Precision@10라고 부르지 않습니다. 실제 선택 수·필수 수·초과량·구간은 같은 산출물의 `service_policy`에 기록합니다.

생성 시드 3개 × 학습 시드 2개에서 모델 순위와 메모 누락·문자 손상·기록 지연을 별도로 비교했습니다. 반복 설비와 30일 관측 기간 중복을 고려한 보정 선택도 다시 검증했습니다. 평균뿐 아니라 실행별 범위와 악화한 조건을 [평가 안정성 결과](docs/verification/robustness-20261025/README.md)에 남겼습니다. 실제 사용자 검토나 고객 실증 결과와는 구분합니다. 전체 HGB와 메모 제외 HGB의 순위가 조건에 따라 달랐으므로, [고객별 모델 선택 기준](docs/model-selection.md)은 기록 품질과 동일 점검 예산의 시간 분리 검증을 중심으로 정리했습니다. 후속 보완에서는 검증 자료로 고객사별 후보를 선택하고, 정책을 활성화·롤백하는 절차를 구현했습니다. 실제 고객별 최적 모델을 입증한 결과는 아닙니다.

과거 PyTorch 메모 누락 대응도 합성 세계 3개 × 학습 시드 2개에서 비교했습니다. 이 기록은 사이트 가리기 중복 수정 전 구현의 결과이며 수정 후 재검증으로 소급하지 않습니다. 메모 25% 누락 시 상위 10개 적중률은 기존 17.64%, 누락 대응 개선형 22.90%, 메모 미사용 모델 23.73%였습니다. 검증 기준은 메모 미사용 모델 5회·기존 모델 유지 1회를 선택했고, 고정한 선택의 최종 테스트 채택 기준을 통과했습니다. 개선형의 정상 입력 성능 하락과 확률 오차도 [전체 결과·방법·복구 기록](docs/verification/memo-20261025/README.md)에 함께 남겼습니다. 공개 서비스 HGB의 교체나 실제 고객 실증을 뜻하지 않습니다.

수정 후에는 같은 알려진 세계를 다시 실행했습니다. 선택 정책의 25/50% 누락 평균 향상은 같은 실행의 legacy 대비 +5.100%p, 정상 입력 변화는 +0.139%p였고 원래 판정을 재통과했습니다. [수정 후 메모 결과·모든 실행·편차](docs/verification/completion-20261026/memo/README.md)는 후향적 재실행이며 새로운 독립 성능 입증이 아닙니다. 새 HGB 검증 선택과도 별도 실험입니다.

## 계산 결과를 운영과 재검토로 연결했습니다

- 신호 근거표는 고객사 단위 bootstrap으로 반복 설비·점검자 기록을 함께 재표집합니다. 자료가 부족하면 구간을 보류합니다.
- 선택형 [보호 모드](docs/protected-mode.md)는 로그인, 고객사별 접근 권한, 업로드 소유권과 세션 취소를 검사합니다. 공개 합성 데모는 익명 모드를 유지합니다.
- [고객사 모델 정책](docs/site-model-policy.md)은 선택 근거와 버전을 남기고 활성화·롤백하며, 화면과 다운로드에 실제 사용 모델을 기록합니다.
- [재검토 기록 도구](https://sokldjs554.github.io/harbinger/retest.html)는 도움·미실시·대기 시간을 구분해 JSON으로 저장합니다. 실제 재측정 결과는 아직 수집하지 않았습니다.

군집 누락·선택적 누락·한국어 치환·축약·기록 지연의 추가 실험과 경보 규칙 검사도 [보완 검증 기록](docs/verification/remaining-gaps-20261025/README.md)에 연결했습니다. 기존 합성 세계의 추가 스트레스 검사이며 새로운 현장 성능 검증은 아닙니다.

기존 AWS의 네이버 SSL 장애·복구 메일은 운영자가 실제 수신을 확인했습니다. 이후 발견한 재설치 설정 삭제 결함도 수정하고, 정상 설정으로 모니터링 컨테이너 재생성과 활성 파일 보존을 확인했습니다. [PR #20·실제 운영 원본·수신 확인 범위](docs/verification/closeout-20261027/README.md#8-pr-20-병합알림-설정-지속성-검증-완료)를 구분해 기록했습니다.

## 평가 오류 수정과 재측정

점검 시각만으로 구간을 나누면 학습 말미의 점검이 **다음 구간에 발생한 고장을 정답으로 사용**했습니다. 학습·보정 cutoff에서 분류 정답의 30일 성숙 여부와 생존의 관측 시간을 함께 제한했습니다. 미래 자료가 바뀌어도 과거 입력·정답·학습 결과가 바뀌지 않는 회귀 테스트를 추가했습니다. 에너지 전처리의 미래 자료 fallback, 고객사 자체 정답 보정, 조기종료, 모델 관측 메타 없는 과거 재현도 점검했습니다.

수정 전 코드 `fd346c7`과 수정 후 코드를 동일 원자료·패키지·시드로 다시 실행했습니다. 수정 전 공개 수치를 재사용하지 않고, **30일의 관측이 끝난 동일한 테스트 18,439행**으로 비교했습니다.

| 지표 | 수정 전 재실행 | 수정 후 |
|---|---:|---:|
| AUROC ↑ | <!-- num:before_after.before.auroc|.4f -->0.7736<!-- /num --> | <!-- num:before_after.after.auroc|.4f -->0.7696<!-- /num --> |
| PR-AUC ↑ | <!-- num:before_after.before.pr_auc|.4f -->0.2520<!-- /num --> | <!-- num:before_after.after.pr_auc|.4f -->0.2445<!-- /num --> |
| Brier ↓ | <!-- num:before_after.before.brier|.4f -->0.0680<!-- /num --> | <!-- num:before_after.after.brier|.4f -->0.0684<!-- /num --> |
| ECE ↓ | <!-- num:before_after.before.ece|.4f -->0.0061<!-- /num --> | <!-- num:before_after.after.ece|.4f -->0.0092<!-- /num --> |

성능은 낮아졌습니다. 학습 3,575행·보정 3,568행의 미성숙 분류 정답을 제외했습니다. 생존은 해당 경계에서 중도절단합니다. 관측이 부족한 360일 Brier는 보류합니다. 경계·전처리·관측 종료 수정이 함께 적용됐으므로 변화 전체를 한 수정의 인과 효과라고 해석하지 않습니다.

## 실행

설치 없이 **CSV 업로드와 새 계산**을 사용하려면 [AWS 데모](https://sokldjs554.github.io/harbinger/live.html)를 엽니다. 직접 실행하려면 아래 명령으로 로컬 서버를 시작합니다.

준비: Git 설치, Docker 실행

```bash
git clone https://github.com/sokldjs554/harbinger.git
cd harbinger
docker compose up --build api
```

브라우저에서 **http://localhost:8000/console/**을 엽니다. 첫 실행에는 이미지 빌드와 축소 합성 모델 학습이 포함되어 수 분 이상 걸릴 수 있습니다. 종료는 실행한 터미널에서 `Ctrl+C`를 누르면 됩니다.

이 명령만으로 로컬 서비스를 사용할 수 있습니다. README의 전체 실험 수치는 별도 학습 결과이므로 기본 실행 결과와 다릅니다. [Python 직접 실행·전체 실험 재현·개발자 검사](docs/running.md)
## 입력 형식과 처리 기준

UTF-8/BOM CSV, 최대 **5 MiB / 20,000행 / 설비 500개 / 고객사 10개 / 관측 5년**. 한 행은 점검 또는 고장·예방정비·부품 교체 기록입니다. 필수 열, 열거값, 날짜, 중복 ID, 설비 정보 불일치, 미지원 열을 검사하고 이유와 행 번호를 반환합니다. 자동으로 결측 정답을 음성으로 채우지 않습니다.

- [전체 열 명세와 예제](docs/upload-format.md)
- `GET /v1/workbench/example.csv`: 지원 형식 예제 다운로드
- `POST /v1/workbench/upload?observation_end=YYYY-MM-DD`: `Content-Type: text/csv`, 원문 CSV body
- 업로드는 메모리에서 최대 30분, 최대 8세션·동시 계산 2개로 제한합니다. 종료/만료 시 제거하며 원문을 파일이나 로그에 저장하지 않습니다.
- 시설 데이터 담당자가 기록 완전성을 확인했을 때만 선택 항목을 체크합니다. 미확인 상태에서도 예측·원문 탐색은 가능하지만 이후 고장 여부·성능 평가는 보류합니다. 실제 누락 여부를 프로그램이 증명하지는 않습니다.
- 업로드에서는 에너지 자료를 받지 않습니다. 에너지 특징은 결측으로 처리하며 합성 학습 모델을 탐색적으로 적용합니다.

## 구성과 검증 자료

| 구성 요소 | 코드·근거 |
|---|---|
| 데이터 처리와 품질 계약 | `src/harbinger/api/upload.py`, `src/harbinger/features/build.py`, [입력 명세](docs/upload-format.md) |
| 시간 경계·생존·보정·회귀 방지 | `src/harbinger/models/common.py`, `src/harbinger/eval/run.py`, `tests/test_observation_boundary.py` |
| 모델 개발과 기여도 실험 | HGB/로지스틱/Cox/AFT/PyTorch, [평가 계약](docs/evaluation.md), `artifacts/contribution.json` |
| 고객별 검증 | `artifacts/loso.json`: 선정·미선정·보류 조건과 자체 정답 기간별 결과 |
| API·웹·설명·다운로드 | `src/harbinger/api/routers/workbench.py`, `src/harbinger/api/analysis.py`, `src/harbinger/console/workbench.js` |
| AWS 배포·운영 검증 | [HTTPS·CSV·재부팅·갱신 시험 기록](docs/verification/aws/README.md), [중지·비용·운영 안내](deploy/aws/README.md) |
| 재현·실행 검증 | [검증 기록 및 미완료 항목](docs/verification/README.md), `Dockerfile`, `.github/workflows/ci.yml` |

검증 명령과 브라우저 검사 방법은 [개발자 검사 안내](docs/running.md#개발자-검사)를 참고하세요.

현재 평가 산출물의 모델 버전은 **<!-- num:metrics.bundle_version -->v20261026-093937<!-- /num -->**입니다. 원자료 해시·평가 파일 버전은 `artifacts/release.json`과 실행 기록을 함께 확인합니다. PR #16은 `e33072b`로 병합됐고 main CI·AWS·Pages 배포가 성공했습니다. AWS 실제 계산 모델은 `v20261026-151241`, Pages 저장 모델은 `v20261026-093937`, 특징 정의는 3·116개입니다. [최종 배포 원본·실행 링크·공개 증거 복구](docs/verification/closeout-20261027/README.md)를 확인하세요. 모델·원자료 바이너리는 로컬 생성물이며 공개 정적 데모에는 합성 계산 응답만 넣습니다. 입력·모니터링 보완 당시 AWS 런타임은 같은 전체 합성 조건을 재학습한 `v20261024-152504`이며, [당시 배포·평가 기록](docs/verification/aws-20261025/README.md)에 보존했습니다. 사용자 검토 의견을 반영한 과거 소스 `4965901`의 당시 배포·런타임 모델 정보는 [AWS 배포 실행·산출물](https://github.com/sokldjs554/harbinger/actions/runs/40189712992)에서 확인할 수 있습니다. TensorFlow 실제 실행·경계/손실 검증과 통제 학습 결과는 [공고 요구 기술 감사](docs/job-requirements-audit.md)에 별도로 기록했습니다. 기존 독립 초기화 차이 기준 실패는 숨기지 않았습니다. 이전 단일 실행은 `artifacts/archive/pre-completion-5a7f947/`, 더 이전 산출물은 `artifacts/archive/fd346c7/`와 Git 이력에 보존합니다. 위 `before_after` 표는 당시의 고정 비교이며 현재 번들 교체로 다시 계산하지 않습니다.

## 개발 방식

사람이 프로젝트 방향과 수용 기준을 정하고, Codex를 활용해 조사·구현·검증을 진행했습니다. 설비 목록과 상세의 구성, 모바일 사용 흐름과 결과를 검토하며 개정했습니다. [초기 개발 회고](docs/how-this-was-built.md)와 [최신 검증 기록](docs/verification/README.md)을 구분해 남겼습니다.

## 추가 문서

[지원용 소개·시연 순서](docs/submission.md) · [회사·공고 조사 범위](docs/company-research.md) · [모델 설계](docs/modeling.md) · [한계](docs/limitations.md) · [실데이터 적용 체크리스트](docs/real-data-checklist.md) · [친구·동료 검토 절차](docs/user-review.md) · [빈 검토 기록 양식](docs/user-review-template.md)

공개 증거 복구와 운영자 이메일 경로는 [후속 검증 기록](docs/verification/closeout-20261027/README.md)에 정리했습니다. PR #17·#18을 병합하고, 기존 EC2에서 네이버 SSL 465 장애·복구 전송과 정상 복구를 확인했습니다. 운영자의 두 이메일 실제 수신 회신도 별도로 기록했으며, 참가자별 7과업 사용성 재측정은 아직 미수신입니다. 서비스 모델·Pages 저장 결과는 위 배포 버전을 유지합니다.
