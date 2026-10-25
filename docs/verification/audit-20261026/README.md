# 감사 지적 수정과 검증 (2026-10-26)

기준 main은 `0c36ba0c4eb1c53ee4ca3f89db7d10d5e2aaf803`였고 기존 작업 트리는 깨끗했다. 별도 `fix/audit-policy-energy-ops-20261026`에서 수정했으며 이전 합성 평가·AWS 배포·사용자 검토 기록은 수정하지 않았다. [결과 확인 전 고정한 계약](../../superpowers/plans/2026-10-26-audit.md)을 따른다.

## 확인한 원인과 수정

| 항목 | 원인 | 수정과 근거 |
|---|---|---|
| 고객사 선택 | Brier와 반복 행 수만으로 선택; 업무 순위·불확실성 조건 없음 | 공통 기준일의 설비별 상위 10개, 날짜별 최소 설비/기간, 업무 악화 방지, Brier 및 두 군집 재표집 조건. [재현·실제 선택](policy-report.md) |
| 에너지 | 조회 범위를 먼저 잘라 이동평균 변화; NaN 비교가 false; 보고서 기본값 0 | 과거 자료로 먼저 계산하고 표시 범위만 자름. no_data/no_model/insufficient_observation/available, nullable 판정·이상일, 관측/판정 가능일 분리. [재현 실패](energy-red.txt), API/JSON/Markdown/브라우저 회귀 |
| 주 경로 관측 | 순찰에만 지연 경보, 처리 예외 시 지연 미집계 | 분석·업로드·다운로드 성공 지연/실패/429 분리. [규칙 검사](promtool.txt), [실제 수신·복구](local-ops/alert-result.json) |
| 문서 | 에너지 RMSE 표기 불일치, 근거 없는 용량/시간 수치 | 실제 MAE/MAPE/R²로 통일. 런북의 2 vCPU·2 GiB는 구성 예시, 3~6초·150 MB·100사이트 추정을 운영 기준에서 제거 |

## 고객사 선택 결과

실제 합성 번들 `v20261021-115634`, 2023-09-02부터 2023-12-01까지 30일 간격, 미래 테스트 미채점. **5곳 모두 기본 모델 유지**. S01 메모 제외 후보는 평균 적중률 +0.075, Brier 개선 +0.00245767이지만 불확실성 기준 실패. S02는 Brier가 좋아져도 적중률이 악화해 제외. S05는 설비 43개로 표본 조건 실패. 원래 감사 자료의 S01 Brier 개선 0.00147564125도 재계산했지만, 반복 점검 행 기준이므로 새 설비/기준일 결과와 직접 성능 차이로 비교하지 않는다.

50설비·4날짜는 현장 검정력 근거가 없는 보수적인 자격 제한이다. 두 별도 군집 검사는 교차·시간 의존성 아래의 동시 신뢰구간을 보장하지 않는다. 테스트를 보고 하한을 낮추지 않았다. 강한 인공 후보가 실제 선택·활성화·서빙되는 회귀 검사를 별도로 포함한다. 실제 고객 성능은 **잘 모르겠습니다**. 실제 고객 자료나 사람의 재측정 결과는 없다.

## 로컬 부하와 경보

[환경·입력·소스 해시](local-ops/manifest.json), [120건 원시 응답](local-ops/load-raw.json), [요약](local-ops/load-summary.json), [복구](local-ops/load-recovery.json).

- Python 3.12.14, Linux x86_64, 호스트에 보이는 CPU 5개. 실행 환경 cgroup CPU 상한 4코어, 메모리 상한 16 GiB. 이것은 AWS 인스턴스 사양도, 앱의 실제 사용량도 아니다.
- 프로세스 1개, 계산 슬롯 2개, OMP/BLAS 스레드 1. 합성 533설비/10,381피처 행, S01 CSV 517,555바이트. 기준일 2023-11-17, 점검 예산 10.
- 경로별 동시 요청 1 및 4, 각 20건. 동시 1의 성공 p95: 분석 0.114초, 업로드 0.483초, 다운로드 0.102초. 서버·전송 실패 0/120.
- 동시 4에서는 각 경로 2건 성공·18건 429. **90%가 의도적으로 거절됐으며 고부하 처리 용량을 입증하지 않는다.** 성공 2건의 백분위는 작은 표본의 기술 통계일 뿐이다. 재시도 대기열은 구현하지 않았다.
- 100ms 표본 최대 RSS 약 539 MiB, CPU 약 99~110%/단일 코어 기준. 순간 최대를 놓칠 수 있다. CPU/메모리 컨테이너 제한값과 다르다.
- 세션 한도도 별도 포화시켜 업로드 429 확인. 부하 종료 후 분석·업로드·다운로드 모두 200.
- 실제 API의 지표를 Prometheus 2.54.1이 수집했다. 테스트에만 1초 수집·10초 창·2초 지속·지연 1ms 기준을 적용했다. 계산 예외는 별도 로컬 서버 래퍼로 주입했으며 제품 API에는 장애 스위치가 없다.
- `HarbingerWorkbenchSlow`, `HarbingerWorkbenchFailures`의 발화와 해결 알림을 로컬 Alertmanager v2 프로토콜 수신기에서 확인했다. [수신 원문](local-ops/notifications.json). 운영 임계값 발화는 promtool 고정 시계열 검사로 별도 검증했다. 외부 Alertmanager 배포·이메일·실제 사고 대응이나 AWS 부하 시험은 하지 않았다.

