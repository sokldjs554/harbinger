# 디더블유아이 공고와 구현·실행 근거 대조

초기 감사 기준: 2026-10-26(KST), main `27051f07bd7597bd53442c98c281f9240f942e4f`에서 시작한 후속 감사. 공고 내용은 사용자가 이번 대화에 첨부한 화면을 기준으로 대조했다. [사람인 상세 주소](https://www.saramin.co.kr/zf_user/jobs/relay/view-detail?rec_idx=54956037)는 이번 웹 조회 도구에서 열리지 않았다. 현재 접수 상태나 회사 내부 기술 선택은 **확실하지 않음**이다.

사용자는 “실제 역량 검증 중심: FastAPI·AWS 유지, TensorFlow 실행 보완”을 선택했다. 모든 제품명을 추가하는 것을 목표로 삼지 않는다. 아래는 프로젝트가 보여 주는 범위이며 지원자의 학력·근무 경력·독립적인 숙련도를 대신 증명하지 않는다. 코드 작성·수정, 실험 실행과 검증에는 Codex 지원을 사용했다. 사용자에게 확인된 문제·UI 방향과 기술 범위 선택, 검토 의견 전달은 [제출 전 근거 인계](submission-evidence-20261026.md)에 별도로 구분했다.

## 후속 평가 보완 1–4

[기술 결과와 전체 근거](verification/completion-20261026/technical-results.md)를 추가했다. 기존 감사와 과거 실험 기록은 보존하며, 알려진 시드의 메모 재실행·새 검증 시드의 HGB 선택·과거 세계의 실제 순찰 재생을 구분한다.

| 항목 | 이번 확인 | 해석 범위 |
|---|---|---|
| PyTorch 메모 누락 수정 후 반복 | 기존 3세계 × 2학습 시드의 원래 판정 재통과; 선택 정책의 누락 평균 향상 +5.100%p, 정상 입력 변화 +0.139%p | 알려진 세계의 후향적 반복. [평균·여섯 실행·편차·해시](verification/completion-20261026/memo/README.md) |
| HGB 기본 모델 | 새 시드의 검증 조건 미달로 `full` 유지; 테스트 전 선택 동결. 검증 P@10 26.5905% 대 26.2667%, 동결 후 테스트 25.8909% 대 25.5212% | 각각 full 대 메모 제외. 보정과 선택의 검증 기간 재사용을 명시. [모든 지표·실행·편차](verification/completion-20261026/default/summary.json), [선택](verification/completion-20261026/default/selection.json) |
| 실제 순찰 평가 | 같은 공동 선택 코드·필수 대상·중요도·예산 적용. 과거 고정 모델 재생에서 HGB 실제 선택 적중률 20.3111%, 최근 점검 규칙 11.1778% | 확률 순위 Precision@10와 별도 보고. [방법별 결과·멤버십·제약](verification/completion-20261026/patrol/actual/summary.json) |
| 평가 가중 | 고객사 안에서 날짜 평균 → 고객사 평균; paired bootstrap도 같은 추정값 재표집 | 균등/불균등 날짜 대조와 과거 가중 결과 보존. [집계 대조](verification/completion-20261026/technical-results.md#4-지표와-bootstrap의-고객사-가중-일치) |

후속 처리량 검토·전체 검사·TensorFlow·API·브라우저·모바일·Docker CI와 PR #16 병합·AWS/Pages 배포까지 완료했다. [최종 커밋·모델·특징 버전과 원본 산출물](verification/closeout-20261027/README.md)을 2026-10-27 KST에 대조했다. 공개 로그 누락으로 클론 재현이 실패한 문제는 같은 기록의 원본 로그 복구·새 클론 검사로 별도 보완한다. 외부 이메일 수신과 사람의 7과업 재측정은 실제 확인 전까지 완료로 표시하지 않는다.

## 공고 전체 항목

| 구분·요구 | 실제 코드·검증 경로 | 확인 범위와 한계 |
|---|---|---|
| 업무: AI 분석 모델 개발·고도화 | `models/classify.py`, `models/deep.py`, `eval/run.py`, 절제·반복 실험 | 학습·비교·실패 재현을 구현. 수정했다는 사실만으로 성능 향상을 주장하지 않음 |
| 업무: Python 전처리·분석 | `api/upload.py`, `features/build.py`, `features/energy.py`, `features/cache.py` | CSV 계약·Pandas 조인/집계·NumPy 수치 계산·시점별 특징·캐시 해시 |
| 업무: ML/DL 설계·성능 개선 | HGB/로지스틱/Cox/AFT/PyTorch, `scripts/memo_robustness.py` | 합성 자료에서 비교. [수정 후 반복·새 검증 선택](verification/completion-20261026/technical-results.md)을 과거 실험과 구분 |
| 업무: 분석 결과 API·웹 구현 | `api/routers/workbench.py`, `api/analysis.py`, `console/workbench.js` | 실제 업로드→계산→원문/근거→과거 검증→다운로드, 실제 브라우저 검사 |
| 업무: 실증·고객 맞춤 모델 | `models/coldstart.py`, `models/site_policy.py`, `models/policy_evaluation.py` | 합성 고객사 보류·선택/보류·활성화/롤백 구현. **실제 고객 실증은 미수행** |
| 자격: 신입/경력 1년 이상 | 저장소로 확인 불가 | 사용자의 고용 경력은 잘 모르겠습니다. 코드 이력을 근무 경력으로 환산하지 않음 |
| 자격: 학력·졸업예정 | 저장소로 확인 불가 | 학력·졸업 상태는 잘 모르겠습니다 |
| 자격: Python 활용 | `src/harbinger`, CLI·테스트·배포/검증 스크립트 | 실행 가능한 프로젝트 근거. 개인의 단독 구현 능력은 별도 면접/설명으로 확인 필요 |
| 자격: Regression·Classification | `models/energy.py`, `models/classify.py`, `eval/metrics.py` | 연속 에너지 회귀와 30일 고장 분류를 별도 목표·지표로 계산 |
| 자격: Pandas·NumPy | `features`, `models/common.py`, `api/analysis.py` | 시계열·결측·범주 변환·배열 계산에 실제 사용, 의존성 이름만 추가한 것이 아님 |
| 자격: 문제 해결 중심 사고 | 경계 누수·관측 보류·이번 결함의 RED→GREEN 기록 | 원인·수정·재검증 과정의 근거이며 사고 능력을 단정하는 인증은 아님 |
| 우대: TensorFlow·PyTorch | `models/keras_parity.py`, `models/deep.py`, `scripts/keras_parity_check.py` | 두 프레임워크 실제 학습과 동일 가중치 수치 대조. TensorFlow는 선택적 비교 구현이며 공개 서비스 추론 경로는 HGB |
| 우대: FastAPI / Flask | `api/main.py`, 라우터·인증·지표·브라우저 연동 | **FastAPI 실제 사용. Flask 미사용.** 둘 다 필수라는 해석은 확인되지 않았고 사용자는 중복 추가를 선택하지 않음 |
| 우대: 데이터 시각화 | `scripts/make_figures.py`, `console/charts.js`, 검증 화면 | 실제 계산 결과의 그림·표·이력 표시. 지표 이름과 평가 범위를 함께 확인 |
| 우대: 클라우드(AWS, GCP) | `deploy/aws/ec2`, AWS workflow; `deploy/gcp` 설정 | **기존 AWS 배포 확인 기록이 있음. 이번 소스의 배포 확인은 [완료 검증 기록](verification/completion-20261026/README.md)의 실행 링크와 최종 인계를 따른다. GCP는 설정 예시만 있고 실제 배포 경험으로 주장할 수 없음** |
| 우대: 실제 서비스 운영 | 기존 AWS HTTPS·버전·재부팅·인증서 갱신·기능 검사, 로컬 Prometheus | 공개 합성 데모의 운영 검증. 실제 고객 트래픽/SLA·장기 운영·AWS 부하 성능은 미검증 |

## 검증 해석

TensorFlow의 손실·기울기 대조와 두 프레임워크의 독립 학습 결과가 비슷하다는 주장은 다르다. 동일 시드가 동일 초기 가중치를 뜻하지 않는다. 초기 감사의 독립 초기화 실행은 기존 NLL 차이 기준 0.25를 넘었다. 실패 원본과 기준을 보존하고, 별도의 동일 초기 가중치 통제 실험으로 수치 구현을 대조한다. 검증 구간은 조기종료에 사용하므로 독립 테스트라고 부르지 않는다.

기존 README·저장 데모 수치는 그때의 합성 실험이다. 오류 수정 후 재실행 결과로 소급해서 바꾸지 않는다. 원시 결과·검토한 파일 목록·숫자 대조·수정 전후 결과는 해당 감사와 후속 평가 기록에 각각 남긴다. 모든 파일의 존재를 확인하는 것과 각 계산의 타당성을 검토하는 것도 구분한다.

실제 고객 자료·현장 실증·학력/경력은 코드 추가로 채울 수 없는 공백이다. Flask/GCP 미사용을 숨기거나 유료 클라우드를 새로 만들어 채용 요건을 충족했다고 표현하지 않는다.

초기 감사 당시의 수정 전후 수치·TensorFlow 실패와 통제 실험·311개 검사·브라우저 캡처·재현 명령은 [초기 감사 검증 기록](verification/requirements-20261026/README.md)에 있다. 후속 평가 수치는 [평가 보완 1–4](verification/completion-20261026/technical-results.md), 역할과 제출 시 해석 범위는 [근거 인계](submission-evidence-20261026.md)로 이어진다.
