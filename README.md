# medcoder : auditable medical-coding pipeline

> An offline pipeline that reads unstructured clinical notes and produces
> **reviewer-ready** ICD-10 diagnosis + CPT procedure suggestions, each with a
> confidence score, supporting evidence, warnings, and a complete audit trail.

The design thesis (`docs/DESIGN.pdf`):
**medcoder converts a free-text clinical note into billable codes through a
seven-stage pipeline in which the LLM is a constrained reasoning component, not
the pipeline itself.** Three stages are LLM agents; the other four are plain
deterministic code. The coder can never free-generate a code: hybrid retrieval
pre-constrains it to a shortlist of real catalog codes, a deterministic rule
engine post-constrains it against ICD-10-CM coding guidelines, and a second,
independent auditor model re-checks each (evidence, code) pair. Every stage is
idempotent and records its output to a trace, so a reviewer can reconstruct
exactly how each code was reached.

```
  ┌── clinical note ────────────────────────────────────────────────────┐
  │                                                                     │
  │  1. ingest (deterministic)         normalise / encounter / window   │
  │  2. extract  [primary LLM]         facts + evidence + assertion     │
  │  3. retrieve (deterministic)       FAISS + BM25 → RRF → whitelist   │
  │  4. code     [primary LLM]         pick code(s) from whitelist      │
  │  5. audit    [independent LLM]     evidence really supports code?   │
  │  6. rules    (deterministic)       Excludes1 / specificity / linkage│
  │  7. assemble (deterministic)       blend + tier confidence; emit    │
  │                                                                     │
  └── reviewer-ready CodingResult (Pydantic-validated JSON) ────────────┘
```

---

## The deliverable — where to read what

| If you want…                                    | Read                                                                 |
| ----------------------------------------------- | -------------------------------------------------------------------- |
| **The design** (architecture, retrieval, prompting, trade-offs, limitations) — *the document to grade* | **[`docs/DESIGN.pdf`](docs/DESIGN.pdf)** — the 1–2 page PDF deliverable |
| **To run it** (local or Docker)                 | This README, §1 below                                                |
| **Real output, without running anything**       | [`outputs/`](outputs/) — pre-run results + audit traces for all 4 notes (§2) |
| **A stage-by-stage code tour**                  | [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) — the optional deep-dive |

> **`docs/DESIGN.pdf` is the primary written deliverable.** It is the concise
> (1–2 page) design document the exercise asks for. `docs/DESIGN.md` is its
> source; rebuild with `make pdf`. An expanded version covering the same five
> sections in more depth lives in `docs/DESIGN-full.md` / `docs/DESIGN-full.pdf`
> (rebuild with `make pdf-full`).

---

## What to look at first

If you have ten minutes, read these — they carry the whole design thesis:

1. **`src/medcoder/pipeline.py`** — the 7-stage orchestration with per-stage
   timing and graceful degradation; the spine everything hangs off.
