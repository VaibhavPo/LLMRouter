from src.core.client import _strip_leaked_reasoning

def test_strips_leaked_reasoning_marker():
    raw = (
        "some internal thinking here"
        "__LM_STUDIO_INTERNAL_LSEP_SYNTHETIC_REASONING_END_f4e9a8d2c6b14d0c9e5f3a7b8c1d2e6a__"
        "final answer text"
    )
    assert _strip_leaked_reasoning(raw) == "final answer text"

def test_passthrough_when_no_marker():
    assert _strip_leaked_reasoning("plain text") == "plain text"

if __name__ == "__main__":
    test_strips_leaked_reasoning_marker()
    test_passthrough_when_no_marker()
    print("Client tests passed.")