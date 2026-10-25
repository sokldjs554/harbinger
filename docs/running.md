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
