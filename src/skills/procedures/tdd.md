# TDD Skill: Red-Green-Refactor

Follow this exact procedure for the task below. Do not skip any phase.
Emit each phase under its own header, in this exact order, using these
exact header strings:

## RED
Write a single failing test using Python's `assert` statement (or a
`unittest`/`pytest`-style test function). The test must call the function
being requested and assert its expected output for at least one concrete
example. Do NOT define or implement the function itself in this section —
only the test that will fail because the function doesn't exist yet.

## GREEN
Write the minimal implementation needed to make the RED test pass. Do not
add behavior beyond what the test in RED actually requires.

## REFACTOR
Review the implementation and test for clarity or duplication. If changes
are needed, show the refactored version. If nothing needs to change, write
exactly: "No refactor needed."

Rules:
- Do not put implementation code under the RED header.
- Do not merge two phases under one header.
- Do not omit the REFACTOR header even if there is nothing to refactor.