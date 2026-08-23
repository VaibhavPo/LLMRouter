"""
phase1_test4_classifier_reasoning.py

Two isolated benchmarks that do NOT ask any model to write code:

  1. CLASSIFIER BENCHMARK  -> tests qwen3-1.7b's actual proposed job:
     turn a one-line dev request into a small structured JSON object.
     Graded on: valid JSON, correct-ish fields, no stray prose, speed.

  2. REASONING BENCHMARK   -> tests qwen3-4b-thinking / deepseek-r1-8b's
     actual proposed job: root-cause diagnosis, NOT code generation.
     Graded on: did it name the real bug, in a short budget of prose,
     with a generous time allowance (this tier is meant to run in the
     background, not block the user).

Run:
    python phase1_test4_classifier_reasoning.py --mode classifier
    python phase1_test4_classifier_reasoning.py --mode reasoning
    python phase1_test4_classifier_reasoning.py --mode all

Requires the `lmstudio` python SDK and LM Studio running locally,
same as phase1_test3.py.
"""

import argparse
import json
import re
import time
from datetime import datetime

import lmstudio as lms

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLASSIFIER_MODELS = [
    {"id": "qwen/qwen3-1.7b", "gpu_ratio": 1.0},
]

REASONING_MODELS = [
    {"id": "qwen/qwen3-4b-thinking-2507", "gpu_ratio": 1.0},
    {"id": "deepseek/deepseek-r1-0528-qwen3-8b", "gpu_ratio": 0.75},
]

CLASSIFIER_TIMEOUT_S = 15          # this model's whole job is to be fast
REASONING_TIMEOUT_S = 300          # deliberately generous — background tier

CLASSIFIER_MAX_TOKENS = 200        # a JSON object should never need more
REASONING_MAX_TOKENS = 6000        # let it think without truncating mid-thought

RESULTS_PATH = "classifier_reasoning_benchmark_results.json"

# ---------------------------------------------------------------------------
# Task sets
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM_PROMPT = """You are a task classifier for a coding assistant router.
Given a short developer request, respond with ONLY a single JSON object, no other text,
no markdown fences, no explanation. Use exactly this schema:

{"task_type": "<one of: coding, debugging, refactoring, explanation, planning>",
 "complexity": "<one of: low, medium, high>",
 "requires_vision": <true or false>,
 "requires_reasoning": <true or false>}
"""

CLASSIFIER_CASES = [
    "Add JWT authentication to this FastAPI project.",
    "Find why this React component is rendering twice and fix it.",
    "Refactor this module and add tests.",
    "Explain why you changed this function.",
    "Fix the typo in this docstring.",
    "This screenshot shows a broken login button, can you tell what's wrong with the layout?",
    "Design the database schema for a multi-tenant SaaS app.",
]

# Each reasoning case has a known, gradeable root cause.
# The model is told explicitly NOT to write corrected code -- diagnosis only.
REASONING_SYSTEM_PROMPT = """You are a senior engineer doing root-cause analysis.
You will be given a short traceback or bug description plus a small function.
Explain in 3-5 sentences what is causing the bug and what the fix should conceptually be.
Do NOT write the full corrected code. Do not write any code block. Diagnosis only.
"""

