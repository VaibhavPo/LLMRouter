"""
Phase 1b - automated benchmark across all remaining candidate models.

Why this is a separate script from phase1_probe.py:
  phase1_probe.py uses the OpenAI-compatible client (openai package) -
  that's the portable, production path the router will eventually use.
  But that endpoint has NO way to control GPU offload per request; it
  only lets you pick which already-configured model to call.

  To set GPU offload ourselves, we need LM Studio's own SDK, which
  exposes load-time settings (GPU ratio, context length, etc). This
  script is a one-time diagnostic tool - not something the orchestrator
  will use later.

For each model below, this script:
  1. Loads it explicitly with a chosen GPU offload ratio
  2. Sends the test prompt once  (-> "cold" - includes load settling)
  3. Sends it again              (-> "warm" - steady-state latency)
  4. Unloads it before moving to the next model
  5. Saves everything to benchmark_results.json and prints a summary

Install first:
  pip install lmstudio
"""

import json
import time

import lmstudio as lms

TEST_PROMPT = "In one sentence, what is a Python decorator?"

# gpu_ratio is 0.0-1.0, NOT an exact layer count. LM Studio maps the
# ratio internally onto however many layers that specific model has.
# Small models get 1.0 (max) since they fit with room to spare.
# The one meaningfully large remaining model gets 0.95 (near-max) as
# an approximation of the "30 layers" you were setting manually -
# adjust this down if it still overflows VRAM on your 6GB card.
MODELS = [
    {"id": "qwen/qwen3-1.7b",                   "gpu_ratio": 1.0},
    {"id": "qwen/qwen3-vl-4b",                  "gpu_ratio": 1.0},
    {"id": "nvidia/nemotron-3-nano-4b",         "gpu_ratio": 1.0},
    {"id": "google/gemma-4-e2b",                "gpu_ratio": 1.0},
    {"id": "qwen/qwen3-4b-thinking-2507",       "gpu_ratio": 1.0},
    {"id": "essentialai/rnj-1",                 "gpu_ratio": 1.0},
    {"id": "deepseek/deepseek-r1-0528-qwen3-8b", "gpu_ratio": 0.95},
]
# Deliberately excluded (confirmed too large for 6GB VRAM in Phase 1):
#   qwen.qwen3.5-9b@q3_k_s, qwen.qwen3.5-9b@q2_k, qwen_qwen3.5-9b


def benchmark_model(model_id: str, gpu_ratio: float) -> dict:
    result = {
        "model": model_id,
        "gpu_ratio": gpu_ratio,
        "load_seconds": None,
        "cold_call_seconds": None,
        "warm_call_seconds": None,
        "response_cold": None,
        "response_warm": None,
        "error": None,
    }

    try:
        # Explicit load with our chosen GPU config.
        # Note: if this model id is already loaded from a previous run,
        # LM Studio ignores the new config - that's why we unload every
        # model at the end of its own benchmark, below.
        load_start = time.perf_counter()
        model = lms.llm(model_id, config={"gpu": {"ratio": gpu_ratio}})
        result["load_seconds"] = round(time.perf_counter() - load_start, 2)

        # First call after loading.
        t0 = time.perf_counter()
        response_cold = model.respond(TEST_PROMPT)
        result["cold_call_seconds"] = round(time.perf_counter() - t0, 2)
        result["response_cold"] = str(response_cold)

        # Second call, same loaded model - steady-state latency.
        t1 = time.perf_counter()
        response_warm = model.respond(TEST_PROMPT)
        result["warm_call_seconds"] = round(time.perf_counter() - t1, 2)
        result["response_warm"] = str(response_warm)

        # Unload before the next model gets its turn. This keeps every
        # model's test isolated - no leftover VRAM pressure carried
        # over, and no risk of a stale config being reused.
        model.unload()

    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    print(f"Benchmarking {len(MODELS)} models. This will take a while.\n")

    all_results = []

    for entry in MODELS:
        model_id = entry["id"]
        gpu_ratio = entry["gpu_ratio"]
        print(f"--- {model_id}  (gpu_ratio={gpu_ratio}) ---")

        result = benchmark_model(model_id, gpu_ratio)
        all_results.append(result)

        if result["error"]:
            print(f"  ERROR: {result['error']}\n")
            continue

        print(f"  load: {result['load_seconds']}s")
        print(f"  cold: {result['cold_call_seconds']}s")
        print(f"  warm: {result['warm_call_seconds']}s")
        preview = (result["response_warm"] or "")[:150]
        print(f"  answer (warm): {preview}\n")

    with open("benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print("\n=== SUMMARY (sorted by warm latency, fastest first) ===")
    ranked = sorted(
        (r for r in all_results if not r["error"]),
        key=lambda r: r["warm_call_seconds"],
    )
    print(f"{'Model':<42} {'Cold(s)':>8} {'Warm(s)':>8}")
    for r in ranked:
        print(f"{r['model']:<42} {r['cold_call_seconds']:>8} {r['warm_call_seconds']:>8}")

    failed = [r["model"] for r in all_results if r["error"]]
    if failed:
        print("\nFailed to benchmark:")
        for m in failed:
            print(f"  - {m}")

    print("\nFull details (including full response text) saved to benchmark_results.json")


if __name__ == "__main__":
    main()