# Annotated note — `note_04_multipage_postop`

> The clinical note with each suggested code shown inline at the evidence span that justifies it. «…» marks the evidence; 「code · system · tier · audit」 is the suggestion. **Legend:** 🟢 high · 🟡 medium · 🔴 low confidence; ✓ auditor agreed · ✗ disagreed · – not audited. The machine-readable record is `result.json`; the decision trail is `trace.json`.

- **Encounter:** inpatient  - **Trace:** `1a95bdfd05c8`

```text
PATIENT: Elena Park (DOB 09/15/1982) DATE: 06/20/2026
ENCOUNTER: Inpatient — Day 2 of post-operative course
PROVIDER: Dr. K. Singh, MD

==== PAGE 1 ====

Subjective:
43-year-old woman post-operative day 2 from «laparoscopic cholecystectomy»「9S0010 · CPT · 🟢 high · ✓」
performed on 06/18/2026 for symptomatic cholelithiasis with acute calculous
cholecystitis. Reports «incisional pain»「G89.18 · ICD-10-CM · 🟡 medium · –」 controlled on oral acetaminophen with
oxycodone PRN. Tolerating a regular diet without nausea or vomiting. Bowels
have moved overnight. She denies fever, chills, shortness of breath, or chest
pain. No leg swelling.

Past Medical History:
- Type 2 diabetes mellitus, well-controlled on metformin, A1C 6.8% three months
 ago.
- «Obesity, BMI 33.»「E66.811 · ICD-10-CM · 🟢 high · –」
- «Migraine without aura.»「G43.009 · ICD-10-CM · 🟢 high · –」
- No prior abdominal surgeries.

Past Surgical History:
- Laparoscopic cholecystectomy 06/18/2026 (this admission).

==== PAGE 2 ====

Objective:
Vitals: Temp 36.9 C, BP 124/78, HR 82, RR 16, SpO2 98% RA.
General: alert, comfortable, ambulatory in the hallway with a steady gait.
Abdomen: soft, non-distended; surgical port sites clean, dry, and intact; no
erythema or drainage. Bowel sounds normoactive. Lungs clear bilaterally.
Cardiac regular. Extremities: no calf tenderness, no edema.

Recent Labs (06/20/2026 morning):
- CBC: WBC 8.4 K/uL (was 12.1 on admission), Hgb 12.6, Plt 240.
- BMP: Na 138, K 4.1, Cr 0.78, glucose 124.
- Liver function tests: AST 28, ALT 31, total bilirubin 0.6 — improved from
 pre-op (T.bili 2.4).

Imaging: none today. Operative ultrasound on admission documented gallbladder
wall thickening with multiple stones, consistent with acute cholecystitis.

Assessment:
1. Status post laparoscopic cholecystectomy for «acute calculous cholecystitis»「K80.00 · ICD-10-CM · 🟡 medium · –」 —
 tolerating recovery well, afebrile, advancing diet, mobilizing.
2. «Type 2 diabetes mellitus, currently well-controlled»「E11.9 · ICD-10-CM · 🟢 high · –」; glucose 124 this morning.
3. Obesity (BMI 33) — discussed peri-operative weight management.
4. «Pain, post-procedural, controlled.»「G89.18 · ICD-10-CM · 🟢 high · –」

Considered but excluded:
- Bile leak: no abdominal pain out of proportion, normal LFTs trending down,
 no fever — clinically excluded.
- Post-operative ileus: bowel function returned, tolerating diet.
- Venous thromboembolism: ambulating, no calf signs, on mechanical prophylaxis.

Plan:
- Discharge home today if no new issues at afternoon reassessment.
- Continue oral analgesics, transition to acetaminophen-only by post-op day 5.
- Resume metformin at home dose.
- Outpatient follow-up with surgery clinic in 2 weeks; PCP in 4 weeks for
 diabetes recheck (A1C and BMP).
- Patient educated on signs of infection, bile leak, and DVT requiring re-presentation.

Procedures performed during this admission (referenced for coding):
- Laparoscopic cholecystectomy on 06/18/2026 (primary procedure).
- «Abdominal ultrasound»「9R0070 · CPT · 🟢 high · ✓」 at admission.
- Comprehensive metabolic panel on admission, hospital day 1, and today.

Signed,
K. Singh, MD
```

## Unanchored codes

_Suggested, but their evidence span could not be placed inline (offset drift or overlap) — see `result.json` for the full record._

- 「Z48.89 · ICD-10-CM · 🟡 medium · –」 — evidence: "Status post laparoscopic cholecystectomy for acute calculous cholecystitis"
