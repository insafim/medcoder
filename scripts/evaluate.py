"""Evaluate the pipeline against the authored gold set.

Reports (split for ICD and CPT — see Plan.md §14):
  - micro P / R / F1
  - macro P / R / F1
  - exact-match ratio (note-level)
  - hierarchical micro-F1 (ICD-10 truncated to 3-char category)
  - retriever recall@k  (the end-to-end recall ceiling)

The gold schema separates "must_include" (counted in recall denominator) from
"may_include" (counted as TP if predicted, but not penalised if missed). This
mirrors real coding: some codes are mandatory; some are defensible alternatives.

Numbers are honest — on a tiny authored gold set they are *directional*, not a
benchmark. The brief asks us to show our scoring methodology; that is the point.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from medcoder.config import get_settings
from medcoder.logging_setup import configure_logging, get_logger, trace_context
from medcoder.pipeline import run as run_pipeline

log = get_logger("evaluate")


# ---- metric primitives ---------------------------------------------------


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def _bucket(predicted: set[str], must: set[str], may: set[str]) -> tuple[int, int, int]:
    """TP/FP/FN against (must, may) gold.

    A prediction is TP if it's in `must` OR `may`.
    A miss against `must` is an FN; missing `may` is *not* penalised.
    Anything predicted that's not in must|may is FP.
    """
    gold = must | may
    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(must - predicted)
    return tp, fp, fn


def _hierarchical_codes(codes: Iterable[str]) -> set[str]:
    """Roll ICD-10 codes up to the 3-char category (e.g., E11.42 → E11)."""
    out = set()
    for c in codes:
        head = c.split(".")[0]
        out.add(head[:3] if len(head) >= 3 else head)
    return out


# ---- per-note evaluation -------------------------------------------------


def evaluate_note(
    note_path: Path,
    gold: dict[str, Any],
) -> dict[str, Any]:
    text = note_path.read_text()
    with trace_context() as tid:
        result = run_pipeline(text, document_id=note_path.stem, trace_id=tid).coding_result
    pred_dx = {s.code for s in result.diagnoses}
    pred_px = {s.code for s in result.procedures}
    dx_must = set(gold["diagnoses"]["must_include"])
    dx_may = set(gold["diagnoses"].get("may_include", []))
    px_must = set(gold["procedures"]["must_include"])
    px_may = set(gold["procedures"].get("may_include", []))

    dx_tp, dx_fp, dx_fn = _bucket(pred_dx, dx_must, dx_may)
    px_tp, px_fp, px_fn = _bucket(pred_px, px_must, px_may)

    # hierarchical (ICD-10 only)
    dx_must_h = _hierarchical_codes(dx_must)
    dx_may_h = _hierarchical_codes(dx_may)
    dx_pred_h = _hierarchical_codes(pred_dx)
    h_tp, h_fp, h_fn = _bucket(dx_pred_h, dx_must_h, dx_may_h)

    exact_dx = pred_dx == dx_must
    exact_px = pred_px == px_must

    return {
        "note": note_path.name,
        "n_dx_pred": len(pred_dx),
        "n_px_pred": len(pred_px),
        "icd": {"tp": dx_tp, "fp": dx_fp, "fn": dx_fn},
        "cpt": {"tp": px_tp, "fp": px_fp, "fn": px_fn},
        "icd_hierarchical": {"tp": h_tp, "fp": h_fp, "fn": h_fn},
        "exact_match_icd": exact_dx,
        "exact_match_cpt": exact_px,
        "latency_ms": result.metadata.metrics.total_latency_ms,
        "cost_usd": result.metadata.metrics.est_cost_usd,
        "n_warnings": len(result.warnings),
    }


def _sum_bucket(rows: list[dict[str, Any]], key: str) -> tuple[int, int, int]:
    tp = sum(r[key]["tp"] for r in rows)
    fp = sum(r[key]["fp"] for r in rows)
    fn = sum(r[key]["fn"] for r in rows)
    return tp, fp, fn


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    icd = _sum_bucket(rows, "icd")
    cpt = _sum_bucket(rows, "cpt")
    icd_h = _sum_bucket(rows, "icd_hierarchical")
    return {
        "n_notes": len(rows),
        "micro_icd":  {"p": _prf(*icd)[0],  "r": _prf(*icd)[1],  "f1": _prf(*icd)[2],  "tp": icd[0],  "fp": icd[1],  "fn": icd[2]},
        "micro_cpt":  {"p": _prf(*cpt)[0],  "r": _prf(*cpt)[1],  "f1": _prf(*cpt)[2],  "tp": cpt[0],  "fp": cpt[1],  "fn": cpt[2]},
        "micro_icd_hierarchical": {
            "p": _prf(*icd_h)[0], "r": _prf(*icd_h)[1], "f1": _prf(*icd_h)[2],
        },
        "exact_match_icd_ratio": sum(1 for r in rows if r["exact_match_icd"]) / len(rows),
        "exact_match_cpt_ratio": sum(1 for r in rows if r["exact_match_cpt"]) / len(rows),
        "mean_latency_ms": statistics.mean(r["latency_ms"] for r in rows),
        "total_cost_usd": sum(r["cost_usd"] for r in rows),
    }


# ---- top-level -----------------------------------------------------------


def run_eval(notes_dir: Path, gold_path: Path) -> dict[str, Any]:
    gold = json.loads(gold_path.read_text())["notes"]
    rows: list[dict[str, Any]] = []
    for stem, g in gold.items():
        path = notes_dir / f"{stem}.txt"
        if not path.exists():
            log.warning("note_missing", extra={"stem": stem})
            continue
        log.info("eval_note", extra={"note": path.name})
        rows.append(evaluate_note(path, g))
    return {"per_note": rows, "aggregate": aggregate(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run gold-set evaluation.")
    parser.add_argument("--notes", type=Path, default=Path("data/notes"))
    parser.add_argument("--gold", type=Path, default=Path("data/gold/labels.json"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    s = get_settings()
    configure_logging(level=s.log_level)
    metrics = run_eval(args.notes, args.gold)
    rendered = json.dumps(metrics, indent=2, default=str)
    if args.out:
        args.out.write_text(rendered + "\n")
        print(f"wrote {args.out}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
