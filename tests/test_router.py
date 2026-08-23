from src.core.router import route, TaskType, RoutingError

def test_simple_code_routes_to_fast_coder():
    assert route(TaskType.SIMPLE_CODE) == "nvidia/nemotron-3-nano-4b"

def test_reasoning_routes_to_reasoner():
    assert route(TaskType.REASONING) == "qwen/qwen3-4b-thinking-2507"

def test_large_context_flag_overrides():
    assert route(TaskType.SIMPLE_CODE, context_tokens=5000) == "essentialai/rnj-1"

def test_vision_is_disabled():
    try:
        route(TaskType.VISION)
        assert False, "expected RoutingError"
    except RoutingError:
        pass

if __name__ == "__main__":
    test_simple_code_routes_to_fast_coder()
    test_reasoning_routes_to_reasoner()
    test_large_context_flag_overrides()
    test_vision_is_disabled()
    print("All router tests passed.")