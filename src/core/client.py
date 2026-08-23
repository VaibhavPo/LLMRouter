import lmstudio as lms

REASONING_END_MARKER_PATTERN = r"__LM_STUDIO_INTERNAL_LSEP_SYNTHETIC_REASONING_END_[a-f0-9]+__"


class InferenceError(Exception):
    """Raised when a model call fails for any reason."""


def _strip_leaked_reasoning(text: str) -> str:
    """
    Some models emit reasoning + final answer as one blob with an internal
    LM Studio marker between them, instead of the SDK splitting it into
    separate .reasoning/.content fields. Keep only what's after the marker
    if present; otherwise return the text unchanged.
    """
    import re
    match = re.search(REASONING_END_MARKER_PATTERN, text)
    if match:
        return text[match.end():].strip()
    return text


def run(model_id: str, prompt: str, timeout_s: float = 60.0) -> str:
    try:
        model = lms.llm(model_id)
        result = model.respond(prompt)
        raw = result.content if hasattr(result, "content") else str(result)
        return _strip_leaked_reasoning(raw)
    except Exception as e:
        raise InferenceError(f"Call to {model_id!r} failed: {e}") from e