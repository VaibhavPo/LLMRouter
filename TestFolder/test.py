from skills.skill_runner import run_tdd_skill

model_id = ["nvidia/nemotron-3-nano-4b", "essentialai/rnj-1"]

for i in (model_id):
    r = run_tdd_skill(
        "Write a function that returns the nth Fibonacci number",
        model_id=i,
        
    )

    print(f"Write a function that returns the nth Fibonacci number")
    print(f"{i}")
    print(r.raw_response)