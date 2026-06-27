"""Unit tests for the confidence blending + tier mapping.

These are direct unit tests on the deterministic blend; the pipeline-level
test only checks the score is non-zero, which is too weak a guarantee for
the calibration knobs in this module.
"""

from __future__ import annotations

from medcoder.confidence import ConfidenceInputs, blend, tier_for
from medcoder.schemas import ConfidenceTier


def test_blend_high_retrieval_high_coder_high_audit():
    """Best-case signal stack should produce a high-tier score."""
    score = blend(
        ConfidenceInputs(
            coder_confidence=0.90,
            retrieval_score=0.05,
            retrieval_rank=1,
            audit_agree=True,
        )
    )
    assert score >= 0.85
    assert tier_for(score) == ConfidenceTier.HIGH


def test_blend_auditor_disagreement_demotes_score():
    """A clear auditor disagreement must push a previously-high score down."""
    base = blend(
        ConfidenceInputs(
            coder_confidence=0.90,
            retrieval_score=0.05,
            retrieval_rank=1,
            audit_agree=None,
        )
    )
    disagreed = blend(
        ConfidenceInputs(
            coder_confidence=0.90,
            retrieval_score=0.05,
            retrieval_rank=1,
            audit_agree=False,
        )
    )
    # Disagreement adjustment is -0.30; should drop the score by ~0.30 (clamped).
    assert disagreed < base - 0.20


def test_blend_rank_decay_monotone():
    """Better-ranked retrieval should produce higher scores, all else equal."""
    rank1 = blend(
        ConfidenceInputs(
            coder_confidence=0.5,
            retrieval_score=0.05,
            retrieval_rank=1,
            audit_agree=None,
        )
    )
    rank5 = blend(
        ConfidenceInputs(
            coder_confidence=0.5,
            retrieval_score=0.05,
            retrieval_rank=5,
            audit_agree=None,
        )
    )
    rank15 = blend(
        ConfidenceInputs(
            coder_confidence=0.5,
            retrieval_score=0.05,
            retrieval_rank=15,
            audit_agree=None,
        )
    )
    assert rank1 > rank5 > rank15


def test_blend_score_is_clamped_to_unit_interval():
    """Auditor adjustment shouldn't push outside [0, 1] even with extreme inputs."""
    very_high = blend(
        ConfidenceInputs(
            coder_confidence=1.0,
            retrieval_score=99.0,
            retrieval_rank=1,
            audit_agree=True,
        )
    )
    very_low = blend(
        ConfidenceInputs(
            coder_confidence=0.0,
            retrieval_score=0.0,
            retrieval_rank=99,
            audit_agree=False,
        )
    )
    assert 0.0 <= very_low <= very_high <= 1.0


def test_tier_thresholds_partition_correctly():
    """No score should fall outside the three buckets."""
    for s in (0.0, 0.1, 0.44, 0.45, 0.5, 0.77, 0.78, 0.9, 1.0):
        assert tier_for(s) in {ConfidenceTier.HIGH, ConfidenceTier.MEDIUM, ConfidenceTier.LOW}
    assert tier_for(1.0) == ConfidenceTier.HIGH
    assert tier_for(0.0) == ConfidenceTier.LOW


def test_make_inputs_prefers_fused_rank_over_single_ranker():
    """Confidence must key off the post-fusion rank, not a single ranker's rank."""
    from medcoder.confidence import make_inputs
    from medcoder.schemas import CandidateCode, CodeSystem

    cand = CandidateCode(
        code="E11.9",
        system=CodeSystem.ICD10,
        description="Type 2 diabetes",
        retrieval_score=0.03,
        dense_rank=10,
        lexical_rank=8,
        fused_rank=2,
    )
    assert make_inputs(cand, coder_confidence=0.8, audit_agree=None).retrieval_rank == 2


def test_make_inputs_falls_back_when_no_fused_rank():
    """No fused_rank → fall back to dense, then lexical, then a large default."""
    from medcoder.confidence import make_inputs
    from medcoder.schemas import CandidateCode, CodeSystem

    cand = CandidateCode(
        code="E11.9",
        system=CodeSystem.ICD10,
        description="Type 2 diabetes",
        retrieval_score=0.03,
        dense_rank=4,
        lexical_rank=None,
        fused_rank=None,
    )
    assert make_inputs(cand, coder_confidence=0.8, audit_agree=None).retrieval_rank == 4
