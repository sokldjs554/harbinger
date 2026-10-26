# 로컬 처리량·제한 대기·경보 검증

엄격 재시험의 저장소 원본과 비교 파일을 재계산해 전후 모두 통과를 확인했다. 초기 시험 기록도 아래에 보존한다.

2026-10-26. 계산 슬롯 **2개를 유지**하고 즉시 거절을 **최대 4개 대기·입장 대기 10초 제한**으로 바꿨다. 같은 로컬 합성 입력의 동시 요청 4·각 20회에서 분석·업로드·다운로드 모두 수정 전 **성공 2/20, 429 18/20**에서 수정 후 **성공 20/20, 429 0/20**으로 바뀌었다. 정상 부하 구간의 5xx·전송 실패는 양쪽 모두 0건이었다.

대기는 요청을 더 오래 받아 두어 완료시키는 정책이다. 계산 슬롯이나 계산 용량을 늘렸다는 뜻이 아니다. 수정 전 p95는 성공 **2건**, 수정 후 p95는 성공 **20건**으로 계산하므로 지연 수치만 같은 표본 조건의 성능 비교처럼 읽지 않는다. 15초 의도적 점유에서는 수정 후에도 초과 대기·대기 만료를 429로 거절하고 정상 요청으로 복구했다.

## 같은 조건인지 확인한 범위

[독립 재계산](verify_comparison.py)은 [비교 JSON](comparison.json)의 모든 정상 부하 상태 수·성공 지연 분위수·429 비율을 원시 요청에서 다시 계산한다. 모델/데이터 `runtime_sha256`, CSV 해시·바이트·행·설비·고객사 수, 두 측정 스크립트 SHA256, 기록된 환경·스레드·worker·요청 조건을 전후 일치로 검사했다. CPU 초·wall time·끝점을 포함한 RSS 최대는 원래 측정 요약의 직접 기록을 사용하며, CPU 비율을 재계산하고 100ms 간격 내부 표본과 대조한다. 생략된 시작/끝 `/proc` 원시 카운터를 독립적으로 복원했다고 주장하지 않는다.

| 항목 | 전후 공통 조건 |
|---|---|
| 고정 모델 / 특징 | `v20261026-093937` / 특징 정의 v3, 전체 HGB 116열 |
| API 프로세스 | worker 1, 계산 슬롯 2, OMP/OpenBLAS 각 1스레드 |
| 요청 수 | 분석·업로드·다운로드 × 동시 1/4 × 각 20회 = 한쪽당 120회 |
| 분석 조건 | S01, 2025-11-17, 요청 K=10; 다운로드 JSON |
| 업로드 CSV | 7,352행, 104설비, 1고객사, 1,546,864바이트 |
| 메모리에 적재한 전체 예제 | 25고객사, 2,312설비, 131,201점검 |
| CPU | 호스트 표시 5개; cgroup `400000/100000` = 4 CPU 할당 |
| 메모리 한도 | cgroup 17,179,869,184바이트 = 16 GiB |
| 실행 환경 | 동일 Linux·AMD EPYC 9V74·Python 3.12.14, 동일 Python 실행 경로 |

CSV와 상주 예제 규모를 혼동하지 않는다. 전체 상주 모델/자료를 둔 프로세스에서 S01 입력을 측정한 결과다. RSS는 API 프로세스의 표본 최대이며 서버 전체나 Prometheus·클라이언트까지 합친 값이 아니다. CPU 100%는 **한 코어 상당**으로 계산한다. 약 한 코어의 사용이 관측됐으며 cgroup의 네 코어 전체 포화나 AWS 인스턴스 성능을 뜻하지 않는다.

## 엄격 재시험의 정상 부하 결과

각 셀을 순서대로 한 번 측정했다. 예열은 별도이며 아래 p95는 HTTP 200 요청만 대상으로 한다. 업로드 요청별 지연은 성공 세션 정리 DELETE 이전까지, 셀 wall time·CPU·요청/초는 정리 및 실행기 오버헤드를 포함한다. 순서는 동시 1의 분석→업로드→다운로드 후 동시 4의 같은 순서다.

