PY ?= python
DATA ?= data
MODELS ?= models
ARTIFACTS ?= artifacts
SEED ?= 20260101

.PHONY: help install synth features eval pipeline figures numbers check-numbers test lint fmt serve docker clean

help:
	@echo "make install    - venv 에 개발 의존성 설치 (CPU torch)"
	@echo "make pipeline   - synth → features → eval → figures → numbers (약 30분, 4 vCPU)"
	@echo "make serve      - API + 콘솔 (http://localhost:8000)"
	@echo "make test       - 린트 + 테스트"
	@echo "make docker     - 이미지 빌드 후 compose 기동"

install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.4"
	$(PY) -m pip install -e ".[dev]"

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

pipeline: synth features eval figures numbers

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
