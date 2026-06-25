"""Catalog loaders for ICD-10-CM (real) and CPT (synthetic)."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..schemas import CodeSystem


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    code: str
    system: CodeSystem
    description: str


def _canonicalize_icd10(code: str) -> str:
    """Insert the decimal point after the 3-char category (CMS files omit it).

    "E1142" → "E11.42"; codes already in dotted form pass through unchanged.
    """
    if "." in code or len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


def load_icd10(path: Path) -> list[CatalogEntry]:
    """Load the CDC FY2026/FY2027 ``icd10cm_codes_*.txt`` whitespace file.

    File shape: ``<code>   <description>`` per line (variable whitespace gap).
    CMS distributes codes in no-dot form ("E1142"); we normalise to the dotted
    form ("E11.42") that reviewers and downstream rule checks expect.
    """
    entries: list[CatalogEntry] = []
    with path.open() as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            code, desc = parts[0].strip(), parts[1].strip()
            if not code or not desc:
                continue
            entries.append(
                CatalogEntry(
                    code=_canonicalize_icd10(code),
                    system=CodeSystem.ICD10,
                    description=desc,
                )
            )
    return entries


def load_cpt(path: Path) -> list[CatalogEntry]:
    """Load the synthetic CPT CSV (`code,description`)."""
    entries: list[CatalogEntry] = []
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("code") or "").strip()
            desc = (row.get("description") or "").strip()
            if not code or not desc:
                continue
            entries.append(CatalogEntry(code=code, system=CodeSystem.CPT, description=desc))
    return entries


def to_dict(entries: Iterable[CatalogEntry]) -> dict[str, CatalogEntry]:
    return {e.code: e for e in entries}
