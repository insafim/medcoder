"""Generate the committed example outputs under ``outputs/``.

The brief asks for outputs that are "structured, auditable, and reproducible".
So that a reviewer can see them *without running anything*, we pre-run the live
pipeline on every authored note and commit the result. This script is what
produced the committed ``outputs/`` folder; a reviewer who runs ``make run``
simply overwrites their local copy.

Each note yields one self-contained ``outputs/<doc_id>/`` folder written from a
*single* pipeline call, so the three views stay mutually consistent:
  - ``result.json`` — the machine/audit payload (the Pydantic ``CodingResult``)
  - ``result.md``   — the same payload as a human review sheet
  - ``trace.json``  — the per-stage decision trail (facts → candidates → coder
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
from medcoder.logging_setup import configure_logging, get_logger
from medcoder.pipeline import run as run_pipeline
from medcoder.render import render_markdown

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
    """Run the live pipeline on each authored note and persist all three views."""
    for note_path in sorted(NOTES_DIR.glob("*.txt")):
        doc_id = note_path.stem
        log.info("run_note", extra={"note": note_path.name})
        pres = run_pipeline(note_path.read_text(), document_id=doc_id)
        out_dir = OUT_ROOT / doc_id

        result_json = json.dumps(pres.coding_result.model_dump(mode="json"), indent=2, default=str)
        trace_json = json.dumps(build_trace(pres), indent=2, default=str)
        result_md = render_markdown(pres.coding_result)

        _write(out_dir / "result.json", result_json)
        _write(out_dir / "result.md", result_md)
        _write(out_dir / "trace.json", trace_json)


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
    generate_note_examples()
    generate_eval_metrics()
    log.info("done", extra={"outputs": str(OUT_ROOT.relative_to(REPO_ROOT))})


if __name__ == "__main__":
    main()