2. **`src/medcoder/code_assign.py`** + **`src/medcoder/verify.py`** — the
   whitelist-constrained coder and the *independent* auditor agent (the
   multi-LLM check that flags codes the cited evidence doesn't support).
3. **`src/medcoder/rules.py`** — the deterministic post-constraint engine
   (Excludes1, specificity, dx↔px linkage) that no LLM can override.
4. **`src/medcoder/schemas.py`** — the Pydantic `CodingResult` contract: the
   reviewer-ready payload every stage builds toward.

---

## 1 · Quickstart

### Local (Python 3.11+)

```bash
# 1. Install
make install                              # creates .venv, installs in editable mode

# 2. Get the real ICD-10-CM catalog (US public domain) + build indexes
make build-index

# 3. (Optional) Set LLM provider keys. The default config is cross-family.
#    Either export them, or put them in .env (auto-loaded at startup):
export OPENAI_API_KEY=sk-...              # coder + extraction (gpt-5.4-mini)
export ANTHROPIC_API_KEY=sk-ant-...       # independent auditor (claude-haiku-4-5)
#   single-provider? point every model at one provider via MEDCODER_*_MODEL

# 4. Run the pipeline on a sample note (live LLMs)
make run                                  # uses note_01_outpatient_diabetes.txt
#   → JSON CodingResult to stdout, AND saved to outputs/<doc_id>/
#     (result.json + trace.json — the per-run audit trail). Flags:
#       --no-save          stdout only (no outputs/ folder)
#       --format md        human-readable review sheet instead of JSON
#       --format annotated the note with codes spliced in inline at each span
#       --out PATH         write one file to an exact path

# 4b. No LLM key? Use the mocked smoke run against the real ICD-10 index:
make smoke                                # same JSON shape, canned LLM responses

# 5. Tests (mocked LLM — no API key required)
make test                                 # full suite (~30–60s; embedding-warm)
make test-fast                            # fast unit tests only (~0.2s)

# 6. Gold-set evaluation
make eval                                 # gold-set metrics — needs an LLM key (live calls)
```

> **First run.** `make build-index` does a one-time download of the
> `all-MiniLM-L6-v2` embedder from the HuggingFace Hub. The
> `unauthenticated requests to the HF Hub` line it prints is a benign rate-limit
> notice, **not an error**. Embedding ~75k ICD-10 codes takes ~60–90 s on CPU
> (cached to `data/index/` afterwards, so later runs are instant).

### Container

No local Python needed — Docker is fully self-contained. The image downloads the
ICD-10 catalog and **pre-builds both retrieval indexes at build time**, so the
first in-container `run` is immediate.

```bash
# 1. Build the image (one-time; ~2–3 min — embeds 75k ICD-10 codes into the image)
docker build -t medcoder:dev .

# 2. Run the pipeline on a bundled note. Pass keys through with -e:
docker run --rm \
  -e OPENAI_API_KEY -e ANTHROPIC_API_KEY \
  medcoder:dev run /app/data/notes/note_01_outpatient_diabetes.txt

#    (-e VAR with no value forwards it from your shell. Or use --env-file .env.)
```

```bash
# Shortcut: build + run the sample note in one step
make docker-run

# Single-provider? Route the auditor to your one provider (no second key needed):
docker run --rm -e OPENAI_API_KEY -e MEDCODER_VERIFIER_MODEL=openai/gpt-5.4-mini \
  medcoder:dev run /app/data/notes/note_01_outpatient_diabetes.txt

# No key at all? The keyless mocked smoke run works in-container too
# (--entrypoint overrides the default `medcoder` entrypoint):
docker run --rm --entrypoint python medcoder:dev -m scripts.smoke_with_mocks
```

Outputs print to stdout. To get the saved `outputs/<doc_id>/` folder back on your
host, mount a volume: add `-v "$PWD/outputs:/app/outputs"` to the `run` command.

---

## 2 · What you get back

`medcoder run note.txt` emits a Pydantic-validated `CodingResult`:

```jsonc
{
  "document_id": "note_01_outpatient_diabetes",
  "diagnoses": [
    {
      "code": "E11.42",
      "system": "ICD-10-CM",
      "description": "Type 2 diabetes mellitus with diabetic polyneuropathy",
      "confidence": 0.86,
      "confidence_tier": "high",
      "rationale": "Assessment names T2DM with diabetic polyneuropathy; …",
      "evidence": [{ "text": "Type 2 diabetes mellitus with diabetic polyneuropathy",
                     "start_offset": 1142, "end_offset": 1195, "section": "assessment",
                     "assertion_status": "present", "kind": "diagnosis" }],
      "reviewer_decision": "suggested",
      "audit_agree": true
    }
    // …
  ],
  "procedures": [ /* CPT — synthetic in this build, see LICENSING.md */ ],
  "warnings": [
    { "type": "missing_information", "severity": "info",
      "message": "Code E66.9 is 'unspecified' — …", "refs": ["E66.9"] }
  ],
  "metadata": {
    "trace_id": "9f3e1c…", "config_hash": "1a2b…",
    "model_ids": { "extraction": "openai/gpt-5.4-mini",
                   "coder":      "openai/gpt-5.4-mini",
                   "auditor":    "anthropic/claude-haiku-4-5-20251001" },
    "pipeline_version": "0.1.1", "temperature": 0.0,
    "timestamp": "2026-06-26T00:00:00Z", "encounter_type": "outpatient",
    "metrics": {
      "stage_latency_ms": { "ingest": 0.6, "extract": 1842, "retrieve": 71,
                            "code": 2103, "audit": 1755, "rules": 1.1,
                            "assemble": 0.4 },
      "total_latency_ms": 5773, "est_cost_usd": 0.0288, "retries": 0,
      "n_candidates": 47, "n_warnings": 2, "n_facts": 5, "n_facts_coded": 4,
      "tokens": { "extraction.total_tokens": 1822, "coder.total_tokens": 2412,
                  "auditor.total_tokens": 1430 }
    }
  }
}
```

Every code carries: machine-checkable **evidence spans** (with offsets back into
the original note), a **blended-then-tiered confidence**, an **auditor verdict**,
and **reviewer-override fields** (`reviewer_decision`, `reviewer_code`,
`reviewer_note`) so the reviewer can accept / modify / reject in place.

**Three views, one payload.** JSON is the machine/audit format. `--format md`
renders the same `CodingResult` as a human review sheet (one row per code with an
Accept? column, confidence tier, evidence quote, and auditor verdict).
`--format annotated` renders the **clinical note itself with each suggested code
spliced in inline at the evidence span** that justifies it — the way a coder reads
the chart. **Audit trail.** Each run auto-saves a self-contained
`outputs/<doc_id>/` folder: the rendered result (`result.json`, or `result.md` /
`result.annotated.md` per `--format`) plus `trace.json` — the full
decision trail (extracted facts, the retrieval candidate whitelist *per fact*, the
coder's choices, and the auditor's verdicts), so a reviewer can reconstruct *how*
each suggestion was reached, not just see the final codes. `--no-save` opts out.

> **Pre-run examples are committed.** [`outputs/`](outputs/) already holds the
> real-API result for **all four notes** — `result.json`, `result.md`,
> `result.annotated.md`, and `trace.json` each — plus `outputs/eval/metrics.json`
> (gold-set scores). Inspect them with no keys and no run. `make run` overwrites
> your local copy; regenerate the whole set with `make examples`.

---

## 3 · Data licensing — read this

`LICENSING.md` is the canonical word, but the short version:

| Artifact          | Source / status                                         | Shipped here?                        |
| ----------------- | ------------------------------------------------------- | ------------------------------------ |
| **ICD-10-CM**     | CDC / NCHS FY2027 file — **US public domain**           | Downloaded by `make data` (~6 MB)    |
| **CPT**           | AMA-copyrighted; **no free tier**                       | **Synthetic only.** Real CPT drops in via `MEDCODER_CPT_CATALOG=` |
| **Clinical notes**| MIMIC / n2c2 / MTSamples all DUA/PHI-restricted         | **Synthetic only**, authored here    |

The architecture is drop-in for licensed real CPT — same `code, description`
schema, same retrieval / coder / rule paths.

---

## 4 · Architecture at a glance

Full design in `docs/DESIGN-full.md`; this section is the elevator pitch.

- **Retrieve-then-constrain.** The LLM never free-generates a code. For each
  extracted fact, hybrid retrieval (FAISS + BM25, fused via Reciprocal Rank
  Fusion) returns the top-K codes from the real ICD-10 catalog (or the
  synthetic CPT catalog), and the coder agent is constrained to pick from that
  whitelist. Hallucinated codes become *structurally impossible*.
- **Coder + Auditor decomposition.** A coder agent assigns codes from the
  whitelist; an *independent* auditor agent (a different LLM by default — set
  via `MEDCODER_VERIFIER_MODEL`) re-reads the cited evidence and flags
  disagreements. Triage keeps cost down: high-confidence diagnoses skip the
  auditor; procedures and low-confidence diagnoses always go through it.
- **Symbolic post-constraint.** A deterministic rule engine flags Excludes1
  conflicts, unspecified codes when more specific ones are warranted, missing
  7th-character extensions, procedures without supporting diagnoses, and
  invalid code formats. Warnings are typed (`missing_information` / `ambiguity`
  / `conflict`) and carry severity.
- **Calibrated confidence.** Raw LLM verbalised confidence is systematically
  overconfident. The pipeline blends retrieval rank, coder confidence, and
  auditor verdict, then bins the result into 🟢 / 🟡 / 🔴 tiers. (Formal
  isotonic / Platt calibration is documented as a production extension.)
- **Observability everywhere.** Structured JSON logs keyed by `trace_id`,
  per-stage latency, per-agent token/cost capture, retry counts, candidate
  counts, and warning counts all flow into `RunMetadata.metrics` and into the
  stderr log stream. `medcoder config` prints the resolved settings and a
  `config_hash` that fingerprints the run.

---

## 5 · Configuration

All env-driven via pydantic-settings; the common settings live in `.env.example`:

```bash
MEDCODER_LLM_MODEL=openai/gpt-5.4-mini        # extraction + coder (shared default)
MEDCODER_VERIFIER_MODEL=anthropic/claude-haiku-4-5-20251001  # auditor — *different* family
MEDCODER_EXTRACTION_MODEL=                     # optional per-agent override (falls back to LLM_MODEL)
MEDCODER_CODER_MODEL=                          # optional per-agent override
MEDCODER_REASONING_EFFORT=low                  # OpenAI GPT-5 reasoning effort; bounds cost
MEDCODER_RETRIEVAL_TOP_K=15                   # whitelist size per fact
MEDCODER_TEMPERATURE=0.0                      # honoured by Claude; GPT-5 rejects non-default
MEDCODER_EMBEDDER=sentence-transformers/all-MiniLM-L6-v2
MEDCODER_NO_VERIFY=0                          # 1 → skip the auditor pass
MEDCODER_AUDIT_LOW_CONF_THRESHOLD=0.75        # ≤ this triggers the auditor
```

Each agent's model is overridable independently (extraction / coder fall back to
`MEDCODER_LLM_MODEL`; the auditor uses `MEDCODER_VERIFIER_MODEL`), so cost can be
tuned per role — e.g. drop extraction to `openai/gpt-5.4-nano`. The defaults pin
*specific* model IDs for reproducibility.

