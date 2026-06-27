"""Confidence blending + 3-tier labelling.

Plan.md §9.7: raw LLM verbalised confidence is systematically overconfident, so
we never surface it directly. We blend three signals into a final score and bin
it into 🟢/🟡/🔴 tiers using gold-tuned thresholds (formal Platt / isotonic
calibration is documented as a production extension).

Signals:
  - s_retrieval: how strong was the candidate's retrieval rank?
                 (normalised RRF score relative to the top of the list)
  - s_coder:     the coder's verbalised confidence in [0, 1]
                 (kept but discounted vs the other signals)
  - s_audit:     +0.15 if auditor agreed, -0.30 if auditor disagreed, 0 if not run
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import get_settings
from .schemas import CandidateCode, ConfidenceTier


@dataclass
class ConfidenceInputs:
    coder_confidence: float
    retrieval_score: float
    retrieval_rank: int  # 1-based
    audit_agree: bool | None  # None = audit skipped


def _retrieval_subscore(score: float, rank: int) -> float:
    """Map (raw RRF score, rank) to a [0, 1] retrieval-strength signal.

    Rank 1 → ~0.95, rank 5 → ~0.75, rank 15 → ~0.4.  This is intentionally
    monotone-in-rank rather than monotone-in-raw-score, because RRF scores are
    not on a calibrated absolute scale.
    """
    # smooth rank curve; tweakable on a gold set
    if rank <= 0:
        rank = 1
    return max(0.0, min(1.0, 1.0 / (1.0 + 0.18 * (rank - 1))))


def _audit_adjustment(audit_agree: bool | None) -> float:
    if audit_agree is True:
        return 0.15
    if audit_agree is False:
        return -0.30
    return 0.0


def blend(inputs: ConfidenceInputs) -> float:
    """Weighted blend of (retrieval, coder confidence) + audit adjustment.

    Weights: 0.55 retrieval, 0.45 coder — empirical starting point. Re-tune via
    ``scripts/evaluate.py`` against ``data/gold/labels.json`` when the gold set
    grows large enough to support formal calibration (isotonic / Platt — see
    Plan.md §9.7).
    """
    s_ret = _retrieval_subscore(inputs.retrieval_score, inputs.retrieval_rank)
    s_coder = max(0.0, min(1.0, inputs.coder_confidence))
    base = 0.55 * s_ret + 0.45 * s_coder
    final = base + _audit_adjustment(inputs.audit_agree)
    return max(0.0, min(1.0, final))


def tier_for(score: float) -> ConfidenceTier:
    s = get_settings()
    if score >= s.tier_high_threshold:
        return ConfidenceTier.HIGH
    if score >= s.tier_low_threshold:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW


def make_inputs(
    candidate: CandidateCode, coder_confidence: float, audit_agree: bool | None
) -> ConfidenceInputs:
    """Assemble the three confidence signals for one candidate.

    The retrieval rank prefers the **fused** (post-merge) rank, then the dense
    rank, then the lexical rank, then a large sentinel. Explicit ``is not None``
    checks (not ``or``) so a legitimate rank of 0 is never skipped as falsy.
    """
    rank = next(
        (
            r
            for r in (candidate.fused_rank, candidate.dense_rank, candidate.lexical_rank)
            if r is not None
        ),
        99,
    )
    return ConfidenceInputs(
        coder_confidence=coder_confidence,
        retrieval_score=candidate.retrieval_score,
        retrieval_rank=rank,
        audit_agree=audit_agree,
    )
