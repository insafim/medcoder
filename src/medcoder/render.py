"""Human-readable Markdown rendering of a `CodingResult`.

JSON is the correct *structured payload* for machines and audit, but it is not
pleasant for a human coder to read. This renderer produces the same data as a
review sheet: each suggested code with its confidence tier, the verbatim
evidence quote, the auditor verdict, and an accept/override column the reviewer
can fill in. JSON and Markdown are two views of one payload — neither replaces
the other (`medcoder run --format md`).
"""

from __future__ import annotations

from .schemas import CodeSuggestion, CodingResult

_AUDIT_GLYPH = {True: "✓ agree", False: "✗ disagree", None: "– skipped"}


def _evidence_quote(s: CodeSuggestion) -> str:
    """First evidence span, quoted and truncated to 80 chars for table readability."""
    if not s.evidence:
        return ""
    text = s.evidence[0].text.replace("\n", " ").strip()
    return f'"{text[:80]}..."' if len(text) > 80 else f'"{text}"'


def _suggestion_rows(suggestions: list[CodeSuggestion]) -> str:
    """Render suggestions as a Markdown table — one row each, with an Accept? column."""
    if not suggestions:
        return "_None suggested._\n"
    lines = [
        "| Accept? | Code | Description | Confidence | Evidence | Audit |",
        "| :-----: | ---- | ----------- | ---------- | -------- | ----- |",
    ]
    for s in suggestions:
        conf = f"{s.confidence:.2f} ({s.confidence_tier.value})"
        desc = s.description.replace("|", "\\|")
        evidence = _evidence_quote(s).replace("|", "\\|")
        audit = _AUDIT_GLYPH[s.audit_agree]
        lines.append(f"| ☐ | `{s.code}` | {desc} | {conf} | {evidence} | {audit} |")
    return "\n".join(lines) + "\n"


def render_markdown(result: CodingResult) -> str:
    """Render a `CodingResult` as a reviewer-facing Markdown sheet."""
    m = result.metadata
    out: list[str] = []
    out.append(f"# Coding review — `{result.document_id}`\n")
    out.append(
        f"- **Encounter:** {m.encounter_type.value}  "
        f"- **Trace:** `{m.trace_id}`  "
        f"- **Config:** `{m.config_hash}`\n"
    )
    out.append(
        f"- **Latency:** {m.metrics.total_latency_ms:.0f} ms  "
        f"- **Cost:** ${m.metrics.est_cost_usd:.4f}  "
        f"- **Models:** " + ", ".join(f"{k}={v}" for k, v in m.model_ids.items() if v) + "\n"
    )

    out.append("\n## Diagnoses (ICD-10-CM)\n")
    out.append(_suggestion_rows(result.diagnoses))
    out.append("\n## Procedures (CPT)\n")
    out.append(_suggestion_rows(result.procedures))

    out.append("\n## Warnings\n")
    if not result.warnings:
        out.append("_None._\n")
    else:
        for w in result.warnings:
            out.append(f"- **[{w.severity.value.upper()}] {w.type.value}** — {w.message}")
        out.append("")

    out.append(
        "\n> Reviewer: tick **Accept?** to confirm a suggestion, or strike it and "
        "write the correct code. JSON (`result.json`) and the audit trail "
        "(`trace.json`) carry the full machine-readable record.\n"
    )
    return "\n".join(out)
