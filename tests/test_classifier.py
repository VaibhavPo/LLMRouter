from src.core.classifier import classify

def test_vision_override_forces_true_on_keyword():
    result = classify("Fix the bug shown in this screenshot.png")
    assert result.requires_vision is True

def test_vision_override_forces_false_without_signal():
    result = classify("Write a function to sort a list")
    assert result.requires_vision is False

if __name__ == "__main__":
    test_vision_override_forces_true_on_keyword()
    test_vision_override_forces_false_without_signal()
    print("Classifier override tests passed.")