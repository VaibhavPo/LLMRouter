# Diagnosing Bugs Skill: Minimize → Hypothesize → Instrument → Fix → Verify

Follow this exact procedure for the bug described below.
Do not skip any phase. Do not merge two phases under one header.
Emit each phase under its own header, in this exact order,
using these exact header strings:

## MINIMIZE
Reduce the failing case to the smallest possible example that still
reproduces the bug. Show the minimal code snippet and the exact error
or wrong output it produces. If the description already gives a minimal
case, state that explicitly and show it.

## HYPOTHESIZE
State at least two specific, concrete candidate root causes for the bug.
Each hypothesis must be a falsifiable claim — not "something might be
wrong" but "X fails because Y, which would cause Z." Do NOT propose
any fix in this section.

## INSTRUMENT
For each hypothesis from HYPOTHESIZE, describe exactly what diagnostic
code you would add (print statements, assertions, logging, a specific
test) to confirm or rule it out. Show the diagnostic code. Do NOT
implement the actual fix in this section — only diagnostic additions.

## FIX
Now apply the fix that the evidence from INSTRUMENT supports. Explain
which hypothesis the instrumentation would have confirmed, and show
the corrected code. Remove any diagnostic code added in INSTRUMENT.

## VERIFY
Write a specific regression test (using assert or a test function) that
would catch this exact bug if it were reintroduced. The test must fail
on the buggy version and pass on the fixed version. "Run the tests
again" is not acceptable here.