**Embedder & single-provider behaviour.** `MEDCODER_EMBEDDER` selects the dense
backend. Any sentence-transformers model runs **locally and keyless** — MiniLM by
default, or a clinical model such as `cambridgeltl/SapBERT-from-PubMedBERT-fulltext`
— while `openai/text-embedding-3-large` (or any `text-embedding-*`) uses a hosted
OpenAI backend that needs `OPENAI_API_KEY` at *build* time. After changing it, run
`make build-index ARGS='--force'`: each index records the embedder it was built
with and refuses to load against a different one, preventing silent
dimension-mismatch garbage. On the LLM side, if *only* the auditor's provider key
is missing, the CLI degrades gracefully to `--no-verify` (with a warning) rather
than hard-failing. Note the GPT-5 family are reasoning
models that reject a non-default `temperature`, so `temperature=0` applies to
providers that honour it (Claude) while GPT-5 determinism rests on Structured
Outputs + low reasoning effort. The full reproducibility envelope (resolved
per-agent model IDs, `reasoning_effort`, temperature) is captured in the
`config_hash` and `RunMetadata`.

---

## 6 · Project layout

```
.
├── README.md                # ← this file (the runbook)
├── LICENSING.md             # data / code licensing notes
├── pyproject.toml
├── Makefile                 # install / data / build-index / run / test / eval / pdf / docker
├── Dockerfile               # py3.11-slim; pre-builds indexes
├── .env.example
├── data/
│   ├── catalogs/            # ICD-10 (downloaded) + synthetic CPT (bundled)
│   ├── notes/               # 4 authored synthetic notes (multi-page, negation, ambiguity, conflict)
│   ├── gold/labels.json     # gold ICD-10 + CPT labels for `make eval`
│   └── index/               # cached FAISS + BM25 indexes (gitignored)
├── docs/
│   ├── DESIGN.md            # concise 1–2 page design (the source for the PDF deliverable)
│   ├── DESIGN.pdf           # ← the PDF deliverable; built by `make pdf`
│   ├── DESIGN-full.md       # expanded design, same five sections in more depth
│   ├── DESIGN-full.pdf      # rendered full version; built by `make pdf-full`
│   └── WALKTHROUGH.md       # optional stage-by-stage code tour
├── outputs/                 # COMMITTED pre-run examples (4 notes + eval metrics)
│   ├── note_01.../          #   result.json + result.md + result.annotated.md + trace.json
│   └── eval/metrics.json    #   gold-set scores (P/R/F1, recall@k, latency, cost)
├── scripts/
│   ├── build_index.py
│   ├── evaluate.py
│   ├── generate_examples.py # regenerates outputs/ via live run (make examples)
│   ├── smoke_with_mocks.py  # keyless mocked pipeline run (make smoke)
│   └── build_pdf.sh         # DESIGN.md → PDF without LaTeX (pandoc → headless Chrome)
├── src/medcoder/
│   ├── cli.py               # `medcoder` entry point
│   ├── config.py            # pydantic-settings + config_hash
│   ├── schemas.py           # Pydantic data contracts (the public payload)
│   ├── logging_setup.py     # structured JSON logs + trace_id
│   ├── llm.py               # LiteLLM gateway (structured output, repair, cache, cost)
│   ├── ingest.py            # normalise / encounter / SOAP / window / global offsets
│   ├── extract.py           # extraction agent + assertion backstop
│   ├── retrieval/
│   │   ├── catalog.py       # ICD-10 / CPT loaders
│   │   ├── embedders.py     # pluggable dense backends (MiniLM / SapBERT / OpenAI) + factory
│   │   ├── vector.py        # FAISS dense index (pluggable embedder + dim-guard sidecar)
│   │   ├── lexical.py       # BM25
│   │   └── hybrid.py        # RRF fusion + the persistent retriever cache
│   ├── code_assign.py       # coder agent (whitelist-constrained)
│   ├── verify.py            # auditor agent (independent model, selective + batched)
│   ├── rules.py             # deterministic rule engine
│   ├── confidence.py        # blend + tier
│   ├── pipeline.py          # orchestration + per-stage timing
│   └── prompts/             # versioned prompts (extraction_p1 / coder_p1 / auditor_p1)
└── tests/
    ├── conftest.py          # mock fixtures, isolated cache
    ├── test_schemas.py
    ├── test_ingest.py
    ├── test_retrieval.py
    ├── test_extraction.py
    ├── test_rules.py
    ├── test_confidence.py
    ├── test_pipeline_mock.py
    ├── test_consistency.py  # reproducibility — same input + mocks → same output
    ├── test_embedders.py    # embedder factory + OpenAI backend (mocked) + dim-guard
    └── test_outputs_and_render.py  # md view, audit trace, auto-save, recall@k
```

