from enum import Enum

from .models import ModelRole, MODEL_REGISTRY


class TaskType(str, Enum):
    SIMPLE_CODE = "simple_code"
    LARGE_CONTEXT_CODE = "large_context_code"
    REASONING = "reasoning"
    VISION = "vision"


class RoutingError(Exception):
    """Raised when no valid model can be selected for a task."""


CONTEXT_ESCALATION_THRESHOLD = 3000


def route(task_type: TaskType, context_tokens: int = 0) -> str:
    if task_type == TaskType.VISION:
        raise RoutingError(
            "Vision routing is disabled: qwen3-vl-4b has not been "
            "benchmarked yet (Phase 1 pending)."
        )

    if task_type == TaskType.REASONING:
        role = ModelRole.REASONER
    elif (
        task_type == TaskType.LARGE_CONTEXT_CODE
        or context_tokens > CONTEXT_ESCALATION_THRESHOLD
    ):
        role = ModelRole.CONTEXT_CODER
    elif task_type == TaskType.SIMPLE_CODE:
        role = ModelRole.FAST_CODER
    else:
        raise RoutingError(f"Unrecognized task_type: {task_type!r}")

    model_id = MODEL_REGISTRY[role]
    if model_id is None:
        raise RoutingError(f"No benchmarked model assigned to role {role}")

    return model_id