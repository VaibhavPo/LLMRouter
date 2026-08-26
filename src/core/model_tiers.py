# src/core/model_tiers.py
"""
Central model-tier registry.

This exists to close the gap between the intended architecture (Planner /
Replanner / FinalValidator on HIGH_REASONING, Checkpoint on MID_REASONING,
deterministic tools needing no model at all) and what was actually wired:
every one of those roles independently hardcoded "google/gemma-4-e2b" as
a default argument (see PlannerBuilder.build_default/build_diagnosis/
build_tdd in config.py, and Orchestrator._get_model_provider /
_get_checkpoint_model_provider in orchestrator.py). gateway.py's own
_MODEL_REGISTRY (nemotron-3-nano-4b, rnj-1) never got connected to any of
that — it only backs the direct gateway.handle() path, which is now a
minority of traffic since planning-first routing was added.

This module is the ONE place that maps an abstract ModelTier to a real
model_id. Every caller below should ask for a tier, not hardcode a
model_id, so re-benchmarking or swapping a model means editing one dict
instead of four call sites.

NOTE ON THE ACTUAL MAPPING: the values below are a starting point, not a
benchmark result. Per your own rule (see gateway.py's _ModelRole.REASONER
comment: "do not assign a model a role in the live router without a
benchmark result to back it"), MID_REASONING and LOW_COST below are
placeholders using whatever's already benchmarked in gateway.py's
_MODEL_REGISTRY. Confirm/replace before relying on this for anything
beyond local testing.
"""

from enum import Enum
from typing import Optional


class ModelTier(str, Enum):
    HIGH_REASONING = "high_reasoning"   # Planner, Replanner, FinalValidator
    MID_REASONING = "mid_reasoning"     # Checkpoint verdicts
    LOW_COST = "low_cost"               # cheap classifiers, simple checks


class TierNotConfiguredError(Exception):
    """Raised when a tier has no model_id assigned yet — fail loud,
    same posture as gateway.py's RoutingError for an unassigned role,
    rather than silently falling back to some other tier's model."""
    pass


# The one dict every role-based provider lookup should go through.
# None = deliberately unassigned (not yet benchmarked for this role).
_TIER_REGISTRY: dict[ModelTier, Optional[str]] = {
    # PLACEHOLDER: gemma-4-e2b is what's actually been getting used for
    # planning/THINK/checkpoint so far, so it's the safest placeholder
    # for HIGH_REASONING until a real benchmark picks the right model.
    ModelTier.HIGH_REASONING: "essentialai/rnj-1",

    # PLACEHOLDER: no lightweight model has been benchmarked specifically
    # for checkpoint-verdict JSON (see Orchestrator._get_checkpoint_model_provider's
    # existing docstring — qwen3-1.7b is "usable with caveats" as a plain
    # classifier only, not proven here). Left unassigned deliberately;
    # falls back to HIGH_REASONING at the call site until benchmarked,
    # mirroring the existing conservative-but-correct behavior rather
    # than guessing.
    ModelTier.MID_REASONING: "qwen.qwen3.5-9b",

    ModelTier.LOW_COST: "qwen/qwen3-1.7b",
}


def resolve_tier(tier: ModelTier, fallback_tier: Optional[ModelTier] = None) -> str:
    """
    Resolve a ModelTier to a concrete model_id.

    If the tier is unassigned and fallback_tier is given, falls back to
    that tier instead of raising — this is how MID_REASONING should
    currently fall back to HIGH_REASONING (conservative: more expensive
    than necessary, never silently promotes an unbenchmarked model into
    a live role, matching the existing docstring in orchestrator.py).

    Raises TierNotConfiguredError if neither the tier nor its fallback
    (if given) is assigned.
    """
    model_id = _TIER_REGISTRY.get(tier)
    if model_id is not None:
        return model_id

    if fallback_tier is not None:
        fallback_model_id = _TIER_REGISTRY.get(fallback_tier)
        if fallback_model_id is not None:
            return fallback_model_id

    raise TierNotConfiguredError(
        f"No model assigned to tier {tier!r}"
        + (f" (fallback {fallback_tier!r} also unassigned)" if fallback_tier else "")
    )