import sys
from skills.diagnosis_runner import run_diagnosis_skill

bugs = [
    "A Python function `def divide(a, b): return a / b` raises ZeroDivisionError when b is 0 but should return None instead.",
    # "A binary search function returns -1 for a value that exists at index 0 in the list.",
    "A function that flattens a nested list fails with RecursionError on deeply nested input.",
    # "A function that counts word frequency in a string returns incorrect counts when words have mixed capitalisation.",
    """A merge_dicts() function combines multiple dictionaries. When it encounters list values with the same key, it extends the result list with new values. But the original data is being mutated.

Code:
def merge_dicts(dicts_list):
    result = {}
    for d in dicts_list:
        for key, value in d.items():
            if key not in result:
                result[key] = value
            else:
                if isinstance(value, list):
                    result[key].extend(value)
    return result

data = [{'items': [1, 2]}, {'items': [3, 4]}]
merged = merge_dicts(data)
print(data[0]['items'])  # BUG: prints [1, 2, 3, 4], should print [1, 2]

The original data is mutated when it should not be. The fix requires understanding reference semantics and why .extend() mutates the original list in-place.""",
]

# Allow testing different models: python run_diagnosis_benchmark.py <model_id>
model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen/qwen3-1.7b"

print(f"\nTesting with model: {model_id}\n")
for i, bug in enumerate(bugs, 1):
    r = run_diagnosis_skill(bug, model_id=model_id)
    print(f"{i}. BUG: {bug[:60]}...")
    print(
        f"   passed={r.passed}  phases={r.phases_found}"
        f"  vague_hyp={r.hypothesize_is_vague}"
        f"  trivial_verify={r.verify_is_trivial}"
    )
    print("   ---")