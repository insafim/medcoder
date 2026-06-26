"""`medcoder` CLI — Typer commands for run / build-index / eval."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from .config import get_settings
from .llm import have_api_key_for
from .logging_setup import configure_logging
from .pipeline import run as run_pipeline
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
        None, "--out", "-o", help="Write JSON to this file (default: stdout)"
    ),
    document_id: str | None = typer.Option(None, "--id", help="Override document_id"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip the auditor pass"),
    log_level: str = typer.Option(None, "--log-level", help="DEBUG / INFO / WARNING / ERROR"),
    no_json_logs: bool = typer.Option(False, "--no-json-logs", help="Pretty-print logs to stderr"),
) -> None:
    """Run the pipeline on a single note."""
    s = get_settings()
    if no_verify:
        s.no_verify = True
    configure_logging(level=log_level or s.log_level, json_mode=not no_json_logs)

    # The default config is cross-family (OpenAI coder + Anthropic auditor), so a
    # live run can need more than one provider key. Check every resolved model.
    needed = {s.model_for("extraction"), s.model_for("coder")}
    if not s.no_verify:
        needed.add(s.model_for("auditor"))
    missing = sorted(m for m in needed if not have_api_key_for(m))
    if missing:
        typer.secho(
            f"⚠ No API key in env for: {', '.join(missing)}. Set OPENAI_API_KEY / "
            "ANTHROPIC_API_KEY / etc., or use the mock-based path (make smoke / make test).",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)

    text = note.read_text()
    result = run_pipeline(
        text,
        document_id=document_id or note.stem,
    )
    payload = result.coding_result.model_dump(mode="json")
    rendered = json.dumps(payload, indent=2, default=str)
    if out is not None:
        out.write_text(rendered + "\n")
        typer.echo(f"wrote {out}", err=True)
    else:
        sys.stdout.write(rendered + "\n")


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
