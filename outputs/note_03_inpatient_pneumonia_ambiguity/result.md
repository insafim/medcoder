# Coding review — `note_03_inpatient_pneumonia_ambiguity`

- **Encounter:** inpatient  - **Trace:** `9bb0de03ba89`  - **Config:** `3bee7eea3e0cee68`

- **Latency:** 46082 ms  - **Cost:** $0.0431  - **Models:** extraction=openai/gpt-5.4-mini, coder=openai/gpt-5.4-mini, auditor=anthropic/claude-haiku-4-5-20251001


## Diagnoses (ICD-10-CM)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `J44.1` | Chronic obstructive pulmonary disease with (acute) exacerbation | 1.00 (high) | "Acute exacerbation of COPD" | – skipped |
| ☐ | `J96.01` | Acute respiratory failure with hypoxia | 1.00 (high) | "Acute hypoxic respiratory failure" | – skipped |
| ☐ | `I10` | Essential (primary) hypertension | 1.00 (high) | "Essential hypertension." | – skipped |
| ☐ | `M16.11` | Unilateral primary osteoarthritis, right hip | 0.99 (high) | "Right hip osteoarthritis." | – skipped |
| ☐ | `R06.02` | Shortness of breath | 0.91 (high) | "progressive dyspnea" | – skipped |
| ☐ | `R06.02` | Shortness of breath | 0.89 (high) | "Productive cough, fever, dyspnea." | – skipped |
| ☐ | `J15.9` | Unspecified bacterial pneumonia | 0.87 (high) | "Community-acquired pneumonia, right lower lobe, probably bacterial" | – skipped |
| ☐ | `R50.9` | Fever, unspecified | 0.85 (high) | "subjective fevers to 38.7 C" | – skipped |
| ☐ | `R09.3` | Abnormal sputum | 0.82 (high) | "productive cough" | – skipped |


## Procedures (CPT)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `9R0011` | [SYNTHETIC] Radiologic examination chest two views frontal and lateral | 1.00 (high) | "Chest X-ray two views" | ✓ agree |
| ☐ | `9P0020` | [SYNTHETIC] Nebulizer treatment for the administration of an inhalation solution | 1.00 (high) | "Nebulizer treatment with albuterol/ipratropium every 4 hours." | ✓ agree |
| ☐ | `9E0011` | [SYNTHETIC] Hospital inpatient or observation care - initial - high complexity | 0.97 (high) | "Admit to medical floor with telemetry." | ✓ agree |


## Warnings

- **[INFO] ambiguity** — Fact 'influenza' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'COVID-19' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'hemoptysis' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'chest pain' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'recent sick contacts' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'fall' dropped from coding (assertion=historical); retained as context only.
- **[INFO] ambiguity** — Fact 'chronic obstructive pulmonary disease' dropped from coding (assertion=historical); retained as context only.
- **[INFO] ambiguity** — Fact 'history of smoking' dropped from coding (assertion=historical); retained as context only.


> Reviewer: tick **Accept?** to confirm a suggestion, or strike it and write the correct code. JSON (`result.json`) and the audit trail (`trace.json`) carry the full machine-readable record.
