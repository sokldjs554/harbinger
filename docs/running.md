# 실행과 실험 재현 안내

기본 실행은 [README의 Docker 명령](../README.md#실행)을 사용합니다. 이 문서는 Python으로 직접 실행하거나, 전체 실험과 검증을 다시 수행할 때 참고합니다.

| 목적 | 필요한 절차 |
|---|---|
| 화면과 저장된 예제 확인 | [공개 데모](https://sokldjs554.github.io/harbinger/) 접속 |
| 설치 없이 CSV 업로드와 새 계산 | [AWS 데모](https://sokldjs554.github.io/harbinger/live.html) 접속 |
| 로컬에서 CSV 업로드와 새 계산 | README의 Docker 실행 |
| Docker 없이 Python으로 실행 | 아래 Python 직접 실행 |
| 전체 실험의 모델·평가 재현 | Python 설치 후 전체 실험 재현 |
| 코드 변경 후 검사 | 개발자 검사 |

## Python 직접 실행

Python 3.12 / Linux CPU를 기준으로 의존성을 고정했습니다. 최초 설치에는 패키지 다운로드가 필요합니다. Docker로 실행했다면 이 절차를 추가로 수행할 필요는 없습니다.

```bash
git clone https://github.com/sokldjs554/harbinger.git
cd harbinger
python3.12 -m venv .venv
source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
pip install -c constraints.txt -e '.[dev]'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
harbinger bootstrap --data data --models models --artifacts artifacts
harbinger serve --port 8000
```

`http://localhost:8000/console/`을 엽니다. OpenAPI 문서는 `http://localhost:8000/docs`, 상태 확인은 `http://localhost:8000/health`입니다.

`bootstrap`은 데이터·모델이 없을 때 축소 합성 예제를 생성하고 학습합니다. 기본 실행은 README에 기재한 전체 실험과 수치·모델 버전이 다릅니다. 첫 학습은 수 분 이상 걸릴 수 있으며 새 모델 버전을 생성합니다.

## 전체 실험 재현

이 절차는 로컬 서비스를 사용하는 데 필수는 아닙니다. README의 25개 사이트·36개월·시드 20260101 조건으로 전체 모델과 평가 결과를 다시 생성할 때만 수행합니다. Python 직접 실행의 설치를 마친 뒤 저장소 루트에서 실행합니다.

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
harbinger synth --out data --seed 20260101 --scale 1 --months 36
harbinger features --data data
harbinger eval --data data --models models --artifacts artifacts --seed 20260101
```

기존 전체 평가는 검증 환경에서 약 26분 걸렸습니다. CPU·패키지·스레드 설정에 따라 달라집니다. 합성 데이터와 모델 바이너리는 Git에 포함하지 않으며, 다중 시드·확장 스트레스 실험은 [별도 검증 기록](verification/remaining-gaps-20261025/README.md)을 참고하세요.

문서 수치와 저장형 데모까지 갱신할 경우에만 다음 명령을 이어서 실행합니다.

```bash
python scripts/make_replay_summary.py
python scripts/fill_numbers.py
python scripts/build_workbench_demo.py
```

평가 기준과 결과 해석은 [평가 문서](evaluation.md)를 참고하세요.

## 개발자 검사

코드 변경 후 사용하는 검사입니다. 로컬 서비스 실행만을 위해 수행할 필요는 없습니다. Python 직접 실행에서 개발 의존성까지 설치한 환경을 기준으로 합니다.

```bash
ruff check src tests scripts
ruff format --check src tests scripts
pytest -q
python scripts/fill_numbers.py --check
```

브라우저 조작 검사에는 Playwright와 Chromium을 추가로 설치하고, 로컬 API 서버를 실행해 둡니다.

```bash
pip install 'playwright==1.56.0'
playwright install chromium
python scripts/check_browser.py --url http://localhost:8000/console/
```

사용 영상이 필요할 때는 다음 명령으로 녹화합니다.

```bash
python scripts/record_workbench.py --url http://localhost:8000/console/
```

현재 실행·브라우저·컨테이너 검증 근거는 [검증 기록](verification/README.md)에 있습니다.

## Docker 실행 범위

컨테이너는 비루트 UID 10001로 실행하도록 구성했습니다. 기본 공유 예제 변경 API는 비활성화하며 CSV 업로드는 독립 세션을 사용합니다. 실제 고객 자료를 다룰 때는 [보호 모드](protected-mode.md)의 로그인·고객사별 권한·세션 소유권 설정을 사용합니다. 단일 프로세스 범위와 로그인 속도 제한을 확인하세요. 공개 데모는 익명 합성 모드입니다.

## TensorFlow 대조 검사

공개 서비스는 TensorFlow를 요구하지 않습니다. 별도 환경에서 CPU TensorFlow/Keras와 PyTorch를 설치해 비교할 수 있습니다. CI도 이 검사를 전용 작업으로 실행하며 설치 누락을 통과로 처리하지 않습니다.

```bash
python3.12 -m venv .venv-tf
source .venv-tf/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
pip install -c constraints.txt -c tensorflow-constraints.txt -e '.[dev,tf]'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1
pytest tests/test_keras_parity.py -ra
python scripts/keras_parity_check.py --features data/features.parquet --train-months 24 --val-months 6 --epochs 12 --shared-initialization --out /tmp/keras-comparison.json
```

`--shared-initialization`은 학습 **전** 가중치를 공유하는 통제 실험입니다. 옵션 없이 실행하면 각 프레임워크의 독립 초기화를 사용합니다. 어느 경우든 검증 점수는 조기종료에 사용한 자료의 값이며 독립 테스트가 아닙니다. 원시 JSON에는 입력/소스 해시, 패키지 버전, 분할 경계와 기존 차이 기준 통과 여부가 포함됩니다. CLI 종료 코드 0은 유한한 점수의 계산 완료를 뜻하며, 차이 기준 통과는 JSON의 `comparison_passed`를 확인해야 합니다. CI의 실제 학습 검사는 차이 한도를 별도로 단언합니다. 실제 실행 결과와 독립 초기화 기준 실패는 [이번 감사](verification/requirements-20261026/README.md)를 참조하세요.

특징 버전 3은 비물리적인 에너지 기대치의 잔차를 결측으로 처리합니다. 기존 모델을 사용할 때 특징만 새로 생성해 섞지 말고, 별도 디렉터리에서 전처리와 모델을 함께 재학습해야 합니다. 같은 버전의 과거 모델/캐시를 읽는 것과 새 특징을 생성하는 것은 구분합니다.
