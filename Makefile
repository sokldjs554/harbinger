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

.PHONY: demo demo-gif
demo:
	$(PY) scripts/build_static_demo.py --out docs/demo --data $(DATA) --models $(MODELS) --artifacts $(ARTIFACTS)

# 정적 데모를 로컬로 띄워 녹화한다 (Playwright + ffmpeg). CHROMIUM_PATH 로 브라우저 지정 가능.
demo-gif:
	cd docs/demo && $(PY) -m http.server 8020 >/dev/null 2>&1 & sleep 2; \
	node scripts/record_demo.cjs http://localhost:8020 /tmp/harbinger-demo > /tmp/harbinger-demo/video.txt 2>&1; \
	ffmpeg -y -loglevel error -ss 0.5 -i "$$(tail -1 /tmp/harbinger-demo/video.txt)" -vf "fps=8,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" docs/images/demo.gif; \
	pkill -f "http.server 8020"; ls -la docs/images/demo.gif
