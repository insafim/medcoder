"""Deterministic rule engine — the symbolic post-constraint.

Implements the subset of ICD-10-CM official-guideline checks doable from the
bundled `icd10cm_codes_*.txt`:
  - format / exists in catalog
  - unspecified-laterality flag (heuristic on description)
  - missing 7th-character flag (categories that require it)
  - evidence-anchor check (every code must have at least one fact)
  - dx ↔ px linkage (every procedure should have a supporting dx)
  - Excludes1-like conflict pairs (curated short list — full graph needs the
    ICD-10 tabular XML, documented as an extension in Plan.md §9.6)

Output is a list of typed Warnings; the pipeline collects them into the
CodingResult envelope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .code_assign import CodedAssignment
from .schemas import CodeSystem, Warning, WarningSeverity, WarningType

# ----------------------------------------------------------------------------
# Format / catalog
# ----------------------------------------------------------------------------

_ICD10_FORMAT = re.compile(r"^[A-Z][0-9][0-9A-Z](\.?[0-9A-Z]{1,4})?$")
_CPT_FORMAT = re.compile(r"^[A-Z0-9-]{4,8}$")  # broad: catches both real CPT and our synthetic shape


def _format_ok(code: str, system: CodeSystem) -> bool:
    if system == CodeSystem.ICD10:
        return bool(_ICD10_FORMAT.match(code))
    if system == CodeSystem.CPT:
        return bool(_CPT_FORMAT.match(code))
    return False


# ----------------------------------------------------------------------------
# Laterality / specificity heuristics
# ----------------------------------------------------------------------------

_UNSPECIFIED_HINTS = ("unspecified",)
_LATERALITY_HINTS = ("right", "left", "bilateral", "unspecified side")


def _is_unspecified(description: str) -> bool:
    d = description.lower()
    return any(h in d for h in _UNSPECIFIED_HINTS)


# ----------------------------------------------------------------------------
# 7th character (injury / pregnancy / external cause chapters)
# ----------------------------------------------------------------------------

# Categories where a 7th-character extension is generally required.
# This is the well-known short list — Plan.md §9.6 notes that complete
# coverage needs the tabular XML.
_SEVENTH_CHAR_PREFIXES = ("S", "T", "M48.4", "M48.5", "M84.3", "M84.4", "M84.5", "M84.6", "O")


def _needs_seventh_char(code: str) -> bool:
    bare = code.replace(".", "")
    if not bare:
        return False
    return any(code.startswith(p) for p in _SEVENTH_CHAR_PREFIXES)


def _has_seventh_char(code: str) -> bool:
    bare = code.replace(".", "")
    return len(bare) >= 7


# ----------------------------------------------------------------------------
# Excludes1-like curated pairs
# ----------------------------------------------------------------------------

# Each pair is (prefix_a, prefix_b, reason). If both a code starting with
# prefix_a AND one with prefix_b are assigned, we surface a conflict warning.
# This is a small curated subset — see Plan.md §9.6 for the full-tabular extension.
_EXCLUDES1_PAIRS: list[tuple[str, str, str]] = [
    (
        "E10",
        "E11",
        "Type 1 (E10.*) and Type 2 (E11.*) diabetes mellitus are mutually exclusive (Excludes1).",
    ),
    (
        "I10",
        "I11",
        "Essential hypertension (I10) is Excludes1 with hypertensive heart disease (I11.*).",
    ),
    (
        "J44",
        "J45",
        "COPD (J44.*) and asthma (J45.*) coding together should be reviewed — see Excludes1 guidance.",
    ),
]


def _excludes1_warnings(codes: list[str]) -> list[Warning]:
    out: list[Warning] = []
    for a, b, reason in _EXCLUDES1_PAIRS:
        has_a = [c for c in codes if c.startswith(a)]
        has_b = [c for c in codes if c.startswith(b)]
        if has_a and has_b:
            out.append(
                Warning(
                    type=WarningType.CONFLICT,
                    severity=WarningSeverity.WARN,
                    message=reason,
                    refs=sorted(set(has_a + has_b)),
                )
            )
    return out


# ----------------------------------------------------------------------------
# Top-level
# ----------------------------------------------------------------------------


@dataclass
class RuleContext:
    diagnoses: list[CodedAssignment]
    procedures: list[CodedAssignment]


def evaluate(ctx: RuleContext) -> list[Warning]:
    """Apply every deterministic edit check to ``ctx`` and return a flat list of
    typed Warnings (missing_information / ambiguity / conflict)."""
    warnings: list[Warning] = []

    all_assignments = ctx.diagnoses + ctx.procedures

    # --- per-assignment checks ---------------------------------------------
    for a in all_assignments:
        code = a.candidate.code
        sys = a.candidate.system

        if not _format_ok(code, sys):
            warnings.append(
                Warning(
                    type=WarningType.CONFLICT,
                    severity=WarningSeverity.BLOCK,
                    message=f"Code {code!r} is not a valid {sys.value} format.",
                    refs=[code],
                )
            )
            continue  # don't run other checks on a structurally invalid code

        if not a.fact or not a.fact.text:
            warnings.append(
                Warning(
                    type=WarningType.MISSING_INFORMATION,
                    severity=WarningSeverity.WARN,
                    message=f"Code {code} has no anchored evidence span.",
                    refs=[code],
                )
            )

        if _is_unspecified(a.candidate.description) and a.choice.confidence < 0.9:
            warnings.append(
                Warning(
                    type=WarningType.MISSING_INFORMATION,
                    severity=WarningSeverity.INFO,
                    message=(
                        f"Code {code} is 'unspecified' — verify the note does not document a "
                        "more specific variant (laterality, type, acuity)."
                    ),
                    refs=[code],
                )
            )

        if sys == CodeSystem.ICD10 and _needs_seventh_char(code) and not _has_seventh_char(code):
            warnings.append(
                Warning(
                    type=WarningType.MISSING_INFORMATION,
                    severity=WarningSeverity.WARN,
                    message=(
                        f"Code {code} appears to require a 7th-character extension "
                        "(initial/subsequent/sequela). Reviewer should confirm."
                    ),
                    refs=[code],
                )
            )

    # --- pairwise: Excludes1 conflicts -------------------------------------
    icd_codes = [a.candidate.code for a in ctx.diagnoses]
    warnings.extend(_excludes1_warnings(icd_codes))

    # --- dx ↔ px linkage (medical necessity) -------------------------------
    if ctx.procedures and not ctx.diagnoses:
        warnings.append(
            Warning(
                type=WarningType.MISSING_INFORMATION,
                severity=WarningSeverity.WARN,
                message=(
                    "Procedures coded with no supporting diagnoses — verify medical-necessity "
                    "documentation before submission."
                ),
                refs=[a.candidate.code for a in ctx.procedures],
            )
        )

    return warnings
