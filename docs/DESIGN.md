---
title: "medcoder: Auditable Medical-Coding Pipeline"
---

# 1 · Architecture & Data Flow

medcoder converts a free-text clinical note into billable codes (ICD-10-CM, the
US clinical modification of ICD-10, for diagnoses; CPT for procedures) via a
seven-stage pipeline (from `note.txt` to `result.json`) as shown in the diagram
below. Three stages are LLM agents; four are deterministic code. Every stage is
idempotent and writes to a trace file, so a reviewer can see exactly how each
code was reached.

![Seven-stage pipeline from note.txt to result.json.](assets/pipeline.svg)

| # | Stage | Runs on | What it does | Output |
|---|-------|---------|--------------|--------|
| 1 | Ingest | deterministic | normalises text, splits SOAP sections, windows long notes, keeps offsets | clean note |
| 2 | Extract | Extraction agent | pulls facts (span, normalised term, present/absent/possible, dx/px); a NegEx backstop fixes polarity | facts |
| 3 | Retrieve | deterministic | hybrid search returns a real-code shortlist per fact (§2) | candidates |
| 4 | Code | Coder agent | picks 1 to N codes per fact, only from the shortlist, quoting evidence | assigned codes |
| 5 | Audit | Auditor agent | a second, independent model re-checks each (evidence, code) pair | agree / disagree |
| 6 | Rules | deterministic | ICD-10-CM checks (Excludes1 conflicts, missing detail, format) | typed warnings |
| 7 | Assemble | deterministic | blends signals into a high/medium/low tier; writes the result and trace | result.json |

Each run writes one result file (`result.json`, or `result.md` /
`result.annotated.md` per `--format`) plus a `trace.json` recording every stage's
output: the facts, the per-fact shortlist, the coder choices, and the auditor
verdicts.

# 2 · Code retrieval / Filtering strategy

**Design:** the coder is constrained to select only from a retrieved candidate
set and can never free-generate a code. For each extracted fact, a short list of
real catalog codes is retrieved; the coder may choose only from that list, and
any code not on it is discarded during validation. Invalid codes are therefore
impossible by construction, which matters because models that free-generate
ICD-10 codes frequently emit invalid or non-billable ones [1].

The shortlist is built from two complementary searches over the code
descriptions, fused into one ranked list:

- **Dense search** matches by meaning (semantic similarity via cosine), so
  "DM type 2" finds "type 2 diabetes mellitus". Sentence-transformer embeddings
  (`all-MiniLM-L6-v2` by default) are queried over a FAISS index (top 50).
- **Lexical search (BM25)** matches exact wording, where a phrase like "essential
  hypertension" must be read word for word (top 50).
- **Reciprocal Rank Fusion** [2] merges the two by rank, so the different scoring
  scales need no calibration; the top 15 become the shortlist. Each fact is also
  queried with a few agent-supplied synonyms (for example "MI" to "myocardial
  infarction") to widen recall.

**Data:** the real CDC ICD-10-CM FY2027 catalog (about 74,879 codes, public
domain) is bundled, so the large-vocabulary challenge is genuine. CPT is
AMA-copyrighted, so a clearly marked synthetic CPT-shaped catalog is shipped, and
a licensed real-CPT catalog can be substituted through configuration without code
changes.

# 3 · LLM usage & Prompting approach

Three role-specialised agents mirror the real coder-then-QA workflow, all behind
one LiteLLM gateway so providers and per-agent models swap by environment
variable.

| Agent | Human analog | Model (default) | Key constraint |
|-------|--------------|-----------------|----------------|
| Extraction | clinical scribe | `openai/gpt-5.4-mini` | reason first, then emit schema-validated JSON |
| Coder | medical coder | `openai/gpt-5.4-mini` | may only choose codes from the shortlist |
| Auditor | QA reviewer | `anthropic/claude-haiku-4-5-20251001` | a different model family by default |

- A **different model family for the auditor** reduces correlated errors and
  self-preference bias, where a model rubber-stamps its own answer [3].
- **Reason first, then format:** forcing JSON-only output degrades reasoning [4],
  so the model thinks internally then emits one schema-validated JSON object,
  with a single repair-retry on a validation failure.
- **Cost discipline:** the extraction call also returns the encounter type and
  the retrieval synonyms in one shot; verification is selective (procedures and
  low-confidence diagnoses only) and calls are batched.
- **Confidence is not the raw LLM number** (which is overconfident): we blend the
  fused retrieval rank, the coder's discounted confidence, and an auditor
  adjustment, then bin into high, medium, or low tiers.

# 4 · Key decisions & trade-offs

| Decision | Why | Trade-off |
|----------|-----|-----------|
| Retrieve, then constrain (shortlist, not free generation) | Removes invalid codes; turns a 75k-way generation problem into a 15-way choice [5] | Bounded by retriever recall, now measured as a separate eval stage |
| Coder plus independent auditor | Best precision and recall; heterogeneous checkers cut correlated errors [3] | Extra LLM calls, reduced by selective and batched verification |
| Hybrid retrieval with RRF | Catches exact terms and paraphrases, no score tuning | Two indexes to build (about a minute on 75k codes) |
| Real ICD-10-CM plus synthetic CPT | Meets the large-vocabulary challenge within AMA licensing | CPT demo runs on synthetic codes |
| Deterministic rules and temp-0 pinned models | Auditable, reproducible, no LLM cost for hard checks | Curated rule subset; foregoes a small sampling-accuracy gain |

# 5 · Limitations & extensions

- *Assistive, not autonomous.* On the evaluation set the system reaches ICD-10
  micro-F1 about 0.5; full-vocabulary ICD-10 coding is hard in general (reported
  state of the art is around 0.54 [6]), so a human reviewer is required. The
  output (evidence spans, confidence tiers, editable fields) makes that review
  fast.
- *CPT is synthetic.* Real-CPT accuracy must be re-validated on a licensed
  catalog, which is substituted through configuration without code changes.
- *General-purpose embedder.* `all-MiniLM-L6-v2` is the default because it is
  local, keyless, fast, and adequate for the short code-description strings being
  embedded. Production clinical text would benefit from a domain-specific
  biomedical embedder (SapBERT or PubMedBERT, trained for mention-to-concept
  linking); the embedder is pluggable via configuration.
- *Evaluation is directional.* The small authored gold set (n=4) gives
  directional signal only; the contribution is the metric methodology (micro
  P/R/F1, hierarchical F1, per-stage retrieval recall), not the absolute scores.
  A larger synthetic set would not add credibility; real validation needs a
  licensed labelled corpus such as MIMIC-IV. Precision is over-coding-bound (more
  codes emitted than gold labels), so the main lever is a more selective coder.
- *Extensions the architecture supports but does not yet implement.* A
  Postgres-backed retriever (semantic,
  full-text, and fuzzy search in one datastore), biomedical embeddings with a
  SNOMED-to-ICD crosswalk, a fuller rule engine (ICD-10 tabular plus CMS NCCI),
  and a FastAPI reviewer UI. Idempotent stages can be orchestrated by Airflow or
  Celery.

**References**

[1] NEJM AI, 2024 (LLMs free-generate invalid ICD-10 codes). [2] Cormack et al.,
2009 (Reciprocal Rank Fusion). [3] arXiv:2410.21819 (heterogeneous verifiers cut
correlated errors). [4] arXiv:2408.02442 (JSON-only output constraints degrade
reasoning). [5] arXiv:2407.12849 (retrieve-then-rerank constrained coding).
[6] RAG-Coding, 2026 (full-vocabulary ICD-10 state of the art about micro-F1 0.54).
