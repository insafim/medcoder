"""Tests for the reviewer Markdown view, per-run audit trace, CLI auto-save /
--no-save / --format, graceful single-key degrade, and eval retrieval recall@k.

These are fast: they construct schema objects directly and mock `run_pipeline`,
so no LLM, no API key, and no retrieval index are needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from medcoder import cli as cli_mod
from medcoder.audit_trace import build_trace
from medcoder.code_assign import CodedAssignment
from medcoder.pipeline import PipelineResult
from medcoder.render import render_annotated, render_markdown
from medcoder.schemas import (
    AssertionStatus,
    CandidateCode,
    CoderCodeChoice,
    CodeSuggestion,
    CodeSystem,
    CodingResult,
    ConfidenceTier,
    EncounterType,
    ExtractedFact,
    RunMetadata,
    RunMetrics,
    Warning,
    WarningSeverity,
    WarningType,
)
from medcoder.verify import AuditOutcome

runner = CliRunner()

# ---- fixtures (built directly, no pipeline) ------------------------------


def _fact(text: str = "type 2 diabetes mellitus", start: int = 0) -> ExtractedFact:
    return ExtractedFact(
        text=text,
        normalized_term=text,
        assertion_status=AssertionStatus.PRESENT,
        start_offset=start,
        end_offset=start + len(text),
        section="assessment",
        kind="diagnosis",
    )


def _candidate(
    code: str = "E11.9",
    system: CodeSystem = CodeSystem.ICD10,
    desc: str = "Type 2 diabetes mellitus",
) -> CandidateCode:
    return CandidateCode(
        code=code, system=system, description=desc, retrieval_score=0.0312, fused_rank=1
    )


def _suggestion(
    code: str = "E11.9",
    system: CodeSystem = CodeSystem.ICD10,
    conf: float = 0.83,
    tier: ConfidenceTier = ConfidenceTier.HIGH,
    audit: bool | None = True,
) -> CodeSuggestion:
    return CodeSuggestion(
        code=code,
        system=system,
        description="Type 2 diabetes mellitus",
        confidence=conf,
        confidence_tier=tier,
        rationale="stated in assessment",
        evidence=[_fact()],
        audit_agree=audit,
    )


def _coding_result(doc_id: str = "t_doc") -> CodingResult:
    meta = RunMetadata(
        trace_id="abc123",
        model_ids={"coder": "openai/gpt-x", "auditor": ""},
        pipeline_version="0.1.1",
        config_hash="deadbeef",
        encounter_type=EncounterType.OUTPATIENT,
        metrics=RunMetrics(total_latency_ms=1234.0, est_cost_usd=0.0031),
    )
    return CodingResult(
        document_id=doc_id,
        diagnoses=[_suggestion()],
        procedures=[
            _suggestion(code="9T0012", system=CodeSystem.CPT, conf=0.80, tier=ConfidenceTier.MEDIUM)
        ],
        warnings=[
            Warning(
                type=WarningType.AMBIGUITY,
                severity=WarningSeverity.INFO,
                message="Fact 'chest pain' dropped from coding.",
            )
        ],
        metadata=meta,
    )


def _pipeline_result() -> PipelineResult:
    fact = _fact()
    cand = _candidate()
    assignment = CodedAssignment(
        fact=fact,
        candidate=cand,
        choice=CoderCodeChoice(code="E11.9", confidence=0.86, rationale="T2DM stated"),
    )
    outcome = AuditOutcome(assignment=assignment, agree=True, note="ok")
    return PipelineResult(
        coding_result=_coding_result(),
        retrieval_by_fact={0: [cand]},
        facts=[fact],
        codable_facts=[fact],
        assignments=[assignment],
        outcomes=[outcome],
    )


# ---- render_markdown -----------------------------------------------------


def test_render_markdown_has_codes_columns_and_warnings():
    md = render_markdown(_coding_result())
    assert "# Coding review" in md
    assert "`E11.9`" in md  # diagnosis
    assert "`9T0012`" in md  # procedure
    assert "Accept?" in md  # reviewer override column
    assert "✓ agree" in md  # audit verdict rendered
    assert "chest pain" in md  # warning surfaced


def test_render_markdown_handles_empty_result():
    cr = _coding_result()
    cr.diagnoses = []
    cr.procedures = []
    cr.warnings = []
    md = render_markdown(cr)
    assert "None suggested" in md
    assert "_None._" in md  # no warnings block


def test_render_markdown_renders_skipped_audit_glyph():
    """A suggestion whose audit was skipped (audit_agree=None) shows the skipped glyph."""
    cr = _coding_result()
    cr.diagnoses = [_suggestion(audit=None)]
    md = render_markdown(cr)
    assert "skipped" in md  # the None branch of _AUDIT_GLYPH


def test_render_markdown_truncates_long_evidence():
    """Evidence longer than 80 chars is truncated with an ellipsis in the table cell."""
    cr = _coding_result()
    long_fact = _fact(text="x" * 200)
    cr.diagnoses = [_suggestion()]
    cr.diagnoses[0].evidence = [long_fact]
    md = render_markdown(cr)
    assert "..." in md
    assert "x" * 200 not in md  # full text not emitted


# ---- render_annotated ----------------------------------------------------


def _sugg_at(code: str, note: str, span_text: str, *, system=CodeSystem.ICD10) -> CodeSuggestion:
    """A CodeSuggestion whose single evidence span points at `span_text` within `note`."""
    start = note.index(span_text)
    ev = ExtractedFact(
        text=span_text,
        normalized_term=span_text,
        assertion_status=AssertionStatus.PRESENT,
        start_offset=start,
        end_offset=start + len(span_text),
        kind="diagnosis",
    )
    return CodeSuggestion(
        code=code,
        system=system,
        description="desc",
        confidence=0.9,
        confidence_tier=ConfidenceTier.HIGH,
        rationale="r",
        evidence=[ev],
        audit_agree=True,
    )


def test_render_annotated_places_code_at_its_span():
    note = "Patient has type 2 diabetes mellitus today."
    cr = _coding_result()
    cr.diagnoses = [_sugg_at("E11.9", note, "type 2 diabetes mellitus")]
    cr.procedures = []
    out = render_annotated(cr, note)
    # marker sits immediately after the wrapped evidence span
    assert "«type 2 diabetes mellitus»「E11.9" in out
    # surrounding (uncoded) text is preserved verbatim
    assert "Patient has «type 2 diabetes mellitus»" in out
    assert "today." in out
    assert "Unanchored" not in out


def test_render_annotated_multiple_codes_one_span_merge():
    """Two codes citing the same span are merged into a single marker."""
    note = "type 2 diabetes mellitus noted."  # default _fact() span (0,24) lands here
    cr = _coding_result()  # diagnosis E11.9 + procedure 9T0012, both cite span (0,24)
    out = render_annotated(cr, note)
    assert "E11.9" in out and "9T0012" in out
    assert " + " in out  # merged, not two separate markers
    # exactly one marker in the annotated note body (the header legend also uses 「…」)
    note_block = out.split("```text")[1]
    assert note_block.count("「") == 1


def test_render_annotated_reverse_splice_keeps_both_spans():
    note = "alpha bravo charlie delta"
    cr = _coding_result()
    cr.diagnoses = [_sugg_at("A00", note, "alpha"), _sugg_at("B00", note, "charlie")]
    cr.procedures = []
    out = render_annotated(cr, note)
    assert "«alpha»「A00" in out
    assert "«charlie»「B00" in out
    # untouched words between/around the spans survive intact
    assert "bravo" in out and "delta" in out


def test_render_annotated_unanchored_on_offset_mismatch():
    """A span whose offsets no longer match the note text is reported, not spliced."""
    note = "completely different text here"
    cr = _coding_result()
    cr.diagnoses = [_suggestion()]  # default evidence span (0,24) ≠ this note's first 24 chars
    cr.procedures = []
    out = render_annotated(cr, note)
    assert "Unanchored" in out
    assert "E11.9" in out  # surfaced in the footer
    # the note block itself is left intact (no «»/「」 splice) — scope to the fenced body
    note_block = out.split("```text")[1].split("```")[0]
    assert note_block.strip() == "completely different text here"


# ---- audit trace ---------------------------------------------------------


def test_build_trace_captures_every_stage():
    trace = build_trace(_pipeline_result())
    assert trace["document_id"] == "t_doc"
    assert trace["trace_id"] == "abc123"
    stages = trace["stages"]
    assert stages["extract"]["facts"][0]["normalized_term"] == "type 2 diabetes mellitus"
    assert stages["retrieve"]["by_fact"][0]["candidates"][0]["code"] == "E11.9"
    assert stages["code"]["assignments"][0]["code"] == "E11.9"
    assert stages["audit"]["verdicts"][0]["agree"] is True
    # the full final payload is embedded for self-containment
    assert trace["result"]["document_id"] == "t_doc"


def test_build_trace_is_json_serializable():
    # round-trip and confirm a non-empty dict (a None return would also not raise)
    data = json.loads(json.dumps(build_trace(_pipeline_result())))
    assert isinstance(data, dict) and data


# ---- CLI: auto-save / --no-save / --format -------------------------------


def _patch_cli(monkeypatch, *, keys=True):
    monkeypatch.setattr(cli_mod, "run_pipeline", lambda *a, **k: _pipeline_result())
    monkeypatch.setattr(cli_mod, "have_api_key_for", lambda m: keys)


def test_run_autosaves_result_and_trace(monkeypatch, tmp_path):
    _patch_cli(monkeypatch)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("Assessment: Type 2 diabetes mellitus.")

    res = runner.invoke(cli_mod.app, ["run", str(note)])
    assert res.exit_code == 0
    out_dir = tmp_path / "outputs" / "t_doc"
    assert (out_dir / "result.json").exists()
    assert (out_dir / "trace.json").exists()
    assert "E11.9" in res.output  # still printed to stdout
    # result.json holds the final payload
    result_saved = json.loads((out_dir / "result.json").read_text())
    assert result_saved["document_id"] == "t_doc"
    # trace.json is valid JSON with the decision trail
    saved = json.loads((out_dir / "trace.json").read_text())
    assert saved["stages"]["retrieve"]["by_fact"][0]["candidates"][0]["code"] == "E11.9"


def test_run_no_save_suppresses_folder(monkeypatch, tmp_path):
    _patch_cli(monkeypatch)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("x")

    res = runner.invoke(cli_mod.app, ["run", str(note), "--no-save"])
    assert res.exit_code == 0
    assert not (tmp_path / "outputs").exists()
    assert "E11.9" in res.output


def test_run_format_md_writes_markdown(monkeypatch, tmp_path):
    _patch_cli(monkeypatch)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("x")

    res = runner.invoke(cli_mod.app, ["run", str(note), "--format", "md"])
    assert res.exit_code == 0
    assert "# Coding review" in res.output
    md_path = tmp_path / "outputs" / "t_doc" / "result.md"
    assert md_path.exists()
    # the saved file is Markdown (not JSON) — confirm content, not just existence
    assert md_path.read_text().startswith("# Coding review")


def test_run_format_annotated_writes_file(monkeypatch, tmp_path):
    _patch_cli(monkeypatch)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    # Leading whitespace makes normalize() load-bearing: only AFTER stripping does the
    # default evidence span (offsets 0–24) line up with "type 2 diabetes mellitus". If the
    # CLI annotated the RAW text instead of normalize(text), the span would mismatch and
    # land in the unanchored footer — so this anchoring check guards the normalize() call.
    note.write_text("   type 2 diabetes mellitus is documented.")

    res = runner.invoke(cli_mod.app, ["run", str(note), "--format", "annotated"])
    assert res.exit_code == 0
    assert "# Annotated note" in res.output
    p = tmp_path / "outputs" / "t_doc" / "result.annotated.md"
    assert p.exists()
    assert "«type 2 diabetes mellitus»" in p.read_text()  # anchored ⇒ normalize() ran


def test_run_rejects_unknown_format(monkeypatch, tmp_path):
    """An unrecognized --format value is a hard stop (Exit 2), before any pipeline run."""
    _patch_cli(monkeypatch)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("x")

    res = runner.invoke(cli_mod.app, ["run", str(note), "--format", "xml"])
    assert res.exit_code == 2


def test_run_out_path_writes_single_file_no_folder(monkeypatch, tmp_path):
    _patch_cli(monkeypatch)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("x")
    target = tmp_path / "custom.json"

    res = runner.invoke(cli_mod.app, ["run", str(note), "--out", str(target)])
    assert res.exit_code == 0
    assert target.exists()
    assert not (tmp_path / "outputs").exists()  # --out skips the auto-save folder


# ---- CLI: graceful single-key degrade ------------------------------------


def test_run_degrades_when_only_auditor_key_missing(monkeypatch, tmp_path):
    """Auditor key missing but coder path present → warn + continue (no Exit 2)."""
    monkeypatch.setattr(cli_mod, "run_pipeline", lambda *a, **k: _pipeline_result())
    # coder/extraction are openai (present); auditor is anthropic (missing)
    monkeypatch.setattr(cli_mod, "have_api_key_for", lambda m: "anthropic" not in m)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("x")

    res = runner.invoke(cli_mod.app, ["run", str(note), "--no-save"])
    assert res.exit_code == 0  # did NOT hard-exit
    assert "--no-verify" in res.output  # canonical phrase from the degrade warning


def test_run_hard_exits_when_coder_key_missing(monkeypatch, tmp_path):
    """No key for the mandatory coder path → still a hard stop (unchanged)."""
    monkeypatch.setattr(cli_mod, "have_api_key_for", lambda m: False)
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("x")

    res = runner.invoke(cli_mod.app, ["run", str(note)])
    assert res.exit_code == 2


# ---- eval retrieval recall@k ---------------------------------------------


def _import_recall_at_k():
    # scripts/ is not an installed package; add the repo root so the import resolves.
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.evaluate import _recall_at_k

    return _recall_at_k


def test_recall_at_k_aggregation():
    _recall_at_k = _import_recall_at_k()
    rows = [
        {"r": {"hit": 2, "total": 3}},
        {"r": {"hit": 1, "total": 1}},
    ]
    assert _recall_at_k(rows, "r") == {"recall_at_k": 0.75, "hit": 3, "total": 4}


def test_recall_at_k_perfect_and_zero_recall():
    _recall_at_k = _import_recall_at_k()
    # hit == total → perfect recall
    assert _recall_at_k([{"r": {"hit": 2, "total": 2}}], "r")["recall_at_k"] == 1.0
    # hit == 0, total > 0 → zero recall on a real denominator
    assert _recall_at_k([{"r": {"hit": 0, "total": 3}}], "r")["recall_at_k"] == 0.0


def test_recall_at_k_empty_denominator():
    _recall_at_k = _import_recall_at_k()
    # total == 0 → defined as 0.0 (no gold codes to recall)
    assert _recall_at_k([{"r": {"hit": 0, "total": 0}}], "r")["recall_at_k"] == 0.0
