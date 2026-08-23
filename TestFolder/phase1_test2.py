"""
Phase 1d - real coding task benchmark, with actual pass/fail testing.

Trivia questions ("what is a decorator") tell you almost nothing about
whether a model can actually write correct code. This script gives
every router-eligible model a real task, extracts the code it wrote,
RUNS it, and checks it against test cases - a tiny preview of the
generate -> test -> pass/fail loop the full system will use later.

Excluded from this run:
  - essentialai/rnj-1        (shelved: repeated instruction-following misses)
  - all three 9B Qwen builds (excluded: too large for 6GB VRAM)

Install first (if not already):
  pip install lmstudio
"""

import json
import re
import time

import lmstudio as lms

CODING_PROMPT = """Write a Python function named is_valid_email that takes a \
string and returns True if it looks like a valid email address, False otherwise. \
Use the re module. Return ONLY a single Python code block containing the function \
definition - no explanation, no example usage, no extra text."""

# (email, expected_result) - a mix of clearly valid and clearly invalid cases.
TEST_CASES = [
    ("user@example.com", True),
    ("first.last@sub.example.co.uk", True),
    ("not-an-email", False),
    ("missing@domain", False),
    ("@no-local-part.com", False),
    ("spaces in@email.com", False),
]

MODELS = [
    {"id": "qwen/qwen3-vl-4b",                   "gpu_ratio": 1.0},
    {"id": "google/gemma-4-e2b",                 "gpu_ratio": 1.0},
    {"id": "nvidia/nemotron-3-nano-4b",          "gpu_ratio": 1.0},
    {"id": "qwen/qwen3-1.7b",                    "gpu_ratio": 1.0},
    {"id": "qwen/qwen3-4b-thinking-2507",        "gpu_ratio": 1.0},
    {"id": "deepseek/deepseek-r1-0528-qwen3-8b", "gpu_ratio": 0.75},  # confirmed stable ratio
]

CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def extract_code(response_text: str) -> str | None:
    """Pull the first fenced code block out of a model's response."""
    match = CODE_BLOCK_RE.search(response_text)
    if match:
        return match.group(1).strip()
    return None


def run_tests(code: str) -> dict:
    """
    Execute the extracted code and run it against TEST_CASES.
    Returns a dict with pass/fail counts and per-case detail.
    """
    namespace = {}
    outcome = {
        "executed": False,
        "exec_error": None,
        "has_function": False,
        "passed": 0,
        "failed": 0,
        "total": len(TEST_CASES),
        "case_results": [],
    }

    try:
        exec(code, namespace)
        outcome["executed"] = True
    except Exception as e:
        outcome["exec_error"] = f"{type(e).__name__}: {e}"
        return outcome

    func = namespace.get("is_valid_email")
    if not callable(func):
        outcome["exec_error"] = "Code ran but no callable 'is_valid_email' was defined"
        return outcome

    outcome["has_function"] = True

    for email, expected in TEST_CASES:
        try:
            actual = func(email)
            ok = bool(actual) == expected
        except Exception as e:
            actual = f"EXCEPTION: {type(e).__name__}: {e}"
            ok = False

        outcome["case_results"].append(
            {"input": email, "expected": expected, "actual": actual, "ok": ok}
        )
        if ok:
            outcome["passed"] += 1
        else:
            outcome["failed"] += 1

    return outcome


def benchmark_model(model_id: str, gpu_ratio: float) -> dict:
    result = {
        "model": model_id,
        "gpu_ratio": gpu_ratio,
        "latency_seconds": None,
        "raw_response": None,
        "extracted_code": None,
        "test_outcome": None,
        "error": None,
    }

    try:
        model = lms.llm(model_id, config={"gpu": {"ratio": gpu_ratio}})

        t0 = time.perf_counter()
        response = model.respond(CODING_PROMPT)
        result["latency_seconds"] = round(time.perf_counter() - t0, 2)
        result["raw_response"] = str(response)

        code = extract_code(result["raw_response"])
        result["extracted_code"] = code

        if code is None:
            result["test_outcome"] = {"executed": False, "exec_error": "No code block found in response"}
        else:
            result["test_outcome"] = run_tests(code)

        model.unload()

    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    print(f"Running a real coding task against {len(MODELS)} models.\n")
    print(f"Task: {CODING_PROMPT}\n")

    all_results = []

    for entry in MODELS:
        model_id = entry["id"]
        gpu_ratio = entry["gpu_ratio"]
        print(f"--- {model_id} ---")

        result = benchmark_model(model_id, gpu_ratio)
        all_results.append(result)

        if result["error"]:
            print(f"  ERROR: {result['error']}\n")
            continue

        outcome = result["test_outcome"]
        print(f"  latency: {result['latency_seconds']}s")

        if not outcome["executed"]:
            print(f"  FAILED TO RUN: {outcome['exec_error']}\n")
            continue

        print(f"  tests passed: {outcome['passed']}/{outcome['total']}")
        for case in outcome["case_results"]:
            mark = "OK " if case["ok"] else "FAIL"
            print(f"    [{mark}] {case['input']!r:35} expected={case['expected']!s:5} actual={case['actual']!s}")
        print()

    with open("coding_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print("\n=== SUMMARY ===")
    print(f"{'Model':<42} {'Latency(s)':>10} {'Score':>8}")
    for r in all_results:
        if r["error"] or not r["test_outcome"]["executed"]:
            score = "FAILED"
        else:
            o = r["test_outcome"]
            score = f"{o['passed']}/{o['total']}"
        latency = r["latency_seconds"] if r["latency_seconds"] is not None else "-"
        print(f"{r['model']:<42} {latency!s:>10} {score:>8}")

    print("\nFull responses, extracted code, and per-case results saved to coding_benchmark_results.json")


if __name__ == "__main__":
    main()