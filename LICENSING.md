# Licensing & data provenance

This repository contains code (MIT) and three data artifacts with distinct licensing.

## ICD-10-CM (real)

- **Source:** CDC / NCHS, ICD-10-CM FY2026 code descriptions file
  (`icd10cm-codes-2026.txt`).
- **License:** US Government public domain. No restriction on redistribution.
- **Bundled?** The file is downloaded by `make build-index` (or
  `scripts/build_index.py --download`). It is git-ignored so a fresh clone
  always pulls the upstream copy and stays current with revisions.

## CPT (synthetic — *not* real CPT)

- **Why not real CPT?** CPT codes and descriptors are copyrighted by the
  American Medical Association (AMA). The AMA has no free public-use tier;
  embedding real CPT codes in this repository would violate their license.
- **What we ship:** `data/catalogs/procedures_synthetic.csv` — clearly
  *fictitious*, CPT-shaped (5-digit) codes that exercise the same retrieval
  and rule paths. Codes intentionally start with `9` to make their synthetic
  origin obvious and to avoid collision with real CPT ranges in casual review.
- **Production swap:** licensed real CPT drops in by pointing
  `MEDCODER_CPT_CATALOG` at the licensed file (same `code,description` shape).

## Clinical notes (synthetic — authored)

- **Why not MIMIC / n2c2 / MTSamples?** Each carries a DUA or
  PHI / redistribution restriction.
- **What we ship:** `data/notes/*.txt` are entirely authored by us. They are
  fictitious clinical narratives written specifically to exercise the
  pipeline's behaviors (multi-page handling, negation, ambiguity, conflict).
  No PHI, no DUA.

## Code

MIT — see header comments. Third-party dependencies retain their own licenses.
