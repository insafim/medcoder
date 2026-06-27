"""`medcoder` CLI — Typer commands for run / build-index / eval."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from .audit_trace import build_trace
from .config import get_settings
from .ingest import normalize
from .llm import have_api_key_for
from .logging_setup import configure_logging
from .pipeline import run as run_pipeline
from .render import render_annotated, render_markdown
from .retrieval.hybrid import get_retriever
from .schemas import CodeSystem

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "medcoder — auditable medical-coding pipeline.\n\n"
        "Reads a clinical note and emits ICD-10 + (synthetic) CPT suggestions with "
        "confidence, evidence, and warnings — ready for human review."
    ),
)


@app.command()
def run(
    note: Path = typer.Argument(
        ..., exists=True, readable=True, help="Path to a .txt clinical note"
    ),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Write the result to this exact path (no auto-save folder)"
    ),
    fmt: str = typer.Option(
        "json",
        "--format",
        help="Output: json (machine/audit) | md (review sheet) | annotated (note with inline codes)",
    ),
    document_id: str | None = typer.Option(None, "--id", help="Override document_id"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip the auditor pass"),
    no_save: bool = typer.Option(
        False, "--no-save", help="Don't persist outputs/<doc_id>/ (stdout only)"
    ),
    log_level: str = typer.Option(None, "--log-level", help="DEBUG / INFO / WARNING / ERROR"),
    no_json_logs: bool = typer.Option(False, "--no-json-logs", help="Pretty-print logs to stderr"),
) -> None:
    """Run the pipeline on a single note.

    By default the result is printed to stdout *and* persisted to
    `outputs/<doc_id>/` — the rendered result (`result.json`, or `result.md` /
    `result.annotated.md` per `--format`) plus `trace.json` (the per-run audit
    trail). Use `--no-save` for stdout only, or `--out PATH` to write one file
    to an exact path.
    """
    s = get_settings()
    if no_verify:
        s.no_verify = True
    configure_logging(level=log_level or s.log_level, json_mode=not no_json_logs)

    fmt = fmt.lower()
    if fmt not in ("json", "md", "annotated"):
        typer.secho(
            f"⚠ Unknown --format {fmt!r}; expected 'json', 'md', or 'annotated'.",
            fg="yellow",
            err=True,
        )
        raise typer.Exit(code=2)

    # The default config is cross-family (OpenAI coder + Anthropic auditor). The
    # coder path (extraction + coder) is mandatory; the auditor is optional, so
    # degrade gracefully rather than hard-failing when *only* the auditor key is
    # missing. We only hard-stop when the mandatory coder path has no usable key.
    core_models = {s.model_for("extraction"), s.model_for("coder")}
    missing_core = sorted(m for m in core_models if not have_api_key_for(m))
    if missing_core:
        typer.secho(
            f"⚠ No API key in env for: {', '.join(missing_core)}. Set OPENAI_API_KEY / "
            "ANTHROPIC_API_KEY / etc., or use the mock-based path (make smoke / make test).",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    if not s.no_verify and not have_api_key_for(s.model_for("auditor")):
        typer.secho(
            f"⚠ No API key for auditor model {s.model_for('auditor')}; continuing "
            "with --no-verify (codes shown without independent verification). "
            "Set the auditor provider key, or set MEDCODER_VERIFIER_MODEL to a "
            "same-family model, to re-enable the audit pass.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        s.no_verify = True

    text = note.read_text()
    pres = run_pipeline(
        text,
        document_id=document_id or note.stem,
    )
    result = pres.coding_result

    if fmt == "md":
        rendered = render_markdown(result)
    elif fmt == "annotated":
        # Offsets index the *normalized* note text, so annotate normalize(raw).
        rendered = render_annotated(result, normalize(text))
    else:
        rendered = json.dumps(result.model_dump(mode="json"), indent=2, default=str)

    if out is not None:
        # Exact-path mode: write the single rendered file, no folder/trace.
        out.write_text(rendered + "\n")
        typer.echo(f"wrote {out}", err=True)
        return

    # Always echo to stdout so piping (e.g. to jq) keeps working.
    sys.stdout.write(rendered + "\n")

    if no_save:
        return

    # Auto-save: one self-contained, inspectable folder per run.
    out_dir = Path("outputs") / result.document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = {"md": "md", "annotated": "annotated.md"}.get(fmt, "json")
    (out_dir / f"result.{ext}").write_text(rendered + "\n")
    trace = json.dumps(build_trace(pres), indent=2, default=str)
    (out_dir / "trace.json").write_text(trace + "\n")
    typer.echo(f"wrote {out_dir}/ (result.{ext}, trace.json)", err=True)


@app.command("build-index")
def build_index_cmd(
    force: bool = typer.Option(False, "--force", help="Rebuild indexes from scratch"),
    system: str = typer.Option("both", "--system", help="icd10 | cpt | both"),
) -> None:
    """Build (or rebuild) the hybrid retrieval indexes on disk."""
    configure_logging()
    import shutil

    from .retrieval.hybrid import reset_cache  # noqa: WPS433  local to avoid import cycles

    s = get_settings()
    if force and s.index_dir.exists():
        shutil.rmtree(s.index_dir)
        reset_cache()
    s.index_dir.mkdir(parents=True, exist_ok=True)

    systems = []
    if system in ("icd10", "both"):
        systems.append(CodeSystem.ICD10)
    if system in ("cpt", "both"):
        systems.append(CodeSystem.CPT)
    for sys_ in systems:
        r = get_retriever(sys_)
        typer.echo(f"{sys_.value}: {len(r.entries)} entries indexed")


@app.command("eval")
def eval_cmd(
    notes_dir: Path = typer.Option(Path("data/notes"), "--notes", exists=True, dir_okay=True),
    gold: Path = typer.Option(Path("data/gold/labels.json"), "--gold", exists=True),
    out: Path | None = typer.Option(None, "--out", help="Write JSON metrics to this file"),
) -> None:
    """Run the gold-set evaluation (see scripts/evaluate.py for details)."""
    configure_logging()
    from scripts.evaluate import run_eval  # imported locally to keep CLI startup cheap

    metrics = run_eval(notes_dir=notes_dir, gold_path=gold)
    rendered = json.dumps(metrics, indent=2)
    if out is not None:
        out.write_text(rendered + "\n")
        typer.echo(f"wrote {out}", err=True)
    else:
        typer.echo(rendered)


@app.command("retrieve")
def retrieve_cmd(
    query: str = typer.Argument(..., help="Normalised clinical term, e.g. 'type 2 diabetes'"),
    system: str = typer.Option("icd10", "--system", help="icd10 | cpt"),
    k: int = typer.Option(10, "--k", help="Top-K candidates to return"),
) -> None:
    """Show what the retriever returns for a query (no LLM calls — useful smoke test)."""
    configure_logging(level="WARNING")
    sys_ = CodeSystem.ICD10 if system == "icd10" else CodeSystem.CPT
    r = get_retriever(sys_)
    hits = r.search(query, top_k=k)
    typer.echo(json.dumps([h.model_dump(mode="json") for h in hits], indent=2))


@app.command()
def config() -> None:
    """Print the resolved settings (and config_hash)."""
    s = get_settings()
    payload = s.model_dump(mode="json")
    payload["config_hash"] = s.config_hash()
    typer.echo(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    app()
