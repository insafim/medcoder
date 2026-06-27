# Annotated note — `note_02_ed_chest_pain`

> The clinical note with each suggested code shown inline at the evidence span that justifies it. «…» marks the evidence; 「code · system · tier · audit」 is the suggestion. **Legend:** 🟢 high · 🟡 medium · 🔴 low confidence; ✓ auditor agreed · ✗ disagreed · – not audited. The machine-readable record is `result.json`; the decision trail is `trace.json`.

- **Encounter:** outpatient  - **Trace:** `62a7d0653e53`

```text
PATIENT: Priya Lange (DOB 11/03/1957) DATE: 06/18/2026
ENCOUNTER: Emergency Department visit
PROVIDER: Dr. R. Okafor, MD

Chief Complaint:
«Acute substernal chest pain, 3 hours.»「R07.89 · ICD-10-CM · 🟢 high · –」

History of Present Illness:
67-year-old woman with history of essential hypertension and «hyperlipidemia»「E78.5 · ICD-10-CM · 🟢 high · –」
presents with 3 hours of «substernal chest pressure radiating to the left arm»「R07.89 · ICD-10-CM · 🟢 high · –」,
associated with diaphoresis and «mild nausea»「R11.0 · ICD-10-CM · 🟢 high · –」. Pain rated 7/10, not relieved with
sublingual nitroglycerin given by EMS. She denies palpitations, syncope, recent
fevers, leg swelling, or recent travel. No prior history of myocardial
infarction. Family history: father with MI at 58.

Objective:
BP 156/92, HR 102, SpO2 97% on room air. Patient appears uncomfortable, diaphoretic.
Cardiac exam: regular rhythm, no murmurs. Lungs clear. No leg swelling.

Results:
- 12-lead EKG: ST-segment elevations 2 mm in leads V2-V4, reciprocal changes
 in inferior leads.
- Troponin I: 0.34 ng/mL (elevated, reference < 0.04).
- Chest X-ray two views: no acute infiltrate, no pneumothorax.

Assessment:
Acute ST-elevation myocardial infarction, anterior wall. Differential considered
and excluded: pulmonary embolism (no risk factors, vital signs and chest X-ray
not consistent), aortic dissection (no tearing pain, equal pulses).

Plan:
1. Activate cardiac catheterization lab.
2. Aspirin 325 mg chewed; loading dose of P2Y12 inhibitor administered.
3. Heparin per protocol.
4. Patient transferred to cath lab for «percutaneous coronary intervention.»「9C0041 · CPT · 🟡 medium · ✗」
5. Admit to cardiac care unit post-procedure.

Procedures performed in ED prior to transfer:
- Routine 12-lead electrocardiogram with interpretation.
- «Two-view chest radiograph.»「9R0011 · CPT · 🟢 high · ✓」
- «Venipuncture for laboratory studies including troponin.»「9V0010 · CPT · 🟢 high · ✓」

Signed,
R. Okafor, MD
```
