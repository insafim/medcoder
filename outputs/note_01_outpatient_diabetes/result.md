# Coding review — `note_01_outpatient_diabetes`

- **Encounter:** outpatient  - **Trace:** `a94f8d732eba`  - **Config:** `3bee7eea3e0cee68`

- **Latency:** 63446 ms  - **Cost:** $0.0393  - **Models:** extraction=openai/gpt-5.4-mini, coder=openai/gpt-5.4-mini, auditor=anthropic/claude-haiku-4-5-20251001


## Diagnoses (ICD-10-CM)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `I10` | Essential (primary) hypertension | 1.00 (high) | "essential hypertension." | – skipped |
| ☐ | `E11.42` | Type 2 diabetes mellitus with diabetic polyneuropathy | 1.00 (high) | "Type 2 diabetes mellitus with diabetic polyneuropathy, with documented  sensory ..." | – skipped |
| ☐ | `E11.9` | Type 2 diabetes mellitus without complications | 0.90 (high) | "type 2 diabetes mellitus" | – skipped |
| ☐ | `E11.21` | Type 2 diabetes mellitus with diabetic nephropathy | 0.85 (high) | "Diabetic nephropathy, early — microalbuminuria." | – skipped |
| ☐ | `E66.811` | Obesity, class 1 | 0.84 (high) | "Obesity, BMI 31.4." | – skipped |


## Procedures (CPT)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `9T0012` | [SYNTHETIC] Comprehensive diabetic foot examination | 1.00 (high) | "Comprehensive diabetic foot exam performed:" | ✓ agree |


## Warnings

- **[INFO] ambiguity** — Fact 'chest pain' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'shortness of breath' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'polyuria' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'visual changes' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'myocardial infarction' dropped from coding (assertion=family); retained as context only.
- **[INFO] ambiguity** — Fact 'stroke' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'myocardial infarction' dropped from coding (assertion=absent); retained as context only.


> Reviewer: tick **Accept?** to confirm a suggestion, or strike it and write the correct code. JSON (`result.json`) and the audit trail (`trace.json`) carry the full machine-readable record.
