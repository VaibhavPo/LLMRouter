from src.core import LLMGateway, RoutingError


def _fake_runner(model_id: str, prompt: str) -> str:
    if model_id == "qwen/qwen3-1.7b":
        return ('{"task_type": "simple_code", "complexity": "low", '
                 '"requires_vision": false, "requires_reasoning": false}')
    return f"FAKE RESPONSE from {model_id}"


def test_handle_end_to_end_offline():
    gw = LLMGateway(model_runner=_fake_runner)
    result = gw.handle("Write a function to reverse a string")
    assert result == "FAKE RESPONSE from nvidia/nemotron-3-nano-4b"


def test_vision_override_applies_through_public_interface():
    gw = LLMGateway(model_runner=_fake_runner)
    classification = gw.classify_only("fix the bug in screenshot.png")
    assert classification.requires_vision is True


def test_vision_task_type_still_blocked():
    from src.core import TaskType
    from src.core.gateway import _route
    try:
        _route(TaskType.VISION)
        assert False, "expected RoutingError"
    except RoutingError:
        pass


if __name__ == "__main__":
    test_handle_end_to_end_offline()
    test_vision_override_applies_through_public_interface()
    test_vision_task_type_still_blocked()
    print("Gateway tests passed.")