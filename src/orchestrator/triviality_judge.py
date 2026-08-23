import json
from pydantic import BaseModel
from typing import Literal
import lmstudio as lms


class ChangeClassification(BaseModel):
    verdict: Literal["trivial", "significant"]
    reason: str
    affected_sections: list[str]


# Benchmark this model the same way grilling/diagnosis/classification were
# benchmarked before trusting it long-term. Currently unbenchmarked for
# triviality judgment specifically — nemotron-3-nano-4b is proven for code
# generation (FAST_CODER role), not for requirements-analysis judgment calls.
CLASSIFIER_MODEL = "nvidia/nemotron-3-nano-4b"

SYSTEM_PROMPT = """You are a requirements analyst. You will be given:
1. A project's CONTEXT.md (its requirements, vocabulary, and assumptions)
2. A change request from a developer

Your job: decide if the change is TRIVIAL or SIGNIFICANT.

TRIVIAL means: the change does not add, remove, or alter any requirement, shared vocabulary
term, or architectural assumption in the CONTEXT.md. Examples: fixing a typo, renaming an
internal variable, adding a log statement, changing a UI color with no spec reference.

SIGNIFICANT means: the change introduces a new requirement, modifies an existing one, adds
a new domain term, changes a system assumption, or expands the project's scope in any way.
Examples: adding a new API endpoint, changing authentication behaviour, adding a new user
role, supporting a new data format.

Respond ONLY with valid JSON matching this schema — no explanation, no markdown, no extra text:
{
  "verdict": "trivial" | "significant",
  "reason": "<one sentence explaining your decision>",
  "affected_sections": ["<section name>", ...]  // empty list if trivial
}"""


def classify_change(context_md: str, change_request: str) -> ChangeClassification:
    model = lms.llm(CLASSIFIER_MODEL)

    user_message = f"""CONTEXT.md:
---
{context_md}
---

Change request: {change_request}

Classify this change as trivial or significant."""

    response = model.respond(
        {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
        },
        config={
            "temperature": 0.1,
        },
    )

    parsed = response.parsed
    if isinstance(parsed, dict):
        return ChangeClassification(**parsed)

    raw = response.content.strip()

    # Strip markdown fences if the model wraps output despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    json_start = raw.find("{")
    if json_start == -1:
        raise ValueError(f"Classifier returned no JSON object: {raw!r}")

    parsed, _ = json.JSONDecoder().raw_decode(raw[json_start:])
    return ChangeClassification(**parsed)