"""Generate the committed example outputs under ``outputs/``.

The brief asks for outputs that are "structured, auditable, and reproducible".
So that a reviewer can see them *without running anything*, we pre-run the live
pipeline on every authored note and commit the result. This script is what
produced the committed ``outputs/`` folder; a reviewer who runs ``make run``
simply overwrites their local copy.

Each note yields one self-contained ``outputs/<doc_id>/`` folder written from a
*single* pipeline call, so the views stay mutually consistent:
  - ``result.json``          — the machine/audit payload (the Pydantic ``CodingResult``)
  - ``result.md``            — the same payload as a human review sheet
  - ``result.annotated.md``  — the note with each code spliced in inline at its span
  - ``trace.json``           — the per-stage decision trail (facts → candidates → coder
    picks → auditor verdicts), the audit artifact behind the final codes.

It also runs the gold-set evaluation once and writes ``outputs/eval/metrics.json``
(aggregate + per-note recall@k), so both the headline metric and the individual
per-note numbers live in the repo pre-run.

Run with live LLM keys (loaded from ``.env``):  ``make examples``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from medcoder.audit_trace import build_trace
from medcoder.ingest import normalize
from medcoder.logging_setup import configure_logging, get_logger
from medcoder.pipeline import run as run_pipeline
from medcoder.render import render_annotated, render_markdown
from medcoder.schemas import CodingResult

log = get_logger("generate_examples")

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = REPO_ROOT / "data" / "notes"
GOLD_PATH = REPO_ROOT / "data" / "gold" / "labels.json"
OUT_ROOT = REPO_ROOT / "outputs"

# Ensure the repo root is importable so `from scripts.evaluate import run_eval`
# resolves under *any* invocation — `python -m scripts.generate_examples` already
# puts it on the path, but a direct `python scripts/generate_examples.py` does not
# (its sys.path[0] is scripts/, not the repo root). This makes the script robust
# either way. `scripts` then resolves as an implicit namespace package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write(path: Path, text: str) -> None:
    """Write `text` to `path`, creating parents and ensuring a single trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n" if not text.endswith("\n") else text)
    log.info("wrote", extra={"path": str(path.relative_to(REPO_ROOT))})


def generate_note_examples() -> None:
    """Run the live pipeline on each authored note and persist the three views
    (`result.json`, `result.md`, `result.annotated.md`) plus the `trace.json` audit trail."""
    for note_path in sorted(NOTES_DIR.glob("*.txt")):
        doc_id = note_path.stem
        raw = note_path.read_text()
        log.info("run_note", extra={"note": note_path.name})
        pres = run_pipeline(raw, document_id=doc_id)
        out_dir = OUT_ROOT / doc_id

        result_json = json.dumps(pres.coding_result.model_dump(mode="json"), indent=2, default=str)
        trace_json = json.dumps(build_trace(pres), indent=2, default=str)
        result_md = render_markdown(pres.coding_result)
        # Offsets index the normalized note text, so annotate normalize(raw).
        annotated_md = render_annotated(pres.coding_result, normalize(raw))

        _write(out_dir / "result.json", result_json)
        _write(out_dir / "result.md", result_md)
        _write(out_dir / "result.annotated.md", annotated_md)
        _write(out_dir / "trace.json", trace_json)


def backfill_annotated() -> None:
    """(Re)write only `result.annotated.md` for each committed note — no pipeline run.

    The annotated view is a pure render over the already-committed `result.json`
    (which carries the evidence offsets) plus the re-normalized note. This lets us
    add the artifact to existing examples WITHOUT re-running the LLM, so the
    committed `result.json` / `trace.json` and the eval numbers are untouched.
    """
    for result_path in sorted(OUT_ROOT.glob("*/result.json")):
        doc_id = result_path.parent.name
        note_path = NOTES_DIR / f"{doc_id}.txt"
        if not note_path.exists():
            log.warning("note_missing_for_backfill", extra={"doc_id": doc_id})
            continue
        cr = CodingResult.model_validate_json(result_path.read_text())
        annotated_md = render_annotated(cr, normalize(note_path.read_text()))
        _write(result_path.parent / "result.annotated.md", annotated_md)


def generate_eval_metrics() -> None:
    """Run the gold-set evaluation once and persist it to `outputs/eval/metrics.json`.

    `run_eval` returns a dict with an `aggregate` block (overall P/R/F1, recall@k,
    latency, cost) and a `per_note` list (individual per-note buckets).
    """
    from scripts.evaluate import run_eval

    log.info("run_eval")
    metrics = run_eval(notes_dir=NOTES_DIR, gold_path=GOLD_PATH)
    _write(OUT_ROOT / "eval" / "metrics.json", json.dumps(metrics, indent=2, default=str))


def main() -> None:
    configure_logging(json_mode=False)
    # `--backfill-annotated` only (re)writes result.annotated.md by re-normalizing the
    # committed note and re-rendering from the committed result.json — no LLM calls, so
    # the rest of the committed examples (result.json / trace.json / metrics) are untouched.
    if "--backfill-annotated" in sys.argv:
        backfill_annotated()
        log.info("backfill_done", extra={"outputs": str(OUT_ROOT.relative_to(REPO_ROOT))})
        return
    generate_note_examples()
    generate_eval_metrics()
    log.info("done", extra={"outputs": str(OUT_ROOT.relative_to(REPO_ROOT))})


if __name__ == "__main__":
    main()
