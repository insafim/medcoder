# Coding review — `note_04_multipage_postop`

- **Encounter:** inpatient  - **Trace:** `1a95bdfd05c8`  - **Config:** `3bee7eea3e0cee68`

- **Latency:** 30259 ms  - **Cost:** $0.0309  - **Models:** extraction=openai/gpt-5.4-mini, coder=openai/gpt-5.4-mini, auditor=anthropic/claude-haiku-4-5-20251001


## Diagnoses (ICD-10-CM)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `E11.9` | Type 2 diabetes mellitus without complications | 0.99 (high) | "Type 2 diabetes mellitus, currently well-controlled" | – skipped |
| ☐ | `G43.009` | Migraine without aura, not intractable, without status migrainosus | 0.99 (high) | "Migraine without aura." | – skipped |
| ☐ | `G89.18` | Other acute postprocedural pain | 0.99 (high) | "Pain, post-procedural, controlled." | – skipped |
| ☐ | `E66.811` | Obesity, class 1 | 0.83 (high) | "Obesity, BMI 33." | – skipped |
| ☐ | `K80.00` | Calculus of gallbladder with acute cholecystitis without obstruction | 0.74 (medium) | "acute calculous cholecystitis" | – skipped |
| ☐ | `Z48.89` | Encounter for other specified surgical aftercare | 0.67 (medium) | "Status post laparoscopic cholecystectomy for acute calculous cholecystitis" | – skipped |
| ☐ | `G89.18` | Other acute postprocedural pain | 0.59 (medium) | "incisional pain" | – skipped |


## Procedures (CPT)

| Accept? | Code | Description | Confidence | Evidence | Audit |
| :-----: | ---- | ----------- | ---------- | -------- | ----- |
| ☐ | `9S0010` | [SYNTHETIC] Laparoscopic cholecystectomy without exploration | 1.00 (high) | "laparoscopic cholecystectomy" | ✓ agree |
| ☐ | `9R0070` | [SYNTHETIC] Ultrasound abdomen complete real-time with image documentation | 1.00 (high) | "Abdominal ultrasound" | ✓ agree |


## Warnings

- **[INFO] ambiguity** — Fact 'nausea' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'vomiting' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'chest pain' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'fever' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'chills' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'dyspnea' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'leg swelling' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'type 2 diabetes mellitus' dropped from coding (assertion=historical); retained as context only.
- **[INFO] ambiguity** — Fact 'prior abdominal surgery' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'bile leak' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'postoperative ileus' dropped from coding (assertion=absent); retained as context only.
- **[INFO] ambiguity** — Fact 'venous thromboembolism' dropped from coding (assertion=absent); retained as context only.


> Reviewer: tick **Accept?** to confirm a suggestion, or strike it and write the correct code. JSON (`result.json`) and the audit trail (`trace.json`) carry the full machine-readable record.
