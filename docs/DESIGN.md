---
title: "medcoder — Auditable Medical-Coding Pipeline"
subtitle: "AppliedAI · Opus AI Engineer · Exercise 2"
author: "Design Document (1–2 pp distillation)"
date: "June 2026"
---

# 1 · Architecture & data flow

**Design thesis.** The LLM is a *constrained reasoning component inside a
deterministic, observable pipeline* — not the pipeline itself. We make a
stochastic model auditable by **pre-constraining it with retrieval** (it can
only choose real codes), **independently verifying it with an auditor agent**,
and **post-constraining it with a deterministic rule engine** grounded in the
ICD-10-CM Official Guidelines.

The pipeline has seven stages, each idempotent and independently retryable:

```
note.txt ─► ① ingest ─► ② extract ─► ③ retrieve ─► ④ code ─► ⑤ audit ─► ⑥ rules ─► ⑦ assemble ─► CodingResult.json
              (det.)       (LLM-A)        (det.)       (LLM-A)    (LLM-B)      (det.)        (det.)
```

1. **Ingest** — normalize, detect encounter type (inpatient vs outpatient
   matters: it governs whether "probable / suspected" diagnoses are codable per
   ICD-10-CM Guideline IV.H), segment SOAP sections, window long multi-page
   notes with overlap, preserve **global character offsets**.
2. **Extract (LLM-A).** Returns `ExtractedFact[]` — verbatim span, normalized
   clinical term, **assertion status** (present / absent / possible /
   hypothetical / family / historical), kind (dx / px / symptom). A
   deterministic NegEx/ConText-style backstop overrules clear LLM polarity
   slips ("denies chest pain" must never be coded as active chest pain).
3. **Retrieve** — hybrid search per fact (see §2).
4. **Code (LLM-A).** Picks 1–N codes **only from the retrieved whitelist**, with
   verbalised confidence and a rationale that quotes the evidence span.
5. **Audit (LLM-B independent).** Re-reads each (evidence, code) pair against
   the cited evidence + code description and returns agree/disagree + note.
   *Selective + batched*: only procedures + low-confidence diagnoses go through
   the heavy auditor.
6. **Rules (deterministic).** Excludes1 conflicts, unspecified-when-specific,
   missing 7th character on injury/pregnancy chapters, evidence anchoring,
   procedure-without-supporting-diagnosis, format validity. Emits typed
   `Warning[]` (missing_information / ambiguity / conflict).
7. **Assemble (deterministic).** Blends and tiers the confidence (§3), builds
   the Pydantic-validated `CodingResult` and a `RunMetadata` envelope with
   `trace_id`, model snapshots, prompt version, config hash, and per-stage
   metrics.

# 2 · Code retrieval / filtering strategy

The single biggest failure mode for full-vocabulary ICD-10 coding is the LLM
**hallucinating non-existent codes** — across GPT-4/Gemini/Llama models, up to
35% of generated ICD-10 codes are non-billable or invalid (NEJM AI, 2024). We
eliminate this structurally: the LLM never free-generates a code.

For each extracted fact (using its `normalized_term` as the query):

