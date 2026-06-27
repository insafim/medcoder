PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip

# Default: build the venv and install in editable mode.
.PHONY: install
install:
	python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

# Pull CDC ICD-10-CM FY27 (public domain) into data/catalogs/.
.PHONY: data
data:
	mkdir -p data/catalogs
	@if [ ! -f data/catalogs/icd10cm_codes_2026.txt ]; then \
		echo "downloading ICD-10-CM FY2027 (public domain)…"; \
		curl -skL -o /tmp/icd10cm.zip 'https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2027/icd10cm-code-descriptions-2027.zip'; \
		unzip -j -o /tmp/icd10cm.zip 'icd10cm-code-descriptions-2027/icd10cm-codes-2027.txt' -d data/catalogs/; \
		mv data/catalogs/icd10cm-codes-2027.txt data/catalogs/icd10cm_codes_2026.txt; \
		rm /tmp/icd10cm.zip; \
		echo "done."; \
	else \
		echo "ICD-10 catalog already present."; \
	fi

# Build FAISS + BM25 indexes for both code systems (cached on disk).
.PHONY: build-index
# Pass flags through with ARGS, e.g. `make build-index ARGS='--force'` to rebuild,
# or `ARGS='--system cpt --force'` to rebuild a single system.
build-index: data
	$(PYTHON) -m scripts.build_index $(ARGS)

# Run the pipeline on the first synthetic note (smoke test, requires LLM key).
.PHONY: run
run: build-index
	$(PYTHON) -m medcoder.cli run data/notes/note_01_outpatient_diabetes.txt --no-json-logs

# Run the full pipeline against the real ICD-10 index but with mocked LLM responses
# (no API key needed) — handy for reviewers who want to see the JSON payload.
.PHONY: smoke
smoke: build-index
	$(PYTHON) -m scripts.smoke_with_mocks

# Full pytest suite.
.PHONY: test
test:
	$(PYTHON) -m pytest tests/ -v

# Fast tests only (skip the slow embedding tests).
.PHONY: test-fast
test-fast:
	$(PYTHON) -m pytest tests/ -v -m "not slow"

# Gold-set evaluation: micro P/R/F1 (ICD+CPT), exact-match, hierarchical micro-F1, latency/cost. Needs an LLM key.
.PHONY: eval
eval: build-index
	$(PYTHON) -m scripts.evaluate

# Regenerate the committed example outputs under outputs/ (live LLM run on every
# authored note + the gold-set metrics). Needs an LLM key. A reviewer running
# `make run` overwrites their local copy; the committed examples are pre-run so
# the outputs can be inspected without running anything.
.PHONY: examples
examples: build-index
	$(PYTHON) -m scripts.generate_examples

# Style.
.PHONY: lint
lint:
	$(PYTHON) -m ruff check src tests scripts

# Generate the 1–2 page design PDF from DESIGN.md (the submission deliverable).
# Default renders via pandoc → headless Chrome — no LaTeX install needed (this is
# the path that built the committed docs/DESIGN.pdf). Prefer LaTeX? use `make pdf-latex`.
.PHONY: pdf
pdf:
	bash scripts/build_pdf.sh

# Generate the expanded design PDF (docs/DESIGN-full.md → docs/DESIGN-full.pdf).
.PHONY: pdf-full
pdf-full:
	bash scripts/build_pdf.sh docs/DESIGN-full.md

# Alternative: render with a LaTeX engine (requires pandoc + xelatex installed).
.PHONY: pdf-latex
pdf-latex:
	@command -v pandoc >/dev/null || { echo "pandoc not found — install pandoc and a LaTeX engine first"; exit 1; }
	@command -v xelatex >/dev/null || { echo "xelatex not found — install a LaTeX engine, or use 'make pdf'"; exit 1; }
	pandoc docs/DESIGN.md \
	  -o docs/DESIGN.pdf \
	  --pdf-engine=xelatex \
	  -V geometry:margin=0.7in \
	  -V fontsize=10pt \
	  -V linkcolor=blue \
	  --toc=false

# Docker build + smoke-run inside the container.
.PHONY: docker
docker:
	docker build -t medcoder:dev .

.PHONY: docker-run
docker-run: docker
	docker run --rm -e OPENAI_API_KEY -e ANTHROPIC_API_KEY -v "$(PWD)/data:/app/data" medcoder:dev \
	  run /app/data/notes/note_01_outpatient_diabetes.txt --no-json-logs

# Wipe build artefacts (keeps data + venv).
.PHONY: clean
clean:
	rm -rf data/index .cache build dist *.egg-info
	find . -name __pycache__ -type d -exec rm -rf {} +

.PHONY: help
help:
	@echo "make install      — create .venv and install package + dev deps"
	@echo "make data         — download public-domain ICD-10-CM into data/catalogs/"
	@echo "make build-index  — build FAISS + BM25 indexes for ICD-10 and CPT"
	@echo "make run          — pipeline smoke run on a sample note"
	@echo "make test         — full pytest suite"
	@echo "make test-fast    — quick tests only (skip slow embedding tests)"
	@echo "make eval         — gold-set evaluation"
	@echo "make examples     — regenerate committed outputs/ (live run on all notes + metrics)"
	@echo "make lint         — ruff"
	@echo "make pdf          — DESIGN.md → docs/DESIGN.pdf (pandoc → headless Chrome; no LaTeX)"
	@echo "make pdf-full     — DESIGN-full.md → docs/DESIGN-full.pdf (expanded version)"
	@echo "make pdf-latex    — same as pdf, via a LaTeX engine (needs pandoc + xelatex)"
	@echo "make docker       — build the Docker image"
	@echo "make docker-run   — run the pipeline inside the container"
	@echo "make clean        — remove build artefacts (keeps venv + data)"
