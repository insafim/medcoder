"""Versioned prompts — loaded at import time and exposed as constants.

A version bump is part of `config_hash` so a prompt change shows up in run audit.
"""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def _load(name: str) -> str:
    return (_DIR / name).read_text().strip()


EXTRACTION_SYSTEM = _load("extraction_p1.txt")
CODER_SYSTEM = _load("coder_p1.txt")
AUDITOR_SYSTEM = _load("auditor_p1.txt")
