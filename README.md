# medcoder — auditable medical-coding pipeline

> AppliedAI · Opus AI Engineer take-home (Exercise 2)
>
> An offline pipeline that reads unstructured clinical notes and produces
> **reviewer-ready** ICD-10 diagnosis + CPT procedure suggestions, each with a
> confidence score, supporting evidence, warnings, and a complete audit trail.

The design thesis (full details in `docs/DESIGN.md` and the 1–2 page PDF):
**the LLM is a constrained reasoning component inside a deterministic,
observable pipeline — not the pipeline itself.** Retrieval pre-constrains the
LLM to real codes; a deterministic rule engine post-constrains it against
ICD-10 coding guidelines; an independent auditor agent reviews each assignment
against the cited evidence.

```
  ┌── clinical note ────────────────────────────────────────────────────┐
  │                                                                     │
  │  1. ingest (deterministic)         normalise / encounter / window   │
  │  2. extract  [LLM-A]               facts + evidence + assertion     │
  │  3. retrieve (deterministic)       FAISS + BM25 → RRF → whitelist   │
  │  4. code     [LLM-A]               pick code(s) from whitelist      │
  │  5. audit    [LLM-B independent]   evidence really supports code?   │
  │  6. rules    (deterministic)       Excludes1 / specificity / linkage│
  │  7. assemble (deterministic)       blend + tier confidence; emit    │
  │                                                                     │
  └── reviewer-ready CodingResult (Pydantic-validated JSON) ────────────┘
```

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

# 3. (Optional) Set LLM provider keys. The default config is cross-family:
export OPENAI_API_KEY=sk-...              # coder + extraction (gpt-5.4-mini)
export ANTHROPIC_API_KEY=sk-ant-...       # independent auditor (claude-haiku-4-5)
#   single-provider? point every model at one provider via MEDCODER_*_MODEL (.env)

# 4. Run the pipeline on a sample note (live LLMs)
make run                                  # uses note_01_outpatient_diabetes.txt
#   → JSON CodingResult to stdout, structured logs to stderr

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

```bash
make docker-run                           # builds image, runs the sample note
# or:
docker build -t medcoder .
docker run --rm -e OPENAI_API_KEY medcoder \
  run /app/data/notes/note_01_outpatient_diabetes.txt
```

The Dockerfile pre-builds the retrieval indexes inside the image, so the first
in-container `run` is fast.

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
    "pipeline_version": "0.1.0", "temperature": 0.0,
    "timestamp": "2026-06-26T00:00:00Z", "encounter_type": "outpatient",
    "metrics": {
      "stage_latency_ms": { "ingest": 0.6, "extract": 1842, "retrieve": 71,
                            "code": 2103, "audit": 1755, "rules": 1.1,
                            "assemble": 0.4 },
      "total_latency_ms": 5773, "est_cost_usd": 0.0091, "retries": 0,
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

Full design in `docs/DESIGN.md`; this section is the elevator pitch.

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
*specific* model IDs for reproducibility. Note the GPT-5 family are reasoning
models that reject a non-default `temperature`, so `temperature=0` applies to
providers that honour it (Claude) while GPT-5 determinism rests on Structured
Outputs + low reasoning effort. The full reproducibility envelope (resolved
per-agent model IDs, `reasoning_effort`, temperature) is captured in the
`config_hash` and `RunMetadata`.

---

## 6 · Project layout

```
.
├── README.md                # ← this file
├── LICENSING.md             # data / code licensing notes
├── Problem.md               # the take-home brief
├── Plan.md                  # full working plan (in-code "§9.x" pointers refer here)
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
│   ├── DESIGN.md            # full design (the source for the 1–2 page PDF)
│   └── DESIGN.pdf           # built by `make pdf`
├── scripts/
│   ├── build_index.py
│   ├── evaluate.py
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
│   │   ├── vector.py        # FAISS over MiniLM
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
    └── test_consistency.py  # reproducibility — same input + mocks → same output
```

---

## 7 · Limitations & extensions

The design doc (`docs/DESIGN.md` §5) is the authoritative list. The key
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
- **Eval is illustrative**, not a benchmark — the gold set is 4 authored notes.
  Methodology and metric choices are correct (`scripts/evaluate.py`); only the
  sample size is small.
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
