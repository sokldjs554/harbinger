# harbinger · 시설 점검 기록 분석

시설 점검 기록으로 **먼저 확인할 설비를 고르고, 점검 원문과 이후 고장 결과로 판단을 검토하는 서비스**입니다. Python으로 이력을 전처리하고 모델을 비교한 뒤, FastAPI와 웹 화면으로 연결했습니다.

[AWS 실제 계산 데모](https://sokldjs554.github.io/harbinger/live.html) · [저장 예제](https://sokldjs554.github.io/harbinger/) · [80초 예제 영상](https://sokldjs554.github.io/harbinger/walkthrough.mp4) · [로컬 실행](#실행) · [평가 방법](docs/evaluation.md)

기본 예제와 아래 성능은 **합성 데이터**에 기반합니다. **AWS 데모에서는 CSV 업로드와 새 계산을 바로 사용할 수 있습니다.** 저장 예제는 미리 계산한 모델 응답을 재생합니다. 실제 고객 성능을 검증한 결과는 아닙니다.

![설비 목록에서 점검 원문과 판단 근거로 이동하는 화면](docs/verification/aws/list.png)

## 주제를 선택한 이유

디더블유아이의 유비스 마스터가 모바일 시설점검과 작업관리를 연결하는 제품이라는 점에서 출발했습니다. 점검할 수 있는 설비 수가 정해져 있다면, 쌓인 기록으로 다음에 확인할 대상을 고르고 그 이유를 검토할 수 있어야 한다고 보았습니다. 회사의 실제 고객 자료를 확보한 프로젝트는 아니며, 공개 제품 맥락을 바탕으로 문제를 정의했습니다. [회사·공고 조사 범위](docs/company-research.md)

예측 시점 이후의 기록을 입력에 섞지 않고, 같은 조건에서 모델과 점검 규칙을 비교했습니다. 화면에서는 설비 목록으로 대상을 고른 뒤 별도 상세에서 점검 날짜별 원문과 판단 항목을 확인하도록 구성했습니다.

## 데모에서 확인할 내용

1. **설비 목록**에서 검색·고객사·종류·정렬 조건으로 대상을 좁힙니다.
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

## 모델 비교와 선택

점검 시점에 알 수 있는 정보로 향후 30일 내 비계획 고장 가능성을 추정합니다. 시간 순서로 학습·보정·테스트를 나누고, 30일의 관측이 끝난 테스트 18,439행에서 비교했습니다.

| 모델 | AUROC ↑ | PR-AUC ↑ | Brier ↓ |
|---|---:|---:|---:|
| HGB 분류 모델 | <!-- num:metrics.classifier.hgb_full.auroc|.4f -->0.7696<!-- /num --> | <!-- num:metrics.classifier.hgb_full.pr_auc|.4f -->0.2445<!-- /num --> | <!-- num:metrics.classifier.hgb_full.brier|.4f -->0.0684<!-- /num --> |
| 로지스틱 회귀 | <!-- num:metrics.baselines.logistic_full.auroc|.4f -->0.7514<!-- /num --> | <!-- num:metrics.baselines.logistic_full.pr_auc|.4f -->0.2134<!-- /num --> | <!-- num:metrics.baselines.logistic_full.brier|.4f -->0.0703<!-- /num --> |
| PyTorch 생존 모델¹ | <!-- num:survival.deep.text+site.p30.auroc|.4f -->0.7643<!-- /num --> | <!-- num:survival.deep.text+site.p30.pr_auc|.4f -->0.2282<!-- /num --> | <!-- num:survival.deep.text+site.p30.brier|.4f -->0.0701<!-- /num --> |

이 실험의 분류 성능을 근거로 HGB를 현재 모델로 사용했습니다. 생존 모델은 고장까지의 시간과 관측 종료를 다루며, 건물 에너지 회귀는 별도로 평가합니다. AUROC·PR-AUC는 높을수록, 확률 오차인 Brier는 낮을수록 좋습니다.

¹ 메모·사이트 임베딩을 포함한 `text+site` 변형입니다. 모든 PyTorch 변형 중 최고 결과라는 뜻은 아닙니다. [모델 설계](docs/modeling.md) · [평가 조건과 변형별 결과](docs/evaluation.md)

## 입력별 기여도와 우선 점검 결과

| 입력 조건 | 시간 보류 AUROC | 시간 보류 PR-AUC |
|---|---:|---:|
| 전체 모델 | <!-- num:ablation.full(+energy).auroc|.4f -->0.7696<!-- /num --> | <!-- num:ablation.full(+energy).pr_auc|.4f -->0.2445<!-- /num --> |
| 메모 및 메모 파생 특징 제거 | <!-- num:ablation.full−text.auroc|.4f -->0.7702<!-- /num --> | <!-- num:ablation.full−text.pr_auc|.4f -->0.2463<!-- /num --> |
| 고장·정비 이력 제거 | <!-- num:ablation.full−history.auroc|.4f -->0.7467<!-- /num --> | <!-- num:ablation.full−history.pr_auc|.4f -->0.2183<!-- /num --> |

이 실험에서는 고장·정비 이력의 기여를 확인했습니다. **전체 모델에서 메모의 추가 예측 성능 이득은 확인하지 못했습니다.** 원문 메모는 사용자가 기록을 검토하는 데 제공합니다.

처음 보는 합성 고객사 8곳의 LOSO 평균 AUROC는 전체 0.7706, 메모 제거 0.7620, 이력 제거 0.7429였습니다. 25곳 전체 LOSO가 아니며 고객별 변화도 일관되지 않습니다. 실제 고객 일반화나 통계적 유의성을 주장하지 않습니다. 자체 정답을 더한 보정도 항상 좋아지지 않았습니다.

25개 합성 사이트의 18개 주간 기준일에서 사이트별 상위 10개를 선택했습니다. **선택한 설비 중 이후 30일 내 고장이 발생한 비율**은 현재 모델 **<!-- num:patrol.methods.harbinger_hgb.precision_at_k|.1% -->24.8%<!-- /num -->**, 로지스틱 **<!-- num:patrol.methods.logistic.precision_at_k|.1% -->20.8%<!-- /num -->**, 최근 점검 판정 규칙 **<!-- num:patrol.methods.last_inspection.precision_at_k|.1% -->12.2%<!-- /num -->**, 무작위 기대치 **<!-- num:patrol.random_expected_precision|.1% -->7.2%<!-- /num -->**입니다. 현재 모델의 고객사 단위 bootstrap 95% 구간은 21.3–28.1%입니다. 현장의 숙련자 판단과 직접 비교한 결과는 아닙니다.

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
- 관측 종료일까지 고장 이력이 완전하다는 사용자 선언이 필요합니다. 실제 기록 누락을 프로그램이 증명할 수는 없습니다.
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

모델 버전 **v20261021-103259**, 원자료 해시와 평가 파일 버전은 `artifacts/release.json`에 기록합니다. 모델·원자료 바이너리는 로컬 생성물이며 공개 정적 데모에는 합성 계산 응답만 넣습니다. AWS 런타임은 입력·모니터링 보완 소스로 같은 전체 합성 조건을 재학습한 `v20261024-152504`이며, 배포 커밋과 별도 평가 파일은 [최신 AWS 검증 기록](docs/verification/aws-20261025/README.md)에 보존했습니다. 선택적 TensorFlow 패리티는 이번 버전에서 재실행하지 않았습니다. 기존 산출물은 `artifacts/archive/fd346c7/`와 Git 이력에 보존합니다.

## 개발 방식

사람이 프로젝트 방향과 수용 기준을 정하고, Codex를 활용해 조사·구현·검증을 진행했습니다. 설비 목록과 상세의 구성, 모바일 사용 흐름과 결과를 검토하며 개정했습니다. [초기 개발 회고](docs/how-this-was-built.md)와 [최신 검증 기록](docs/verification/README.md)을 구분해 남겼습니다.

## 추가 문서

[지원용 소개·시연 순서](docs/submission.md) · [회사·공고 조사 범위](docs/company-research.md) · [모델 설계](docs/modeling.md) · [한계](docs/limitations.md) · [실데이터 적용 체크리스트](docs/real-data-checklist.md) · [친구·동료 검토 절차](docs/user-review.md) · [빈 검토 기록 양식](docs/user-review-template.md)