---

## Eval results (directional — n=4)

Measured on the 4-note authored gold set with a single-provider run —
reproduce with `MEDCODER_VERIFIER_MODEL=openai/gpt-5.4-mini make eval`. (Plain
`make eval` uses the default cross-family config: OpenAI coder + Anthropic
auditor.)

The figures below are the **exact committed run** in
[outputs/eval/metrics.json](outputs/eval/metrics.json) (rebuild with `make eval`):

| Metric                       |    P |    R |   F1 |
| ---------------------------- | ---: | ---: | ---: |
| **ICD-10 (micro)**           | 0.41 | 0.64 | 0.50 |
| ICD-10 hierarchical (3-char) | 0.50 | 0.77 | 0.61 |
| **CPT (micro)**              | 0.89 | 0.80 | 0.84 |
| Exact-match (note-level)     |    — |    — | ICD 0% · CPT 25% |

Four notes is too small to be a benchmark — read these as directional. **Run-to-run
variance is real at this scale** (±0.05+ micro-F1 between runs is normal LLM
sampling noise at n=4), so treat `outputs/eval/metrics.json` as one representative
run, not a fixed score. ICD-10 micro-F1 (**≈0.5**) sits near the ~0.54
full-vocabulary SOTA ceiling; recall > precision is by design — retrieval **query
expansion** (the extraction agent emits lookup synonyms) plus **LLM encounter-type**
classification over-surface candidates with typed warnings (5–14/note) for a human
reviewer rather than silently missing codes. Precision (~0.41) is bounded by
**over-coding** (the coder emits more codes than gold), not by retrieval — a more
selective coder and a larger gold set are the levers for higher precision.

