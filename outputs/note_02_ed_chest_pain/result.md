# Coding review — `note_02_ed_chest_pain`

- **Encounter:** outpatient  - **Trace:** `62a7d0653e53`  - **Config:** `3bee7eea3e0cee68`

- **Latency:** 12877 ms  - **Cost:** $0.0178  - **Models:** extraction=openai/gpt-5.4-mini, coder=openai/gpt-5.4-mini, auditor=anthropic/claude-haiku-4-5-20251001


## Diagnoses (ICD-10-CM)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `R11.0` | Nausea | 0.99 (high) | "mild nausea" | – skipped |
| ☐ | `R07.89` | Other chest pain | 0.96 (high) | "Acute substernal chest pain, 3 hours." | – skipped |
| ☐ | `R07.89` | Other chest pain | 0.88 (high) | "substernal chest pressure radiating to the left arm" | – skipped |
| ☐ | `E78.5` | Hyperlipidemia, unspecified | 0.86 (high) | "hyperlipidemia" | – skipped |


## Procedures (CPT)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `9V0010` | [SYNTHETIC] Venipuncture for collection of specimen routine | 1.00 (high) | "Venipuncture for laboratory studies including troponin." | ✓ agree |
| ☐ | `9R0011` | [SYNTHETIC] Radiologic examination chest two views frontal and lateral | 0.95 (high) | "Two-view chest radiograph." | ✓ agree |
| ☐ | `9C0041` | [SYNTHETIC] Percutaneous coronary intervention single vessel with stent placement | 0.55 (medium) | "percutaneous coronary intervention." | ✗ disagree |


## Warnings

- **[INFO] ambiguity** — Fact 'essential hypertension' dropped from coding (assertion=historical); retained as context only.
- **[INFO] ambiguity** — Fact 'myocardial infarction' dropped from coding (assertion=family); retained as context only.
- **[INFO] ambiguity** — Fact 'myocardial infarction' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'acute ST-elevation myocardial infarction' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'pulmonary embolism' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'aortic dissection' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'electrocardiogram' dropped from coding (assertion=historical); retained as context only.
- **[INFO] missing_information** — Code E78.5 is 'unspecified' — verify the note does not document a more specific variant (laterality, type, acuity).
- **[WARN] ambiguity** — Auditor disagreed with code 9C0041: The note documents only that the patient was 'transferred to cath lab for percutaneous coronary intervention' but does not specify vessel count or stent placement; the code asserts single-vessel PCI with stent, which exceeds the documented specificity.


> Reviewer: tick **Accept?** to confirm a suggestion, or strike it and write the correct code. JSON (`result.json`) and the audit trail (`trace.json`) carry the full machine-readable record.