- **Dense search** with `sentence-transformers/all-MiniLM-L6-v2` over a FAISS
  inner-product index (catches paraphrases — "DM type 2" finds "type 2
  diabetes mellitus"). Returns top-N=50.
- **Lexical BM25** over the same descriptions (catches exact clinical phrasing
  — "essential hypertension" matters word-for-word). Returns top-N=50.
- **Reciprocal Rank Fusion** (Cormack et al. 2009): each retriever contributes
  ``1 / (k + rank)``; fused scores are summed. RRF needs **no score calibration**
  between heterogeneous scorers — the empirically dominant hybrid fusion
  choice. Top-K=15 candidates become the **whitelist**.

That whitelist is a **hard constraint**, not soft context. The coder agent's
response is re-validated against the candidate set; any out-of-list code is
dropped and logged. This makes hallucinated codes *structurally impossible*.

**Data:** we bundle the **real CDC ICD-10-CM FY2027 catalog** (~74,879 codes,
US public domain) — using a synthetic ICD-10 catalog would dodge the
large-code-space challenge the exercise tests. CPT is **AMA-copyrighted with no
free tier**, so we ship a clearly-marked **synthetic CPT-shaped catalog** and
make licensed real CPT a one-config-line drop-in.

**Production swap (documented):** the same `Retriever` interface backs equally
well by **Postgres `pgvector` + `tsvector` + `pg_trgm`** — one datastore for
semantic + full-text + fuzzy in one operational footprint.

# 3 · LLM usage & prompting approach

Three role-specialized agents (mirroring the real-world coder → QA-auditor
workflow), all behind one **LiteLLM** Chat Completions gateway so providers (and
per-agent models) swap by env var:

| Agent       | Human analog    | Model (default)             | Constraint                          |
| ----------- | --------------- | --------------------------- | ----------------------------------- |
| Extraction  | clinical scribe | `openai/gpt-5.4-mini`       | reason-then-format; assertion regex |
| Coder       | medical coder   | `openai/gpt-5.4-mini`       | may only choose from whitelist      |
| **Auditor** | QA auditor      | `anthropic/claude-haiku-4-5-20251001` | **different model family** by default |

The **auditor defaulting to a different model family** is deliberate — research
shows heterogeneous verifiers cut correlated errors and self-preference bias
(arXiv 2410.21819; A-HMAD 2025). Same-model fallback is supported but flagged
as weaker. **Selective verification** (only procedures + low-confidence
diagnoses) and **batched calls** (one extract / one code / one audit per note)
keep the cost discipline reasonable.

**Prompting choices:**

- *Reason-then-format.* Strict JSON-only constraints degrade reasoning quality
  (arXiv 2408.02442). Prompts instruct the model to think internally first,
  then emit a single JSON object validated against a Pydantic schema. On
  validation failure we **repair-retry** once with the error appended to the
  conversation — almost always sufficient.
- *Versioned prompt files* (`prompts/extraction_p1.txt`, etc.). Prompt versions
  are part of the `config_hash` so a prompt change is visible in the audit log.
- *Pinned model IDs + bounded sampling* (e.g. `openai/gpt-5.4-mini`): `temp=0`
  where honoured (Claude); GPT-5 reasoning models reject it, so determinism rests
  on Structured Outputs + low `reasoning_effort` (hashed; self-consistency off).

**Confidence we surface ≠ raw LLM confidence.** Verbalised LLM confidence is
systematically overconfident (Xiong et al. 2023). We blend three signals —
retrieval rank (rank-aware, not raw RRF score), coder confidence (discounted),
and an auditor adjustment (+0.15 for agree, −0.30 for disagree) — and bin into
🟢 / 🟡 / 🔴 tiers using gold-tuned thresholds. (Formal isotonic/Platt
calibration is wired as an extension — needs a larger labelled set than the
demo gold supports.)

# 4 · Key decisions & trade-offs

| Decision                                            | Why                                                 | Trade-off accepted                     |
| --------------------------------------------------- | --------------------------------------------------- | -------------------------------------- |
| **Retrieve-then-constrain** (whitelist, not free generation) | Eliminates hallucinated codes; turns a 75k-way generation problem into a k-way selection (6% → ~100% on a comparable task — arXiv 2407.12849) | Bounded by **retriever recall@k** — the upstream recall ceiling on retrievable codes (not computed in the eval) |
| **Coder + independent Auditor** (multi-LLM)         | Best precision/recall on MIMIC-IV (MDPI Informatics 2026); heterogeneous verifiers cut correlated errors (A-HMAD 2025) | Extra LLM calls — mitigated by selective+batched verification |
| **Hybrid retrieval + RRF**                          | Exact terms *and* paraphrases; no score-scale tuning | Two indexes to build; ~1 minute on 75k codes |
| **Bounded 3-agent decomposition (no swarm)**        | MAST (NeurIPS 2025) shows speculative swarms add latency and "silent gray errors" without reliable accuracy gains | Foregoes ensemble-style accuracy gains for predictability |
| **Real ICD-10 + synthetic CPT**                     | Solves the brief's large-code-space challenge; legal under AMA licensing | CPT demo runs on synthetic codes |
| **LiteLLM** gateway                                 | Multi-provider in one call; built-in `mock_response` for keyless tests | Thin dependency |
| **temp=0 + pinned snapshots** over sampling         | Reproducibility / auditability is an explicit requirement | Foregoes ~1–3 pt accuracy from self-consistency (offered as optional) |
| **Deterministic rule engine** for hard checks       | Auditable, exact, no LLM cost                       | Full guideline coverage needs the ICD-10 tabular XML + CMS NCCI |
| **CLI-only core** (FastAPI/UI as extensions)        | Matches the offline brief; no over-build            | No reviewer UI — but the JSON contract supports override in-place |
| **Blended-then-tiered confidence**                  | Raw LLM confidence is systematically overconfident  | Calibration is gold-tuned, not formally calibrated (extension) |

# 5 · Limitations & extensions

**Limitations (honest).** *Assistive, not autonomous* — SOTA full-vocabulary
ICD-10 tops out around micro-F1 ≈ 0.54 (RAG-Coding, 2026); a human reviewer is
required by design and the payload (evidence spans, tiered confidence, mutable
reviewer fields) is shaped to make that review fast. *CPT is synthetic* —
real-CPT accuracy must be re-validated on a licensed catalog (architecture is
drop-in). *General-purpose embedder* (`all-MiniLM-L6-v2`) is a demo compromise;
production choice is biomedical (SapBERT / PubMedBERT). *Rule engine is a
curated subset* (format, billable, Excludes1 short list, 7th-character chapters,
dx↔px linkage, evidence anchoring); full guideline coverage needs the ICD-10
tabular XML + CMS NCCI refresh pipeline. *Confidence calibration* is
gold-tuned thresholds, not formal Platt / isotonic — needs a larger labelled
set. *Reproducibility* is engineered (temp=0, pinned dated snapshots, versioned
prompts, full audit log) but not bit-for-bit guaranteed across provider model
updates — exactly why we pin and log everything. *Evaluation* is illustrative
on a small authored gold set; the metric methodology (`scripts/evaluate.py`:
micro P/R/F1 for ICD and CPT, exact-match ratio, ICD-10-hierarchical micro-F1)
is correct; only the sample size is small.

**Extensions (designed for, not built).** Postgres hybrid retrieval
(`pgvector` + `tsvector` + `pg_trgm`); biomedical embeddings + SNOMED→ICD
crosswalk; full tabular-rule + NCCI engine; FastAPI + reviewer UI;
self-consistency confidence; AHIMA/ACDIS-compliant provider-query drafting;
licensed real CPT (one config line); LLM-observability tooling (Langfuse /
OpenTelemetry export via LiteLLM callbacks — opt-in env flag; Grafana +
Prometheus dashboards in production). Pipeline stages are idempotent and map
cleanly to **Airflow tasks** or **Celery jobs** for production orchestration.

**References (load-bearing).** Soroush et al. *LLMs Are Poor Medical Coders*
(NEJM AI 2024); *Code Like Humans* (EMNLP 2025, 2509.05378); MDPI Informatics
2026 (coder+auditor); 2407.12849 (retrieve-then-rerank); MAST (NeurIPS 2025);
Huang et al. *Can't Self-Correct Reasoning Yet* (ICLR 2024, 2310.01798);
Chain-of-Verification (2309.11495); Cormack et al. 2009 (RRF); 2408.02442
(JSON ≠ free-form); Xiong et al. 2306.13063 + Tian et al. 2305.14975
(confidence); ICD-10-CM Official Guidelines FY2026 (CMS/CDC); AMA CPT
licensing FAQ.