| 경로 | 동시 | 전 성공/429 | 후 성공/429 | 전 성공 p95(초) | 후 성공 p95(초) | 전 성공 요청/초 | 후 성공 요청/초 |
|---|---:|---:|---:|---:|---:|---:|---:|
| analysis | 1 | 20/0 | 20/0 | 0.113 | 0.157 | 9.127 | 7.238 |
| upload | 1 | 20/0 | 20/0 | 1.053 | 0.957 | 1.228 | 1.285 |
| download | 1 | 20/0 | 20/0 | 0.145 | 0.123 | 7.608 | 8.568 |
| analysis | 4 | 2/18 | 20/0 | 0.348 | 0.629 | 5.695 | 7.090 |
| upload | 4 | 2/18 | 20/0 | 2.241 | 4.463 | 0.890 | 0.968 |
| download | 4 | 2/18 | 20/0 | 0.291 | 0.787 | 6.792 | 6.186 |

| 경로 | 동시 | 전/후 CPU 초 | 전/후 CPU % (1코어=100) | 전/후 표본 최대 RSS(MiB) | 전/후 전체 응답 요청/초 |
|---|---:|---:|---:|---:|---:|
| analysis | 1 | 2.18 / 2.74 | 99.5 / 99.2 | 850.2 / 850.1 | 9.127 / 7.238 |
| upload | 1 | 16.27 / 15.55 | 99.9 / 99.9 | 882.8 / 881.5 | 1.228 / 1.285 |
| download | 1 | 2.61 / 2.31 | 99.3 / 99.0 | 880.9 / 878.7 | 7.608 / 8.568 |
| analysis | 4 | 0.38 / 3.08 | 108.2 / 109.2 | 886.3 / 895.7 | 56.952 / 7.090 |
| upload | 4 | 2.37 / 21.72 | 105.5 / 105.1 | 970.6 / 1001.6 | 8.899 / 0.968 |
| download | 4 | 0.32 / 3.52 | 108.7 / 108.9 | 970.6 / 1001.6 | 67.915 / 6.186 |

전체 응답 요청/초에는 즉시 거절한 429도 포함된다. 수정 전의 높은 전체 응답률을 성공 처리 용량으로 부르지 않는다. 동시 4에서 수정 전 90% 거절은 계산 2개가 찼을 때의 즉시 거절 정책과 일치하며, CPU나 메모리 한계에서 20건 처리를 시도하다 실패한 측정이 아니다. 수정 후 대기는 성공 수를 늘리는 대신 일부 요청의 대기 지연과 메모리 체류를 늘린다. 단일 연속 측정의 차이를 안정된 속도 향상·SLA·최대 고객 수로 일반화하지 않는다.

원시 [수정 전 요청](strict/before/load-raw.json)·[수정 후 요청](strict/after/load-raw.json), 각 `load-summary.json`과 `resources-*.json`에 기록이 있다. RSS 표본은 짧은 순간의 실제 최대를 놓칠 수 있다. CPU 끝점 차이와 wall time은 직접 요약값이며 내부 표본만으로 전체 카운터를 재구성할 수 없다. `comparison.json`의 `endpoint_peak_above_interior_bytes`는 끝점 포함 최대와 내부 표본 최대의 차이를 그대로 남긴다.

## 대기 한도·세션 한도·회복

실제 계산에 **15초 지연을 의도적으로 주입**하고 12개 클라이언트 worker로 20개 분석 요청을 보냈다. 정상 처리량 측정과 분리한 시험이다. 양쪽 모두 성공 2건·429 18건이었다. 수정 후 거절은 `queue_full` 14건, `wait_timeout` 4건으로 구분되며 `Retry-After: 1`을 받았다. 대기 만료는 약 10초에 반환됐다. 10초는 입장 대기 한도이고 이미 실행 중인 15초 요청을 중단하는 실행 시간 제한이 아니다.

