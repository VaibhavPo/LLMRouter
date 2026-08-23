from src.skills.diagnosis_runner import (
    run_diagnosis_skill,
    _evaluate_diagnosis_gating,
)


def test_compliant_response_passes():
    fake = (
        "## MINIMIZE\nminimal case here\n"
        "## HYPOTHESIZE\nFails because the index is off-by-one when list is empty.\n"
        "## INSTRUMENT\nprint(len(items)) to confirm\n"
        "## FIX\ncorrected code here\n"
        "## VERIFY\ndef test_empty_list():\n    assert func([]) == []\n"
    )
    result = _evaluate_diagnosis_gating(fake)
    assert result.passed is True


def test_missing_phase_fails():
    fake = (
        "## MINIMIZE\nminimal case\n"
        "## HYPOTHESIZE\nFails because of missing check\n"
        "## FIX\nfixed\n"
        "## VERIFY\nassert func() == True\n"
    )
    result = _evaluate_diagnosis_gating(fake)
    assert result.all_phases_present is False
    assert result.passed is False


def test_out_of_order_fails():
    fake = (
        "## MINIMIZE\ncase\n"
        "## INSTRUMENT\nprint debug\n"
        "## HYPOTHESIZE\nFails because X returns None\n"
        "## FIX\nfix\n"
        "## VERIFY\nassert x == 1\n"
    )
    result = _evaluate_diagnosis_gating(fake)
    assert result.followed_order is False
    assert result.passed is False


def test_vague_hypothesize_fails():
    fake = (
        "## MINIMIZE\nminimal case\n"
        "## HYPOTHESIZE\nSomething might be wrong with the code.\n"
        "## INSTRUMENT\nprint statements\n"
        "## FIX\nfix\n"
        "## VERIFY\nassert func() == True\n"
    )
    result = _evaluate_diagnosis_gating(fake)
    assert result.hypothesize_is_vague is True
    assert result.passed is False


def test_trivial_verify_fails():
    fake = (
        "## MINIMIZE\nminimal case\n"
        "## HYPOTHESIZE\nFails because index is wrong\n"
        "## INSTRUMENT\nprint(index)\n"
        "## FIX\nfix\n"
        "## VERIFY\nRun the test suite again to confirm.\n"
    )
    result = _evaluate_diagnosis_gating(fake)
    assert result.verify_is_trivial is True
    assert result.passed is False


def test_real_assert_in_verify_passes():
    fake = (
        "## MINIMIZE\nminimal case\n"
        "## HYPOTHESIZE\nFails because of off-by-one in range\n"
        "## INSTRUMENT\nprint(i)\n"
        "## FIX\nfix\n"
        "## VERIFY\nassert sorted_merge([1,3],[2,4]) == [1,2,3,4]\n"
    )
    result = _evaluate_diagnosis_gating(fake)
    assert result.verify_is_trivial is False


def test_fake_runner_receives_skill_text():
    def fake_runner(model_id: str, prompt: str) -> str:
        assert "MINIMIZE" in prompt
        assert "HYPOTHESIZE" in prompt
        assert "INSTRUMENT" in prompt
        assert "FIX" in prompt
        assert "VERIFY" in prompt
        return (
            "## MINIMIZE\ncase\n"
            "## HYPOTHESIZE\nFails because index returns None\n"
            "## INSTRUMENT\nprint(val)\n"
            "## FIX\nfix\n"
            "## VERIFY\nassert func(x) == expected\n"
        )

    result = run_diagnosis_skill("some bug", model_runner=fake_runner)
    assert result.passed is True


if __name__ == "__main__":
    test_compliant_response_passes()
    test_missing_phase_fails()
    test_out_of_order_fails()
    test_vague_hypothesize_fails()
    test_trivial_verify_fails()
    test_real_assert_in_verify_passes()
    test_fake_runner_receives_skill_text()
    print("Diagnosis runner tests passed.")