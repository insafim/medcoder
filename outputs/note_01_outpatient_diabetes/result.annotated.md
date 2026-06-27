# Annotated note — `note_01_outpatient_diabetes`

> The clinical note with each suggested code shown inline at the evidence span that justifies it. «…» marks the evidence; 「code · system · tier · audit」 is the suggestion. **Legend:** 🟢 high · 🟡 medium · 🔴 low confidence; ✓ auditor agreed · ✗ disagreed · – not audited. The machine-readable record is `result.json`; the decision trail is `trace.json`.

- **Encounter:** outpatient  - **Trace:** `a94f8d732eba`

```text
PATIENT: Jordan Reyes (DOB 04/12/1968) DATE: 06/14/2026
ENCOUNTER: Outpatient — Primary Care Follow-Up
PROVIDER: Dr. M. Patel, MD

Subjective:
Mr. Reyes returns for routine follow-up of «type 2 diabetes mellitus»「E11.9 · ICD-10-CM · 🟢 high · –」 and «essential
hypertension.»「I10 · ICD-10-CM · 🟢 high · –」 He reports adherence to metformin 1000 mg BID and lisinopril 20 mg
daily. He denies chest pain, shortness of breath, polyuria, or visual changes.
He notes mild bilateral foot numbness over the last 3 months, particularly at
night. No falls. No new wounds. Mother had type 2 diabetes mellitus and died of a
myocardial infarction at age 71; father with hypertension. No personal history of
stroke or MI.

Objective:
BP 138/86, HR 76, BMI 31.4. «Comprehensive diabetic foot exam performed:»「9T0012 · CPT · 🟢 high · ✓」
monofilament sensation reduced in both feet at three of ten test sites, pedal
pulses 2+ bilaterally, no ulcerations, no callosities, normal capillary refill.
Recent labs: A1C 8.4%, eGFR 76, urine microalbumin elevated at 78 mg/g.

Assessment:
1. «Type 2 diabetes mellitus with diabetic polyneuropathy, with documented
 sensory deficits on monofilament testing — A1C above goal.»「E11.42 · ICD-10-CM · 🟢 high · –」
2. Essential hypertension, not at goal (BP 138/86).
3. «Diabetic nephropathy, early — microalbuminuria.»「E11.21 · ICD-10-CM · 🟢 high · –」
4. «Obesity, BMI 31.4.»「E66.811 · ICD-10-CM · 🟢 high · –」

Plan:
- Increase metformin to maximum tolerated dose; consider GLP-1 agonist add-on if
 A1C remains > 7.5% at next visit.
- Continue lisinopril; recheck BP at 4-week telephone visit.
- Diabetes self-management education referral.
- Comprehensive diabetic foot examination performed today (see Objective).
- Return to clinic in 3 months with A1C, BMP, and urine microalbumin.

Signed,
M. Patel, MD
```
