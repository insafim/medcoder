# Annotated note — `note_03_inpatient_pneumonia_ambiguity`

> The clinical note with each suggested code shown inline at the evidence span that justifies it. «…» marks the evidence; 「code · system · tier · audit」 is the suggestion. **Legend:** 🟢 high · 🟡 medium · 🔴 low confidence; ✓ auditor agreed · ✗ disagreed · – not audited. The machine-readable record is `result.json`; the decision trail is `trace.json`.

- **Encounter:** inpatient  - **Trace:** `9bb0de03ba89`

```text
PATIENT: Samuel Okello (DOB 02/22/1949) DATE: 06/19/2026
ENCOUNTER: Inpatient admission, day 1
PROVIDER: Dr. L. Bianchi, MD

History and Physical / Admission Note:

Chief Complaint: «Productive cough, fever, dyspnea.»「R06.02 · ICD-10-CM · 🟢 high · –」

History of Present Illness:
77-year-old man with COPD on home oxygen 2 L/min, admitted via the emergency
department with 4 days of «productive cough»「R09.3 · ICD-10-CM · 🟢 high · –」, «subjective fevers to 38.7 C»「R50.9 · ICD-10-CM · 🟢 high · –」, and
«progressive dyspnea»「R06.02 · ICD-10-CM · 🟢 high · –」. He completed a 5-day course of azithromycin from urgent
care 3 days ago without improvement. He denies hemoptysis, chest pain, or recent
sick contacts. He lives alone and has had one fall in the past month.

Past Medical History:
- Chronic obstructive pulmonary disease (Gold stage III), on home oxygen.
- «Essential hypertension.»「I10 · ICD-10-CM · 🟢 high · –」
- History of smoking, 50 pack-years, quit 4 years ago.
- «Right hip osteoarthritis.»「M16.11 · ICD-10-CM · 🟢 high · –」

Physical Exam:
Temp 38.4 C, BP 132/78, HR 104, RR 24, SpO2 89% on 2 L (baseline 92%).
General: appears tired and tachypneic. Lungs: diminished breath sounds at the
right base with focal crackles; expiratory wheeze throughout. Cardiac: regular,
no murmurs. Extremities: no edema.

Imaging:
Chest X-ray two views: dense right lower lobe consolidation. No effusion.
No pneumothorax.

Laboratory:
WBC 16.2 K/uL with 88% neutrophils. Procalcitonin 1.8 ng/mL. BMP normal.

Assessment:
1. Community-acquired pneumonia, right lower lobe, probably bacterial — failed
 outpatient macrolide therapy. Atypical pathogen versus resistant typical.
2. Acute exacerbation of COPD, contributing to hypoxia.
3. Acute hypoxic respiratory failure.

The differential for the cough and fever included influenza and COVID-19; both
ruled out by negative combined rapid testing performed in the ED. Heart failure
considered but BNP within normal limits and no peripheral edema.

Plan:
- Admit to medical floor with telemetry.
- Empiric ceftriaxone plus doxycycline.
- Continue home oxygen, titrate to SpO2 ≥ 92%.
- Nebulizer treatment with albuterol/ipratropium every 4 hours.
- Pulse oximetry continuous.
- Repeat chest X-ray in 48 hours.

Signed,
L. Bianchi, MD
```

## Unanchored codes

_Suggested, but their evidence span could not be placed inline (offset drift or overlap) — see `result.json` for the full record._

- 「J44.1 · ICD-10-CM · 🟢 high · – + J96.01 · ICD-10-CM · 🟢 high · – + J15.9 · ICD-10-CM · 🟢 high · – + 9R0011 · CPT · 🟢 high · ✓ + 9P0020 · CPT · 🟢 high · ✓ + 9E0011 · CPT · 🟢 high · ✓」 — evidence: "Acute exacerbation of COPD"
