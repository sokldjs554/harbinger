PY ?= python
DATA ?= data
MODELS ?= models
ARTIFACTS ?= artifacts
SEED ?= 20260101

.PHONY: help install synth features eval signals replay-summary pipeline figures numbers check-numbers test lint fmt serve docker clean

help:
	@echo "make install    - venv 에 개발 의존성 설치 (CPU torch)"
	@echo "make pipeline   - synth → features → eval → figures → numbers (약 30분, 4 vCPU)"
	@echo "make serve      - API + 콘솔 (http://localhost:8000)"
	@echo "make test       - 린트 + 테스트"
	@echo "make docker     - 이미지 빌드 후 compose 기동"

install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
	$(PY) -m pip install -c constraints.txt -e ".[dev]"

synth:
	harbinger synth --out $(DATA) --seed $(SEED)

features:
	harbinger features --data $(DATA)

eval:
	harbinger eval --data $(DATA) --models $(MODELS) --artifacts $(ARTIFACTS) --seed $(SEED)

figures:
	$(PY) scripts/make_figures.py --artifacts $(ARTIFACTS) --data $(DATA) --models $(MODELS) --out docs/images

numbers:
	$(PY) scripts/fill_numbers.py --artifacts $(ARTIFACTS)

check-numbers:
	$(PY) scripts/fill_numbers.py --artifacts $(ARTIFACTS) --check

signals:
	$(PY) scripts/make_signals.py --data $(DATA) --out $(ARTIFACTS)/signals.json

replay-summary:
	$(PY) scripts/make_replay_summary.py --data $(DATA) --models $(MODELS) --artifacts $(ARTIFACTS)

pipeline: synth features eval signals replay-summary figures numbers

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

fmt:
	ruff format src tests scripts
	ruff check --fix src tests scripts

test: lint
	pytest -q

serve:
	harbinger serve --port 8000

docker:
	docker compose up --build

clean:
	rm -rf $(DATA)/*.parquet $(DATA)/*.json $(MODELS)/v* $(MODELS)/manifest.json $(ARTIFACTS)/*.json

.PHONY: demo demo-gif
demo:
	$(PY) scripts/build_workbench_demo.py --out docs/demo --data $(DATA) --models $(MODELS) --artifacts $(ARTIFACTS)

# 실행 중인 API를 80초 녹화한다. Playwright Chromium 및 ffmpeg가 필요하다.
demo-gif:
	$(PY) scripts/record_workbench.py
	@echo "docs/verification/video의 WebM을 확인하고 필요하면 ffmpeg로 변환하세요."
