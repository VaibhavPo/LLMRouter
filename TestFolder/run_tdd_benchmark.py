from src.skills.skill_loader import run_tdd_skill

tasks = [
    "Write a function that checks if a string is a palindrome",
    "Write a function that returns the nth Fibonacci number",
    "Write a function that merges two sorted lists into one sorted list",
    "Write a function that validates whether a string is a valid email address",
]

for t in tasks:
    r = run_tdd_skill(t, model_id="essentialai/rnj-1")  # swap model here to compare
    print(f"TASK: {t}")
    print(
        f"  passed={r.passed}  phases={r.phases_found}"
        f"  stub_red={r.red_phase_looks_like_stub}"
        f"  trivial_green={r.green_phase_looks_trivial}"  # NEW
    )
    print("  ---")