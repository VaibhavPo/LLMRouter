import json
import re

from .client import run, InferenceError
from .schema import Classification
from .router import TaskType

CLASSIFIER_MODEL_ID = "qwen/qwen3-1.7b"

SYSTEM_PROMPT = """You are a task classifier. Given a user's coding request,
classify it along two independent axes.

Axis 1 — task_type (execution routing):
- simple_code: small, self-contained code changes
- large_context_code: changes needing broad codebase context
- reasoning: requires multi-step logical reasoning
- vision: request involves an image/screenshot

Axis 2 — skill_name (procedure to follow), based on WHAT THE USER IS ASKING:
- tdd: "Write tests" / "Write code with tests" / "Red-green-refactor"
- diagnosis: "Debug" / "Fix bug" / "Why is X failing"
- planning: "Design" / "Architecture" / "How should I structure"
- code_review: "Review my code" / "Is this good"
- domain_modeling: "What entities" / "Data structure" / "Schema design"
- If multiple apply, pick the PRIMARY one
- If none clearly apply: "unknown"

Respond with ONLY a JSON object, no other text, in this exact shape:
{"task_type": "simple_code" | "large_context_code" | "reasoning" | "vision",
 "skill_name": "tdd" | "diagnosis" | "planning" | "code_review" | "domain_modeling" | "unknown",
 "complexity": "low" | "medium" | "high",
 "requires_vision": true | false,
 "requires_reasoning": true | false}
"""

# Deterministic, non-LLM signal for vision — file extensions / keywords that
# indicate an image is actually involved. This is what actually governs
# requires_vision; the LLM's opinion on this field is discarded entirely.
VISION_SIGNALS = (".png", ".jpg", ".jpeg", ".webp", "screenshot", "image")


def _deterministic_requires_vision(raw_request: str) -> bool:
    lowered = raw_request.lower()
    return any(signal in lowered for signal in VISION_SIGNALS)


def classify(raw_request: str) -> Classification:
    prompt = f"{SYSTEM_PROMPT}\n\nUser request: {raw_request}"

    try:
        raw_output = run(CLASSIFIER_MODEL_ID, prompt)
    except InferenceError as e:
        raise

    # Strip common wrapping (```json fences, stray text) defensively —
    # small models don't always follow "ONLY JSON" perfectly.
    match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not match:
        raise ValueError(f"Classifier returned no JSON object: {raw_output!r}")

    parsed = json.loads(match.group(0))
    classification = Classification(**parsed)

    # Deterministic override — this line is the entire reason Version 3
    # exists instead of Version 2. Do not remove it.
    classification.requires_vision = _deterministic_requires_vision(raw_request)

    return classification