REASONING_CASES = [
    {
        "id": "mutable_default_arg",
        "prompt": """
def add_item(item, bucket=[]):
    bucket.append(item)
    return bucket

print(add_item(1))
print(add_item(2))
# Expected: [2]
# Actual:   [1, 2]
""",
        "expected_keywords": ["mutable", "default argument", "shared", "list"],
    },
    {
        "id": "async_missing_await",
        "prompt": """
async def fetch_user(user_id):
    result = get_user_from_db(user_id)  # get_user_from_db is an async def function
    return result.name

# Traceback:
# AttributeError: 'coroutine' object has no attribute 'name'
""",
        "expected_keywords": ["await", "coroutine"],
    },
    {
        "id": "off_by_one",
        "prompt": """
def get_last_n_items(items, n):
    return items[len(items) - n - 1:]

# get_last_n_items([1,2,3,4,5], 2) returns [3,4,5] instead of the expected [4,5]
""",
        "expected_keywords": ["off by one", "off-by-one", "index", "-n", "len"],
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_json(text: str):
    """Pull the first {...} block out of a response and parse it."""
    text = text.strip()
    # strip markdown fences if present, even though we told it not to use them
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None, "No JSON object found in response"
    try:
        return json.loads(match.group(0)), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def grade_classification(parsed: dict):
    """Loose structural grading -- no ground truth labels yet, just sanity."""
    required_keys = {"task_type", "complexity", "requires_vision", "requires_reasoning"}
    missing = required_keys - parsed.keys()
    if missing:
        return False, f"Missing keys: {missing}"
    if parsed["complexity"] not in ("low", "medium", "high"):
        return False, f"Invalid complexity value: {parsed['complexity']}"
    if not isinstance(parsed["requires_vision"], bool):
        return False, "requires_vision is not boolean"
    if not isinstance(parsed["requires_reasoning"], bool):
        return False, "requires_reasoning is not boolean"
    return True, None


def grade_reasoning(response_text: str, expected_keywords: list):
    lowered = response_text.lower()
    hit = any(kw.lower() in lowered for kw in expected_keywords)
    return hit


def run_with_timeout(model, prompt, system_prompt, max_tokens, timeout_s):
    """Single-turn call against an LM Studio model with a wall-clock timeout."""
    start = time.time()
    try:
        chat = lms.Chat()
        if system_prompt:
            chat.add_system_prompt(system_prompt)
        chat.add_user_message(prompt)

        response = model.respond(
            chat,
            config={"maxTokens": max_tokens},
        )
        latency = time.time() - start
        text = str(response)
        return text, latency, False, None
    except Exception as e:
        latency = time.time() - start
        timed_out = latency >= timeout_s
        return None, latency, timed_out, str(e)


# ---------------------------------------------------------------------------
# Benchmark: classifier
# ---------------------------------------------------------------------------

def benchmark_classifier():
    print(f"\n=== CLASSIFIER BENCHMARK ({len(CLASSIFIER_CASES)} cases) ===")
    all_results = []

    for entry in CLASSIFIER_MODELS:
        model_id, gpu_ratio = entry["id"], entry["gpu_ratio"]
        print(f"\n--- {model_id} (gpu_ratio={gpu_ratio}) ---")
        try:
            model = lms.llm(model_id, config={"gpu": {"ratio": gpu_ratio}})
        except Exception as e:
            print(f"  ERROR loading model: {e}")
            all_results.append({"model": model_id, "load_error": str(e)})
            continue

        case_results = []
        passed = 0
        total_latency = 0.0

        for case_prompt in CLASSIFIER_CASES:
            text, latency, timed_out, err = run_with_timeout(
                model, case_prompt, CLASSIFIER_SYSTEM_PROMPT,
                CLASSIFIER_MAX_TOKENS, CLASSIFIER_TIMEOUT_S,
            )
            total_latency += latency

            if err:
                print(f"  [ERR ] ({latency:.1f}s) {case_prompt[:50]!r} -> {err}")
                case_results.append({"prompt": case_prompt, "error": err, "latency": latency})
                continue

            parsed, parse_err = extract_json(text)
            if parse_err:
                print(f"  [FAIL] ({latency:.1f}s) {case_prompt[:50]!r} -> {parse_err}")
                case_results.append({
                    "prompt": case_prompt, "raw_response": text,
                    "error": parse_err, "latency": latency,
                })
                continue

            ok, grade_err = grade_classification(parsed)
            status = "OK  " if ok else "FAIL"
            if ok:
                passed += 1
            print(f"  [{status}] ({latency:.1f}s) {case_prompt[:50]!r} -> {parsed}")
            case_results.append({
                "prompt": case_prompt, "parsed": parsed,
                "valid": ok, "grade_error": grade_err, "latency": latency,
            })

        n = len(CLASSIFIER_CASES)
        avg_latency = total_latency / n if n else 0
        print(f"  SCORE: {passed}/{n} valid  |  avg latency {avg_latency:.2f}s")
        all_results.append({
            "model": model_id, "gpu_ratio": gpu_ratio,
            "passed": passed, "total": n, "avg_latency": avg_latency,
            "cases": case_results,
        })

    return all_results


# ---------------------------------------------------------------------------
# Benchmark: reasoning
# ---------------------------------------------------------------------------

def benchmark_reasoning():
    print(f"\n=== REASONING BENCHMARK ({len(REASONING_CASES)} cases) ===")
    print(f"Timeout per case: {REASONING_TIMEOUT_S}s | max tokens: {REASONING_MAX_TOKENS}")
    all_results = []

    for entry in REASONING_MODELS:
        model_id, gpu_ratio = entry["id"], entry["gpu_ratio"]
        print(f"\n--- {model_id} (gpu_ratio={gpu_ratio}) ---")
        try:
            model = lms.llm(model_id, config={"gpu": {"ratio": gpu_ratio}})
        except Exception as e:
            print(f"  ERROR loading model: {e}")
            all_results.append({"model": model_id, "load_error": str(e)})
            continue

        case_results = []
        passed = 0

        for case in REASONING_CASES:
            text, latency, timed_out, err = run_with_timeout(
                model, case["prompt"], REASONING_SYSTEM_PROMPT,
                REASONING_MAX_TOKENS, REASONING_TIMEOUT_S,
            )

            if err or text is None:
                status = "TIMEOUT" if timed_out else "ERROR"
                print(f"  [{status}] {case['id']} ({latency:.1f}s) -> {err}")
                case_results.append({
                    "case_id": case["id"], "error": err,
                    "timed_out": timed_out, "latency": latency,
                })
                continue

            hit = grade_reasoning(text, case["expected_keywords"])
            status = "OK  " if hit else "MISS"
            if hit:
                passed += 1
            print(f"  [{status}] {case['id']} ({latency:.1f}s) "
                  f"-> {'found expected root cause' if hit else 'did NOT mention expected root cause'}")
            case_results.append({
                "case_id": case["id"], "response": text,
                "matched_expected": hit, "latency": latency,
            })

        n = len(REASONING_CASES)
        print(f"  SCORE: {passed}/{n} correct diagnoses")
        all_results.append({
            "model": model_id, "gpu_ratio": gpu_ratio,
            "passed": passed, "total": n, "cases": case_results,
        })

    return all_results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["classifier", "reasoning", "all"], default="all")
    args = parser.parse_args()

    output = {"run_at": datetime.now().isoformat(), "mode": args.mode}

    if args.mode in ("classifier", "all"):
        output["classifier_results"] = benchmark_classifier()

    if args.mode in ("reasoning", "all"):
        output["reasoning_results"] = benchmark_reasoning()

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nFull results saved to {RESULTS_PATH}")

    # --- summary tables ---
    if "classifier_results" in output:
        print("\n=== CLASSIFIER SUMMARY ===")
        print(f"{'Model':<35}{'Valid':<12}{'Avg Latency(s)':<16}")
        for r in output["classifier_results"]:
            if "load_error" in r:
                print(f"{r['model']:<35}{'LOAD ERR':<12}")
                continue
            score_str = f"{r['passed']}/{r['total']}"
            print(f"{r['model']:<35}{score_str:<12}{r['avg_latency']:<16.2f}")

    if "reasoning_results" in output:
        print("\n=== REASONING SUMMARY ===")
        print(f"{'Model':<40}{'Correct Diagnoses':<20}")
        for r in output["reasoning_results"]:
            if "load_error" in r:
                print(f"{r['model']:<40}{'LOAD ERR':<20}")
                continue
            score_str = f"{r['passed']}/{r['total']}"
            print(f"{r['model']:<40}{score_str:<20}")


if __name__ == "__main__":
    main()