`make eval` also reports a per-stage **retrieval recall@k** — whether each gold
code reached the candidate whitelist the retriever produced. This separates a
*retrieval* miss ("the code was never surfaced") from a *coder* miss ("it was
surfaced but not picked"), so an end-to-end miss is diagnosable to the stage that
caused it rather than blamed on the pipeline as a whole.

---

## 7 · Limitations & extensions

The design doc (`docs/DESIGN-full.md` §5) is the authoritative list. The key
limitations to set reviewer expectations:

- **Assistive, not autonomous.** SOTA full-vocabulary ICD-10 coding tops out
  around micro-F1 ≈ 0.54 (RAG-Coding 2026), so a human reviewer is required by
  design. Every payload field is shaped to make that review fast.
- **CPT is synthetic.** Real CPT drops in via config; the pipeline is
  unaffected. CPT coding accuracy should be validated separately on a real
  catalog before any production use.
- **General-purpose embedder.** `all-MiniLM-L6-v2` is a demo compromise; the
  production choice is a biomedical embedder (SapBERT / PubMedBERT) for better
  semantic match on clinical terminology.
- **Eval is directional**, not a benchmark — 4 authored notes (numbers in the
  Eval results section above). Methodology and metric choices are sound
  (`scripts/evaluate.py`); only the sample size is small.
- **Confidence is gold-tuned, not formally calibrated.** Isotonic / Platt
  calibration with ECE is a documented extension (needs a larger labelled set
  than a small authored gold set supports).
- **Reproducibility is engineered**, not bit-for-bit guaranteed across provider
  model updates — that's why we pin dated snapshots and log everything.

Production extensions (kept out of MVP scope on purpose): Postgres
(`pgvector` + `tsvector` + `pg_trgm`) as the single hybrid datastore, biomedical
embeddings, full ICD-10 tabular-rule + NCCI engine, FastAPI + reviewer UI,
self-consistency confidence, licensed CPT, Langfuse / OpenTelemetry tracing via
LiteLLM callbacks (one env flag).
