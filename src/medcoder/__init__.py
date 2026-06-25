"""medcoder — auditable medical-coding pipeline.

Public entry point: :func:`medcoder.pipeline.run` — feed it a clinical note,
get back a Pydantic-validated :class:`medcoder.schemas.CodingResult` with
ICD-10 + (synthetic) CPT suggestions, evidence spans, confidence tiers, and
warnings.

See ``docs/DESIGN.md`` for the full architecture and ``README.md`` for quickstart.
"""
