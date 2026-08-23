from src.core.router import route, TaskType
from src.core.client import run

model_id = route(TaskType.SIMPLE_CODE)
print(f"Routed to: {model_id}")

response = run(model_id, "Write a Python function that reverses a string.")
print("---- Response ----")
print(response)