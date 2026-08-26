"""
prompt_rules.py

Single source of truth for planning-discipline text shared between the
initial Planner (planner_v2/prompts.py) and the replanners
(executor/replanner.py). 

Why this exists: DefaultPromptBuilder's system_prompt() originally had
the only copy of the edit_file safety rules. LocalReplanner and
FullReplanner had their own much thinner prompts, which meant every
replan (local or full) was planning with strictly less discipline than
the first plan a task ever got. Two separate incidents came from this
gap: a FullReplanner using write_file to "fix" an existing file (wiping
it), and a FullReplanner/LocalReplanner emitting tool_invocation with
empty arguments (missing file_path). Both are now covered below, and
BOTH callers import from here so a future third gap can't reappear the
same way -- fix it once, in one place.
"""

EDIT_DISCIPLINE_RULES = """
CRITICAL FILE-SAFETY RULES:

- If a file already exists and has been read (via read_file/search_code) in
  a completed step below, you MUST use edit_file to modify it, never
  write_file. write_file OVERWRITES THE ENTIRE FILE -- using it on an
  existing file destroys all of its current content except what you put in
  the new "content" argument.
- Only use write_file for files that do not exist yet.
- edit_file requires old_str to be an EXACT substring of the file's actual
  current content (from a read_file/search_code step's evidence below).
  Never invent old_str from imagination or from what CONTEXT.md implies
  the file should look like.
- If you don't yet know the exact current content of a file you need to
  edit, add a read_file step first, before any edit_file step for that
  file.
"""

TOOL_ARGS_SCHEMA = """
REQUIRED tool_invocation.arguments PER TOOL -- never omit these:

- read_file:   {"file_path": "..."}                            (file_path is REQUIRED)
- search_code: {"pattern": "...", "path": "..."}                (pattern is REQUIRED)
- list_files:  {"path": "..."}                                  (path optional, defaults to ".")
- write_file:  {"file_path": "...", "content": "..."}           (both REQUIRED)
- edit_file:   {"file_path": "...", "old_str": "...", "new_str": "..."}  (all three REQUIRED)
- run_tests:   {"test_path": "..."}                              (optional, defaults to "tests")

Every step whose action_type uses a tool MUST include a complete
tool_invocation.arguments matching the tool it names. An empty {} or a
missing required key will cause the step to fail immediately at
execution time before it ever runs.
"""

# Convenience: both blocks together, for callers that want the full
# planning-safety package in one insertion point.
PLANNING_SAFETY_RULES = EDIT_DISCIPLINE_RULES + "\n" + TOOL_ARGS_SCHEMA


# Required-argument table used by plan_serde.py at parse time to fail
# loud on a malformed tool_invocation, rather than letting it reach
# execution. Kept here (not duplicated in plan_serde.py) so the prompt
# text above and the actual validation logic can never drift apart --
# if you add a tool or change its required args, this is the one place
# to edit.
REQUIRED_TOOL_ARGS: dict[str, list[str]] = {
    "read_file": ["file_path"],
    "search_code": ["pattern"],
    "write_file": ["file_path", "content"],
    "edit_file": ["file_path", "old_str", "new_str"],
}