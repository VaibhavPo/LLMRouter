from src.skills.skill_loader import run_tdd_skill, _evaluate_phase_gating


def test_evaluates_compliant_response_as_passed():
    fake_response = "## RED\ntest here\n## GREEN\ncode here\n## REFACTOR\nNo refactor needed."
    result = _evaluate_phase_gating(fake_response)
    assert result.passed is True


def test_evaluates_out_of_order_response_as_failed():
    fake_response = "## GREEN\ncode\n## RED\ntest\n## REFACTOR\nNo refactor needed."
    result = _evaluate_phase_gating(fake_response)
    assert result.all_phases_present is True
    assert result.followed_order is False
    assert result.passed is False


def test_evaluates_missing_phase_as_failed():
    fake_response = "## RED\ntest\n## GREEN\ncode"
    result = _evaluate_phase_gating(fake_response)
    assert result.all_phases_present is False
    assert result.passed is False


def test_run_tdd_skill_with_fake_runner():
    def fake_runner(model_id: str, prompt: str) -> str:
        assert "RED" in prompt and "GREEN" in prompt and "REFACTOR" in prompt
        return "## RED\ntest\n## GREEN\ncode\n## REFACTOR\nNo refactor needed."

    result = run_tdd_skill("reverse a string", model_runner=fake_runner)
    assert result.passed is True

def test_flags_stub_implementation_in_red_phase():
    fake_response = (
        "## RED\ndef is_palindrome(s):\n    return False\n"
        "## GREEN\ndef is_palindrome(s):\n    return s == s[::-1]\n"
        "## REFACTOR\nNo refactor needed."
    )
    result = _evaluate_phase_gating(fake_response)
    assert result.red_phase_looks_like_stub is True
    assert result.passed is False


def test_does_not_flag_real_assert_based_test():
    fake_response = (
        "## RED\ndef test_is_palindrome():\n    assert is_palindrome('radar') is True\n"
        "## GREEN\ndef is_palindrome(s):\n    return s == s[::-1]\n"
        "## REFACTOR\nNo refactor needed."
    )
    result = _evaluate_phase_gating(fake_response)
    assert result.red_phase_looks_like_stub is False
    assert result.passed is True

def test_flags_trivial_return_true_in_green_phase():
    fake_response = (
        "## RED\ndef test_email():\n    assert is_valid_email('a@b.com') == True\n"
        "## GREEN\ndef is_valid_email(email):\n    return True\n"
        "## REFACTOR\nNo refactor needed."
    )
    result = _evaluate_phase_gating(fake_response)
    assert result.green_phase_looks_trivial is True
    assert result.passed is False


def test_does_not_flag_real_implementation_in_green_phase():
    fake_response = (
        "## RED\ndef test_email():\n    assert is_valid_email('a@b.com') == True\n"
        "## GREEN\nimport re\ndef is_valid_email(email):\n"
        "    return bool(re.match(r'^[\\w.]+@[\\w]+\\.[\\w]{2,}$', email))\n"
        "## REFACTOR\nNo refactor needed."
    )
    result = _evaluate_phase_gating(fake_response)
    assert result.green_phase_looks_trivial is False
    assert result.passed is True
def test_does_not_flag_fibonacci_iterative_as_trivial():
    fake_response = (
        "## RED\ndef test_fib():\n    assert fibonacci(5) == 5\n"
        "## GREEN\ndef fibonacci(n):\n"
        "    if n <= 1:\n        return n\n"
        "    a, b = 0, 1\n"
        "    for _ in range(2, n + 1):\n        a, b = b, a + b\n"
        "    return b\n"
        "## REFACTOR\nNo refactor needed."
    )
    result = _evaluate_phase_gating(fake_response)
    assert result.green_phase_looks_trivial is False
    assert result.passed is True



if __name__ == "__main__":
    test_evaluates_compliant_response_as_passed()
    test_evaluates_out_of_order_response_as_failed()
    test_evaluates_missing_phase_as_failed()
    test_run_tdd_skill_with_fake_runner()
    test_flags_stub_implementation_in_red_phase()
    test_does_not_flag_real_assert_based_test()
    test_flags_trivial_return_true_in_green_phase()
    test_does_not_flag_real_implementation_in_green_phase()
    test_does_not_flag_fibonacci_iterative_as_trivial()
    print("Skill runner tests passed.")