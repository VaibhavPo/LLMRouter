"""
Phase 7d: Step Executor Implementations
Concrete implementations for executing different action types.

Each ActionType has a corresponding executor:
- ToolStepExecutor: READ_FILE, WRITE_FILE, SEARCH_CODE, etc.
- ThinkStepExecutor: THINK, DESIGN (LLM reasoning steps)
- SkillStepExecutor: SKILL_WORKFLOW (run TDD, Diagnosis, etc.)
- VerifyStepExecutor: RUN_TESTS, VERIFY

All follow the StepExecutor interface: execute(step, plan, context) → str
"""

from abc import ABC
from typing import Any, Dict, Optional, List
from src.core.executor.interfaces import (
    StepExecutor,
    ContextManager,
    StepExecutionError,
    Logger,
)

import re

_STEP_OUTPUT_PATTERN = re.compile(r"\{\{step_output:(\d+)\}\}")


def _resolve_step_output_placeholders(arguments: dict, context: ContextManager) -> dict:
    """
    Resolve `{{step_output:N}}` placeholders inside tool_invocation.arguments
    with the actual output of step N, pulled from ContextManager.

    This is the wiring that lets a THINK/DESIGN step's result actually reach
    a later WRITE_FILE/EDIT_FILE/RUN_TESTS step. Without it, THINK executes
    and its output is stored but never consumed — the planner is forced to
    inline full content at plan-generation time instead, which defeats the
    point of having a separate thinking step at all.
    """
    resolved = {}
    for key, value in arguments.items():
        if isinstance(value, str) and _STEP_OUTPUT_PATTERN.search(value):
            def _replace(match):
                step_id = int(match.group(1))
                try:
                    return context.get_step_output(step_id)
                except Exception:
                    raise StepExecutionError(
                        f"Argument '{key}' references step_output:{step_id}, "
                        f"but that step has no recorded output (it may not "
                        f"have run yet, or produced nothing — check depends_on)"
                    )
            resolved[key] = _STEP_OUTPUT_PATTERN.sub(_replace, value)
        else:
            resolved[key] = value
    return resolved


# ============================================================================
# TOOL STEP EXECUTOR
# ============================================================================

class ToolStepExecutor(StepExecutor):
    """
    Execute a step that calls a tool (read_file, write_file, etc.).

    Delegates to ToolRegistry.execute() to perform the actual tool call.
    Handles error checking and output formatting.
    """

    def __init__(self, tool_runtime):
        """
        Initialize with a ToolRegistry.

        Args:
            tool_runtime: ToolRegistry instance from src/core/tool_runtime.py
        """
        self.tool_runtime = tool_runtime

    def execute(self, step, plan, context: ContextManager) -> str:
        """
        Execute a tool-based step.
        """
        if not step.tool_invocation:
            raise StepExecutionError(f"Step {step.step_id}: No tool invocation specified")

        from src.tools.schemas import ToolRequest

        resolved_arguments = _resolve_step_output_placeholders(
            step.tool_invocation.arguments, context
        )

        tool_request = ToolRequest(
            tool_name=step.tool_invocation.tool_name,
            arguments=resolved_arguments,
        )

        try:
            result = self.tool_runtime.execute(tool_request)
        except Exception as e:
            raise StepExecutionError(f"Tool execution failed: {e}")

        if not result.success:
            raise StepExecutionError(f"Tool failed: {result.error}")

        return result.output

# ============================================================================
# THINK STEP EXECUTOR
# ============================================================================

class ThinkStepExecutor(StepExecutor):
    """
    Execute a thinking step (THINK, DESIGN, REVIEW_FINDINGS).
    
    Calls an LLM to reason through a problem step-by-step, incorporating
    outputs from previous steps.
    """

    def __init__(self, model_provider):
        """
        Initialize with an LLMProvider.
        
        Args:
            model_provider: LLMProvider instance (e.g., LMStudioProvider)
        """
        self.model_provider = model_provider

    def execute(self, step, plan, context: ContextManager) -> str:
        """
        Execute a thinking step.
        
        Args:
            step: TaskStep with description (reasoning task)
            plan: Full TaskPlan
            context: ContextManager (to access previous findings)
        
        Returns:
            LLM's reasoning output
        
        Raises:
            StepExecutionError: If model call fails
        """
        # Build prompt incorporating previous step outputs
        prompt = self._build_thinking_prompt(step, context)

        # Call model with reasoning parameters
        try:
            response = self.model_provider.call(
                system_prompt=(
                    "You are a careful reasoner. Think through the problem step-by-step, "
                    "considering the context provided. Be precise and thorough."
                ),
                user_prompt=prompt,
                temperature=0.1,  # Low temp: precise, not creative
                max_tokens=1024,
            )
        except Exception as e:
            raise StepExecutionError(f"Model call failed: {e}")

        return response

    def _build_thinking_prompt(self, step, context: ContextManager) -> str:
        """
        Build a prompt for the thinking step that includes context.
        
        Args:
            step: The TaskStep
            context: ContextManager with previous outputs
        
        Returns:
            Full prompt including task + previous findings
        """
        # Gather outputs from all dependencies
        previous_outputs = context.get_outputs_for_steps(step.depends_on)

        # Format them nicely
        previous_section = ""
        for dep_step_id, output in previous_outputs.items():
            truncated = (output[:200] + "...") if len(output) > 200 else output
            previous_section += f"Step {dep_step_id}:\n{truncated}\n\n"

        # Build full prompt
        prompt = f"""Task: {step.description}

Previous findings:
{previous_section if previous_section else "(No dependencies)"}

Reason through this carefully. Consider all the information above."""

        return prompt