[수정 전 강제 점유](strict/before/admission-overload.json)·[수정 후 강제 점유](strict/after/admission-overload.json) 뒤 분석·업로드·다운로드 세 경로가 모두 200으로 회복했다. 정상 부하 뒤에도 세 경로와 health를 확인했다([전](strict/before/load-recovery.json), [후](strict/after/load-recovery.json)).

별도의 [세션 포화 시험](strict/after/capacity.json)은 보관 세션 8개 한도에 따른 429다. 계산 대기열 포화·대기 만료와 다른 제한이며 `capacity_reason`은 없다. 정상 부하에서는 성공 업로드 세션을 정리해 세션 포화가 계산 정책 비교에 섞이지 않도록 했다.

## 초기 경보 검증의 누락과 엄격 재시험

초기 [before](before/)·[after](after/) 원본은 그대로 보존했다. 최초 측정기는 Slow/Failures가 **과거에 한 번 resolved를 보냈는지**만 확인했다. 초기 before에서는 Slow가 resolved 후 다시 firing했고 마지막 `recovered-rules.json`도 firing이었다. 따라서 당시 종료 코드 0과 `resolved` 목록만으로 최종 정상화를 주장할 수 없다. 초기 after의 마지막 상태는 inactive였다.

[회귀 검사](../../../../tests/test_ops_recovery.py)는 과거 resolved 뒤 재발, 현재 pending, 상태/수신 기록 누락을 거절한다. 수정한 측정기는 **현재 Prometheus 규칙 inactive AND 해당 경보의 최신 수신 상태 resolved**를 동시에 요구한다. 동일한 수정 스크립트를 baseline과 after에 복사해 전체 전후를 재실행했으며 작업량·대기 정책·경보 문턱을 결과에 맞춰 바꾸지 않았다.

엄격 재시험에서는 양쪽 모두 실제 Prometheus가 `HarbingerWorkbenchSlow`와 `HarbingerWorkbenchFailures`를 firing했고 로컬 Alertmanager v2 프로토콜 수신기가 알림을 받았다. 종료 시 두 규칙은 inactive이고 최신 수신은 resolved였다([전 상태](strict/before/recovered-rules.json)·[전 수신](strict/before/notifications.json), [후 상태](strict/after/recovered-rules.json)·[후 수신](strict/after/notifications.json)). 실패 경보를 위해 의도적으로 주입한 500은 `alert-requests.json`에 따로 남기며 정상 부하의 서버 실패 0건과 혼합하지 않는다.

경보 시험은 scrape/eval 1초, 관측창 10초, `for` 2초, 성공 p95>1ms·성공 1건 이상인 시험용 문턱을 사용했다. 운영 규칙을 수정한 것이 아니며 실서비스 지연 경보의 유효성을 보증하는 시험도 아니다. 경보 설명 문구의 운영 2초와 시험용 실제 표현식 1ms를 구분한다. 외부 Slack/이메일 등의 전송은 수행하지 않았고 임시 TSDB는 증거 복사에서 제외했다.

## 실행 소스의 차이와 해석

baseline은 `def9c94260c1df70acc218d95b7af743ad3cc28d`의 분리 checkout이다. after는 당시 작업 트리다. `/version.git_sha`가 양쪽 모두 `def9c94`인 것은 고정 모델 번들의 기록이며 실행 소스가 같다는 뜻이 아니다. [전 manifest](strict/before/manifest.json)·[후 manifest](strict/after/manifest.json)의 실제 파일 해시를 비교했다.

| 변경 소스 | 변경 범위 |
|---|---|
| `src/harbinger/api/compute.py` | 제한된 FIFO 대기·입장 만료·429 사유/재시도 헤더 |
| `src/harbinger/api/routers/workbench.py` | 즉시 semaphore 대신 동일 2슬롯의 gate 사용·정책 메타데이터 |
| `src/harbinger/api/store.py` | 고급 순찰 결과의 실제/필수/초과 수와 같은 필수 조건 비교군 |
| `src/harbinger/api/routers/report.py` | 고급 순찰 Markdown의 제약·선택 수 표기 |
| `src/harbinger/eval/run.py` | 오프라인 순찰 멤버십 증거 압축 보관과 요약 분리 |

