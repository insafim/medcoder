"""Shared test fixtures.

Tests never hit a real LLM provider — every test that exercises an agent passes
canned ``mock_response`` JSON strings down through the pipeline. The cache
directory is redirected to a tmp path so cache hits/misses don't bleed between
tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Disable LiteLLM debug logs before anything imports it.
os.environ.setdefault("LITELLM_LOG", "ERROR")

from medcoder.config import get_settings  # noqa: E402
from medcoder.llm import downgrade_logger_for_tests  # noqa: E402
from medcoder.logging_setup import configure_logging  # noqa: E402

downgrade_logger_for_tests()


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Each test gets its own LLM response cache directory."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("MEDCODER_CACHE_DIR", str(cache_dir))
    s = get_settings(refresh=True)
    s.cache_dir = cache_dir
    yield
    # tmp_path teardown is automatic


@pytest.fixture(scope="session", autouse=True)
def _logging_once():
    configure_logging(level="WARNING", json_mode=False)


# ----- canned mock responses ----------------------------------------------


def fact_payload(
    *,
    text: str,
    normalized_term: str,
    start: int,
    end: int,
    status: str = "present",
    kind: str = "diagnosis",
    section: str | None = "assessment",
) -> dict:
    return {
        "text": text,
        "normalized_term": normalized_term,
        "assertion_status": status,
        "start_offset": start,
        "end_offset": end,
        "section": section,
        "kind": kind,
    }


@pytest.fixture
def mock_extraction_one_dx():
    """One present-status diagnosis, one negated finding, one family history.

    The pipeline should code only the present one.
    """
    note = "Type 2 diabetes mellitus. Denies chest pain. Mother had stroke."

    facts = [
        fact_payload(
            text="Type 2 diabetes mellitus", normalized_term="type 2 diabetes mellitus",
            start=note.find("Type 2"), end=note.find("Type 2") + len("Type 2 diabetes mellitus"),
            kind="diagnosis", status="present",
        ),
        fact_payload(
            text="chest pain", normalized_term="chest pain",
            start=note.find("chest pain"), end=note.find("chest pain") + len("chest pain"),
            kind="symptom", status="absent",
        ),
        fact_payload(
            text="stroke", normalized_term="stroke",
            start=note.find("stroke"), end=note.find("stroke") + len("stroke"),
            kind="diagnosis", status="family",
        ),
    ]
    return note, json.dumps({"facts": facts})


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]