# ============================================================================
# SKILL STEP EXECUTOR
# ============================================================================

class SkillStepExecutor(StepExecutor):
    """
    Execute a skill workflow step (SKILL_WORKFLOW).
    
    Routes to a skill (TDD, Diagnosis, etc.) and runs it with gathered context.
    """

    def __init__(self, skill_factory):
        """
        Initialize with a SkillFactory.
        
        Args:
            skill_factory: SkillFactory instance from src/skills/skill_factory.py
        """
        self.skill_factory = skill_factory

    def execute(self, step, plan, context: ContextManager) -> str:
        """
        Execute a skill workflow.
        
        Args:
            step: TaskStep with skill workflow action
            plan: Full TaskPlan (contains skill_name)
            context: ContextManager (for gathering skill context)
        
        Returns:
            Skill output
        
        Raises:
            StepExecutionError: If skill execution fails
        """
        if not plan.skill_name:
            raise StepExecutionError(f"Step {step.step_id}: No skill specified in plan")

        # Gather context for the skill
        # Previous steps may have read files, searched code, etc.
        # Skill needs access to those findings
        previous_outputs = context.get_outputs_for_steps(step.depends_on)

        # Run the skill
        try:
            result = self.skill_factory.run_skill(
                skill_name=plan.skill_name,
                request=step.description,
                context_md=previous_outputs,  # Pass previous findings
            )
        except Exception as e:
            raise StepExecutionError(f"Skill execution failed: {e}")

        # Check if skill validation passed
        if not result.passed:
            raise StepExecutionError(f"Skill validation failed: {result.feedback}")

        return result.output


# ============================================================================
# VERIFY STEP EXECUTOR
# ============================================================================

class VerifyStepExecutor(StepExecutor):
    """
    Execute a verification step (RUN_TESTS, VERIFY, RUN_LINTER).

    Runs tests or verification tools and reports results.
    """

    def __init__(self, tool_runtime):
        """
        Initialize with a ToolRegistry.

        Args:
            tool_runtime: ToolRegistry instance
        """
        self.tool_runtime = tool_runtime

    def execute(self, step, plan, context: ContextManager) -> str:
        """
        Execute verification.
        """
        if not step.tool_invocation:
            raise StepExecutionError(f"Step {step.step_id}: No tool invocation for verification")

        from src.tools.schemas import ToolRequest

        resolved_arguments = _resolve_step_output_placeholders(
            step.tool_invocation.arguments, context
        )

        result = self.tool_runtime.execute(
            ToolRequest(
                tool_name=step.tool_invocation.tool_name,
                arguments=resolved_arguments,
            )
        )

        if not result.success:
            raise StepExecutionError(f"Verification failed: {result.output}")

        return result.output


# ============================================================================
# FACTORY
# ============================================================================

class DefaultStepExecutorFactory:
    """
    Concrete factory for creating step executors.
    
    Maps ActionType → appropriate StepExecutor implementation.
    """

    def __init__(self, tool_runtime, model_provider, skill_factory):
        """
        Initialize the factory.
        
        Args:
            tool_runtime: ToolRegistry
            model_provider: LLMProvider
            skill_factory: SkillFactory
        """
        self.tool_runtime = tool_runtime
        self.model_provider = model_provider
        self.skill_factory = skill_factory

    def create(self, action_type) -> StepExecutor:
        """
        Create the right executor for an action type.
        
        Args:
            action_type: ActionType enum
        
        Returns:
            Appropriate StepExecutor instance
        
        Raises:
            ValueError: If action type is unknown
        """
        # Import ActionType when needed to avoid circular imports
        from src.core.task_plan import ActionType 
        # Tool-based actions
        if action_type in {
            ActionType.READ_FILE,
            ActionType.WRITE_FILE,
            ActionType.SEARCH_CODE,
            ActionType.EDIT_FILE,
            ActionType.LIST_FILES,
            ActionType.RUN_TESTS,
        }:
            return ToolStepExecutor(self.tool_runtime)

        # Thinking steps
        elif action_type in {ActionType.THINK, ActionType.DESIGN, ActionType.REVIEW_FINDINGS}:
            return ThinkStepExecutor(self.model_provider)

        # Skill steps
        elif action_type == ActionType.SKILL_WORKFLOW:
            return SkillStepExecutor(self.skill_factory)

        # Verification steps
        elif action_type in {ActionType.VERIFY, ActionType.RUN_LINTER}:
            return VerifyStepExecutor(self.tool_runtime)

        else:
            raise ValueError(f"Unknown action type: {action_type}")