분석 계산·CSV 파싱·특징 생성/갱신·분류 모델·지표 수집 파일의 해시는 동일하다. 검토한 diff에서 `Store` 변경은 이 측정이 호출하지 않는 고급 순찰 메서드이며, JSON workbench 다운로드는 동일한 분석 함수를 호출한다. 이 세 측정 경로의 연산 부분은 같고 admission gate가 달라진 것으로 해석할 근거가 있다. 다만 전체 작업 트리에는 위 다른 변경도 있고 전후 각 한 번의 연속 실행이므로 완전한 단일 변수 인과 실험이나 독립적인 계산 속도 향상으로 표현하지 않는다.

## 재검증과 재현

저장된 자료의 독립 대조는 서버·네트워크 없이 실행한다. 작업 디렉터리에 의존하지 않는다.

```bash
python docs/verification/completion-20261026/operations/verify_comparison.py
# 초기 자료는 최종 경보 정상화 미완료로 종료 코드 1이 예상된다.
python docs/verification/completion-20261026/operations/verify_comparison.py --root docs/verification/completion-20261026/operations
```

실제 실행 명령·cwd·소요 시간은 [전 execution](strict/before/execution.json)과 [후 execution](strict/after/execution.json)에 보존했다. 아래는 같은 자료·모델을 보존한 로컬 환경에서 **새 출력 경로**로 재현하는 절차다. after 소스는 manifest의 파일 해시와 일치하는 버전을 사용하고, 측정 코드 두 개도 manifest의 SHA256과 대조한다.

```bash
OPS_REPO=/path/to/harbinger
OPS_RUNTIME=/path/to/frozen-v20261026-093937-runtime
OPS_PYTHON=/path/to/venv/bin/python
OPS_PROM=/path/to/prometheus
OPS_BASE=/tmp/harbinger-operations-baseline
OPS_OUT=/tmp/harbinger-operations-reproduction
git -C "$OPS_REPO" worktree add --detach "$OPS_BASE" def9c94260c1df70acc218d95b7af743ad3cc28d
cp "$OPS_REPO/scripts/check_local_operations.py" "$OPS_BASE/scripts/check_local_operations.py"
cp "$OPS_REPO/scripts/audit_fault_server.py" "$OPS_BASE/scripts/audit_fault_server.py"
sha256sum "$OPS_REPO/scripts/check_local_operations.py" "$OPS_BASE/scripts/check_local_operations.py"
sha256sum "$OPS_REPO/scripts/audit_fault_server.py" "$OPS_BASE/scripts/audit_fault_server.py"
cd "$OPS_BASE"
PYTHONPATH="$OPS_BASE/src" "$OPS_PYTHON" -m scripts.check_local_operations --runtime "$OPS_RUNTIME" --prometheus "$OPS_PROM" --out "$OPS_OUT/before"
cd "$OPS_REPO"
PYTHONPATH="$OPS_REPO/src" "$OPS_PYTHON" -m scripts.check_local_operations --runtime "$OPS_RUNTIME" --prometheus "$OPS_PROM" --out "$OPS_OUT/after"
```

엄격 재시험의 `check_local_operations.py` SHA256은 `8894cb325d43d96a883400fde4c6ec86963f540e6464e54be44227b453c686cb`, `audit_fault_server.py`는 `50359fda695c4b1673585f11425d6ad0094cf3cd8d5f95791228ecfe187b7a8f`다. 서버는 loopback 18000, Prometheus 19090, 로컬 수신기 19093에만 바인딩했다. 공개 AWS 부하, 새 유료 자원, 외부 알림은 사용하지 않았다. 이 기록으로 CI·병합·공개 배포 완료를 주장하지 않는다.
