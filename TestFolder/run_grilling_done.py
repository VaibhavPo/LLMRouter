from skills.grilling_runner import GrillingRunner

runner = GrillingRunner()

# Start
msg = runner.start_interview("Build a social media feed app")
print(f"Q{msg.ask_count}: {msg.question}\n")

# Continue (simulate user typing)
for i in range(5):
    user_input = input("Your answer: ")
    if not user_input.strip():
        break
    msg = runner.continue_interview(user_input)
    print(f"Q{msg.ask_count}: {msg.question}\n")
    if msg.is_finalizing:
        print("Model is ready to finalize. Ending interview.")
        break

# Finalize
result = runner.finalize()
print("=== CONTEXT.md ===")
print(result.context_md)
print(f"\n=== Interview Stats ===")
print(f"Total questions: {result.ask_count}")
print(f"Successfully finalized: {result.successfully_finalized}")