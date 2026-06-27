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


# ---- annotated-note view -------------------------------------------------

# Keyed by the enum *value* strings (not the enum types) so this module needs no
# extra schema imports — and so a ruff autofix can't strip an "unused" import.
_TIER_GLYPH = {"high": "🟢", "medium": "🟡", "low": "🔴"}
_AUDIT_GLYPH_INLINE = {True: "✓", False: "✗", None: "–"}


def _suggestion_marker(s: CodeSuggestion) -> str:
    """Render the inline `「…」` marker `render_annotated` splices in after each span.

    Packs the four things a reviewer needs to act on a code without leaving the note —
    the code, its system, its confidence tier (glyph + word), and the auditor verdict —
    into one ` · `-separated string, e.g. `E11.42 · ICD-10-CM · 🟢 high · ✓`. Both glyph
    lookups use `.get(..., fallback)` so an unexpected enum/None value degrades to a
    placeholder rather than raising mid-render.
    """
    tier = s.confidence_tier.value
    glyph = _TIER_GLYPH.get(tier, "")
    audit = _AUDIT_GLYPH_INLINE.get(s.audit_agree, "?")
    return f"{s.code} · {s.system.value} · {glyph} {tier} · {audit}"


def render_annotated(result: CodingResult, note_text: str) -> str:
    """Render the clinical note with each suggested code spliced in at its evidence span.

    `note_text` MUST be the **normalized** note (``ingest.normalize(raw)``): that is the
    text the offsets were computed against, because evidence `start_offset`/`end_offset`
    index it, not the raw file. Passing raw text instead does NOT raise — it silently
    splices markers at the wrong positions (or trips the unanchored fallback below), so
    callers must normalize first. Each coded span is wrapped «like this» and followed by
    a 「CODE · SYSTEM · tier · audit」 marker; text with no code is left verbatim. This is
    a third human-review view alongside the JSON payload and the Markdown review sheet —
    not a replacement for either.

    Robustness: spans are spliced right-to-left so earlier offsets stay valid; codes
    sharing one span are merged into a single marker; any span that is out of bounds,
    overlaps an already-spliced span, or whose text no longer matches the recorded
    evidence is reported in an "unanchored" footer instead of corrupting the note.
    """
    # Group every suggestion by the exact (start, end) span it cites. One fact can
    # back several codes; several codes can share one fact.
    by_span: dict[tuple[int, int], list[CodeSuggestion]] = {}
    ev_text: dict[tuple[int, int], str] = {}
    for s in [*result.diagnoses, *result.procedures]:
        for ev in s.evidence:
            key = (ev.start_offset, ev.end_offset)
            by_span.setdefault(key, []).append(s)
            ev_text.setdefault(key, ev.text)

    text = note_text
    n = len(note_text)
    unanchored: list[str] = []
    # Splice from the rightmost span leftwards; require each span to end at/before the
    # start of the last one spliced, which also rejects overlaps cleanly.
    last_start = n
    for (start, end), sugs in sorted(by_span.items(), key=lambda kv: kv[0][0], reverse=True):
        markers = " + ".join(_suggestion_marker(s) for s in sugs)
        valid = (
            0 <= start <= end <= n
            and end <= last_start
            and note_text[start:end].strip() == ev_text[(start, end)].strip()
        )
        if not valid:
            unanchored.append(f'- 「{markers}」 — evidence: "{ev_text[(start, end)]}"')
            continue
        span = text[start:end]
        text = f"{text[:start]}«{span}»「{markers}」{text[end:]}"
        last_start = start

    m = result.metadata
    out: list[str] = []
    out.append(f"# Annotated note — `{result.document_id}`\n")
    out.append(
        "> The clinical note with each suggested code shown inline at the evidence span "
        "that justifies it. «…» marks the evidence; 「code · system · tier · audit」 is the "
        "suggestion. **Legend:** 🟢 high · 🟡 medium · 🔴 low confidence; ✓ auditor agreed · "
        "✗ disagreed · – not audited. The machine-readable record is `result.json`; the "
        "decision trail is `trace.json`.\n"
    )
    out.append(f"- **Encounter:** {m.encounter_type.value}  - **Trace:** `{m.trace_id}`\n")
    out.append("```text")
    out.append(text)
    out.append("```")
    if unanchored:
        out.append(
            "\n## Unanchored codes\n\n_Suggested, but their evidence span could not be "
            "placed inline (offset drift or overlap) — see `result.json` for the full record._\n"
        )
        out.extend(unanchored)
        out.append("")
    return "\n".join(out)
