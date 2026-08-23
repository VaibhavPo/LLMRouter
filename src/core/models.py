from enum import Enum


class ModelRole(str, Enum):
    FAST_CODER = "fast_coder"        # nemotron-3-nano-4b
    CONTEXT_CODER = "context_coder"  # rnj-1 (gemma3 8.3B)
    REASONER = "reasoner"            # qwen3-4b-thinking
    VISION = "vision"                # disabled — not yet benchmarked


# Only models with a passing Phase 1 benchmark result get an entry here.
# This dict IS the enforcement of "no model gets a role without a benchmark."
MODEL_REGISTRY: dict[ModelRole, str | None] = {
    ModelRole.FAST_CODER: "nvidia/nemotron-3-nano-4b",
    ModelRole.CONTEXT_CODER: "essentialai/rnj-1",
    ModelRole.REASONER: "qwen/qwen3-4b-thinking-2507",
    ModelRole.VISION: None,  # intentionally unset
}

# API Endpoint and Bootstrap Settings
LM_STUDIO_API = "http://localhost:1234/v1/chat/completions"
DEFAULT_BOOTSTRAP_MODEL = "google/gemma-4-e2b"