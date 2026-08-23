# src/core/planner_v2/prompts.py
"""Prompt management."""
# src/core/planner_v2/prompts.py
"""Prompt templates and builders."""

from .interfaces import PromptBuilder


class DefaultPromptBuilder(PromptBuilder):
    """Standard prompt for task planning."""
    
    def system_prompt(self) -> str:
        return """You are a meticulous task planner. Given a user request and project context,
decompose the work into an ordered sequence of concrete steps.

## Your Job
1. Understand what the user wants
2. Read/search the codebase to understand the current state
3. Plan the exact steps needed (thinking, reading, coding, testing)
4. Output a structured TaskPlan as JSON

## Keys to Good Planning
- Use tools surgically: read_file(start_line=X, end_line=Y)
- Gather info first: search_code and read_file before coding
- Identify patterns: look for how similar problems are solved
- Explicit dependencies: if step B needs output from step A, mark: depends_on=[A]
- Estimate time: reads=2-3s, searches=2-5s, thinking=5-10s, coding=10-20s
- One tool per step: don't combine multiple tools

## ActionType Reference
- read_file, search_code, list_files, analyze_context
- think, design, review_findings
- write_file, edit_file, refactor
- run_tests, run_linter, verify
- skill_workflow

## Output Format
Return ONLY valid JSON matching TaskPlan schema. No preamble, no markdown."""
    
    def build_user_prompt(
        self,
        user_request: str,
        context_md: str,
        tool_descriptions: dict,
    ) -> str:
        tool_list = "\n".join([
            f"- {name}: {info['description']}"
            for name, info in tool_descriptions.items()
        ])
        
        return f"""USER REQUEST: {user_request}

PROJECT CONTEXT:
{context_md}

AVAILABLE TOOLS:
{tool_list}

Plan the exact steps needed. Output TaskPlan JSON."""


class DiagnosisPromptBuilder(PromptBuilder):
    """Specialized prompt for diagnosis/debugging tasks."""
    
    def system_prompt(self) -> str:
        return """You are an expert debugger. When given a problem, you:
1. Minimize: narrow down the exact cause
2. Hypothesize: what's going wrong?
3. Instrument: add diagnostics
4. Fix: apply the fix
5. Verify: confirm it works

Output a TaskPlan that follows this diagnostic approach."""
    
    def build_user_prompt(
        self,
        user_request: str,
        context_md: str,
        tool_descriptions: dict,
    ) -> str:
        return f"""PROBLEM: {user_request}

CONTEXT:
{context_md}

Plan a diagnosis approach using: minimize → hypothesize → instrument → fix → verify."""


class TDDPromptBuilder(PromptBuilder):
    """Specialized prompt for TDD tasks."""
    
    def system_prompt(self) -> str:
        return """You are a TDD expert. For every feature:
1. RED: write failing test
2. GREEN: write minimal implementation
3. REFACTOR: improve code

Output a TaskPlan following strict red-green-refactor discipline."""
    
    def build_user_prompt(
        self,
        user_request: str,
        context_md: str,
        tool_descriptions: dict,
    ) -> str:
        return f"""FEATURE: {user_request}

CONTEXT:
{context_md}

Plan a TDD approach: RED test → GREEN implementation → REFACTOR."""