## 재현

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 pytest
ruff check src tests scripts
ruff format --check src tests scripts
bash scripts/check_monitoring.sh /tmp/hb-monitoring-bin
# runtime에는 동일한 data/models/artifacts를 준비한다. 입력 해시는 manifest.json 참조.
python -m scripts.check_local_operations --runtime /path/to/runtime \
  --prometheus /tmp/hb-monitoring-bin/prometheus --out /tmp/hb-audit-ops
# 위 명령은 127.0.0.1:18000,19090,19093만 사용한다.
python scripts/check_browser.py --url http://127.0.0.1:18001/console/ --out /tmp/hb-browser
python scripts/check_energy_browser.py --out /tmp/hb-energy-browser
```

모델 선택 CLI·원본 해시는 [policy-report.md](policy-report.md)에 있다. 소스 코드와 원시 결과를 함께 보존한다. 에너지 브라우저 검사는 2023-01-01부터 시작한 실제 축소 합성 API를 사용하며 응답을 모킹하지 않는다.

## 실행 상태와 한계

초기 전체 pytest는 네트워크가 격리된 실행 환경에서 API 테스트가 대기해 중단했다. 로컬 통신 권한을 부여한 실행은 정상 완료했다. 최초 Docker 빌드는 환경 디스크 부족으로 실패했다. 캐시 정리 후 중간 소스의 빌드는 성공했지만, 검토 수정까지 포함한 최종 소스의 초기 재빌드도 같은 저장소 제약으로 실패했다. 참조 없는 중간 이미지와 재생성 가능한 캐시를 정리한 뒤 **최종 소스 재빌드와 실제 컨테이너 실행은 성공**했다. [빌드 원문](docker/build.txt), [분석·업로드·다운로드](docker/api.json), [설치 소스 78파일 일치](docker/image.json)를 보존한다. CI image 작업에서도 독립적으로 다시 검사한다. 원본 소스·데이터·검증 기록은 삭제하지 않았다. 기존 가상환경은 `/tmp/hb-audit-venv`로 이동하고 원래 `.venv` 경로에 심볼릭 링크를 유지했다.

**최종 회귀: 262 통과·1 건너뜀** (`full-tests-final.txt`). 건너뛴 검사는 선택 의존성 TensorFlow의 패리티 검사이며 설치하지 않았다. lint/format, 문서 숫자·모델/산출물 해시 검사 통과. 실제 API 브라우저에서 목록/상세·상태 복원·모바일 320/390/650px·CSV 및 다운로드를 확인했다([검사 기록](browser/workflow-checks.json)). 에너지 상태는 [실제 화면](browser/energy-mobile-insufficient.png)과 [상태별 기록](browser/energy-checks.json)에 남겼다. 독립 검토에서 발견한 당일 에너지 결측 판정과 전체 오래된 기록의 근거 누락은 두 회귀 검사의 실패 후 수정했고 전체 검사를 다시 통과했다. 최종 커밋의 CI test/image 작업 및 Docker 원시 결과는 PR의 Checks/Actions artifacts에서 확인한다. 초기 로컬 Docker 실패와 최종 성공은 아래와 같이 구분한다. 현재 공개 AWS/Pages 배포는 이 브랜치로 갱신하지 않았다. main 병합 시 AWS 배포 workflow가 자동 실행되는 구성이므로 이번 PR은 검토 가능한 상태로 제공한다. 새 유료 리소스는 생성하지 않는다. 테스트 통과가 모든 약점의 해소나 현장 적용 타당성을 의미하지 않는다.

최종 로컬 이미지: `sha256:5ee599fc98b349177431b3c90a40325b42aa32674701d7391b4899d3f0ad40e5`. 컨테이너 제한 2 CPU·2 GiB, UID 10001, 기존 합성 번들을 복사한 뒤 부트스트랩 없이 실행했다. 이 합성 자료 사본 파일에만 읽기 권한(644, 디렉터리 755)을 부여했으며 원본 권한은 바꾸지 않았다. 첫 사본의 제한적인 권한 때문에 기동 실패한 뒤 이 테스트 설정을 바로잡았다. 건강 응답까지 약 7.24초(명령·검사 오버헤드 포함), 부하 전 Docker stats 339.1 MiB는 단일 실행 관측값이며 용량 보장이 아니다. Dockerfile의 WORKDIR를 큰 venv 복사보다 먼저 두어 VFS 환경의 불필요한 복사 층을 줄였다.

최종 컨테이너 자체에서도 [전체 웹 작업](docker/browser-checks.json)과 [에너지 상태별 화면](docker/energy-browser-checks.json)을 다시 조작했다. 사용자 자료·유료 API·외부 메시징은 사용하지 않았다.
