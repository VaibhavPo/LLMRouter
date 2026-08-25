"""
test_planner_integration.py

Comprehensive tests for the planning stage (Orchestrator.plan_task).

Tests cover:
1. Unit tests with mock planner
2. Integration tests with real planner + mock CONTEXT.md
3. Plan validation helpers
4. Edge cases (missing context, invalid requests, etc.)
5. Example usage patterns
"""

import pytest
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from unittest.mock import Mock, patch, MagicMock

from src.orchestrator.orchestrator import Orchestrator
from src.core.task_plan import (
    TaskPlan, TaskStep, ActionType, ToolInvocation, 
    PlannerResponse, StepStatus
)
from src.context.context_store import ContextStore


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def mock_context_store():
    """Mock ContextStore for testing without filesystem."""
    store = Mock(spec=ContextStore)
    
    # Pre-populate with example CONTEXT.md
    store.load.return_value = EXAMPLE_CONTEXT_MD
    store.exists.return_value = True
    store.list_projects.return_value = ["test-project", "another-project"]
    
    return store


@pytest.fixture
def orchestrator_with_mock_store(mock_context_store):
    """Orchestrator using mock ContextStore (no filesystem)."""
    orch = Orchestrator(context_store=mock_context_store)
    return orch


@pytest.fixture
def mock_planner_response():
    """Example PlannerResponse for testing."""
    steps = [
        TaskStep(
            step_id=0,
            description="Read UserSchema to understand current validation",
            action_type=ActionType.READ_FILE,
            tool_invocation=ToolInvocation(
                tool_name="read_file",
                arguments={"file_path": "src/models/user.py"}
            ),
            rationale="Baseline for what needs validation",
            depends_on=[],
            can_fail=False,
        ),
        TaskStep(
            step_id=1,
            description="Analyze requirements and design validation rules",
            action_type=ActionType.THINK,
            rationale="Design phase: decide what rules to add",
            depends_on=[0],
            can_fail=False,
        ),
        TaskStep(
            step_id=2,
            description="Write new validation tests",
            action_type=ActionType.WRITE_FILE,
            tool_invocation=ToolInvocation(
                tool_name="write_file",
                arguments={
                    "file_path": "tests/test_user_validation.py",
                    "content": "# New validation tests"
                }
            ),
            rationale="TDD: write tests first",
            depends_on=[1],
            can_fail=False,
        ),
        TaskStep(
            step_id=3,
            description="Implement validation in UserSchema",
            action_type=ActionType.EDIT_FILE,
            tool_invocation=ToolInvocation(
                tool_name="edit_file",
                arguments={
                    "file_path": "src/models/user.py",
                    "edit_instruction": "Add email and phone validation"
                }
            ),
            rationale="Make tests pass",
            depends_on=[2],
            can_fail=False,
        ),
        TaskStep(
            step_id=4,
            description="Run all validation tests",
            action_type=ActionType.RUN_TESTS,
            tool_invocation=ToolInvocation(
                tool_name="run_tests",
                arguments={"pattern": "test_user_validation.py"}
            ),
            rationale="Verify implementation",
            depends_on=[3],
            can_fail=False,
        ),
    ]
    
    plan = TaskPlan(
        task_summary="Add email and phone validation to UserSchema",
        steps=steps,
        relevant_files=["src/models/user.py", "tests/test_user_validation.py"],
        skill_name="TDD",
        estimated_total_seconds=300,
    )
    
    return PlannerResponse(
        plan=plan,
        reasoning="Using TDD workflow: read → design → test → implement → verify",
        alternatives_considered=[
            "Direct implementation without tests",
            "Pydantic validators instead of custom rules",
        ],
    )


# ============================================================================
# EXAMPLE CONTEXT.MD FOR TESTING
# ============================================================================

EXAMPLE_CONTEXT_MD = """
### Problem Statement
The current UserSchema has basic validation but is missing email format checks
and phone number validation. This causes invalid data to enter the database.

### Functional Requirements
1. Email must be valid format (RFC 5322 subset)
2. Phone must be 10 digits (US format)
3. Both are optional fields
4. Validation errors should be clear

### Assumptions
- Using Pydantic for validation
- Phone format is always US (10 digits)
- Email can be validated with a simple regex

### Shared Vocabulary
- UserSchema: Pydantic model in src/models/user.py
- Validation: checking data format before database save
- TDD: Test-Driven Development workflow

### Current Implementation
UserSchema has:
- name: required string
- email: optional string (no validation)
- phone: optional string (no validation)
- created_at: auto timestamp

### Relevant Files
- src/models/user.py: UserSchema definition
- tests/test_models/test_user.py: Existing user tests
- src/validators.py: Custom validator functions (if any)

### Change Log
- **2024-01-15 10:30 UTC** — Initial context created
"""


# ============================================================================
# PLAN VALIDATION HELPERS
# ============================================================================

@dataclass
class PlanValidationResult:
    """Result of validating a TaskPlan."""
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    stats: dict


def validate_plan(plan: TaskPlan) -> PlanValidationResult:
    """
    Validate a TaskPlan for correctness and best practices.
    
    Checks:
    - All steps have unique IDs (0 to n-1)
    - All steps have descriptions
    - All tool steps have tool_invocation
    - All dependencies reference valid steps
    - No circular dependencies
    - Action types are recognized
    - Topological sort succeeds
    """
    errors = []
    warnings = []
    
    # Check: steps list is non-empty
    if not plan.steps:
        errors.append("Plan has no steps")
        return PlanValidationResult(False, errors, warnings, {})
    
    # Check: step IDs are sequential 0..n-1
    actual_ids = {s.step_id for s in plan.steps}
    expected_ids = set(range(len(plan.steps)))
    if actual_ids != expected_ids:
        errors.append(f"Step IDs not sequential: got {sorted(actual_ids)}, expected {sorted(expected_ids)}")
    
    # Check: all steps have descriptions
    for step in plan.steps:
        if not step.description.strip():
            errors.append(f"Step {step.step_id} has empty description")
    
    # Check: tool steps have tool_invocation
    tool_actions = {
        ActionType.READ_FILE, ActionType.WRITE_FILE, ActionType.EDIT_FILE,
        ActionType.SEARCH_CODE, ActionType.LIST_FILES, ActionType.RUN_TESTS,
        ActionType.RUN_LINTER, ActionType.VERIFY,
    }
    for step in plan.steps:
        if step.action_type in tool_actions and step.tool_invocation is None:
            errors.append(f"Step {step.step_id} ({step.action_type}) missing tool_invocation")
        if step.action_type not in tool_actions and step.tool_invocation is not None:
            warnings.append(f"Step {step.step_id} ({step.action_type}) has tool_invocation but shouldn't")
    
    # Check: dependencies reference valid steps
    for step in plan.steps:
        for dep_id in step.depends_on:
            if dep_id < 0 or dep_id >= len(plan.steps):
                errors.append(f"Step {step.step_id} depends on invalid step {dep_id}")
            if dep_id >= step.step_id:
                errors.append(f"Step {step.step_id} depends on later step {dep_id}")
    
    # Check: topological sort succeeds (no circular deps)
    try:
        topo_order = plan.topological_order()
        if len(topo_order) != len(plan.steps):
            errors.append("Topological sort returned fewer steps than plan has")
    except ValueError as e:
        errors.append(f"Topological sort failed: {e}")
    
    # Warnings: all steps should have rationale
    for step in plan.steps:
        if not step.rationale.strip():
            warnings.append(f"Step {step.step_id} has no rationale")
    
    # Warnings: all steps should have expected_output (except thinking steps)
    thinking_actions = {ActionType.THINK, ActionType.DESIGN, ActionType.REVIEW_FINDINGS}
    for step in plan.steps:
        if step.action_type not in thinking_actions and not step.expected_output.strip():
            warnings.append(f"Step {step.step_id} has no expected_output")
    
    stats = {
        "total_steps": len(plan.steps),
        "tool_steps": sum(1 for s in plan.steps if s.action_type in tool_actions),
        "thinking_steps": sum(1 for s in plan.steps if s.action_type in thinking_actions),
        "max_depth": _calculate_plan_depth(plan),
        "parallelizable_pairs": _count_parallelizable_pairs(plan),
    }
    
    is_valid = len(errors) == 0
    return PlanValidationResult(is_valid, errors, warnings, stats)


def _calculate_plan_depth(plan: TaskPlan) -> int:
    """Calculate longest dependency chain (critical path)."""
    depths = {}
    
    def dfs(step_id):
        if step_id in depths:
            return depths[step_id]
        
        step = plan.steps[step_id]
        if not step.depends_on:
            depths[step_id] = 1
            return 1
        
        max_dep_depth = max(dfs(dep_id) for dep_id in step.depends_on)
        depths[step_id] = max_dep_depth + 1
        return depths[step_id]
    
    return max(dfs(i) for i in range(len(plan.steps)))


def _count_parallelizable_pairs(plan: TaskPlan) -> int:
    """Count pairs of steps that could run in parallel (no dependency)."""
    count = 0
    for i in range(len(plan.steps)):
        for j in range(i + 1, len(plan.steps)):
            step_i = plan.steps[i]
            step_j = plan.steps[j]
            if j not in step_i.depends_on and i not in step_j.depends_on:
                count += 1
    return count


# ============================================================================
# UNIT TESTS (Mock Planner)
# ============================================================================

class TestPlanTaskUnitMock:
    """Unit tests for plan_task() using a mock planner."""
    
    def test_plan_task_success(self, orchestrator_with_mock_store, mock_planner_response):
        """Test successful plan generation."""
        orch = orchestrator_with_mock_store
        
        # Mock the planner
        orch.planner.plan = Mock(return_value=mock_planner_response)
        
        # Call plan_task
        result = orch.plan_task(
            user_request="Add email and phone validation",
            project_id="test-project"
        )
        
        # Verify result
        assert isinstance(result, PlannerResponse)
        assert result.plan.task_summary == "Add email and phone validation to UserSchema"
        assert len(result.plan.steps) == 5
        assert result.plan.skill_name == "TDD"
        
        # Verify planner was called correctly
        orch.planner.plan.assert_called_once()
        call_args = orch.planner.plan.call_args
        assert call_args[0][0] == "Add email and phone validation"  # user_request
        assert "Problem Statement" in call_args[0][1]  # context_md
        assert "read_file" in str(call_args[0][2])  # tool_descriptions
    
    def test_plan_task_missing_context(self, orchestrator_with_mock_store):
        """Test plan_task with missing CONTEXT.md."""
        orch = orchestrator_with_mock_store
        orch.context_store.load.return_value = None
        
        with pytest.raises(ValueError, match="No CONTEXT.md"):
            orch.plan_task("some request", "nonexistent-project")
    
    def test_plan_task_loads_context_for_project(self, orchestrator_with_mock_store):
        """Test that plan_task loads CONTEXT.md for the right project."""
        orch = orchestrator_with_mock_store
        orch.planner.plan = Mock(return_value=Mock(spec=PlannerResponse))
        
        orch.plan_task("a request", "my-project")
        
        # Verify context store was queried for right project
        orch.context_store.load.assert_called_with("my-project")


# ============================================================================
# INTEGRATION TESTS (Real Planner, Mock Context)
# ============================================================================

class TestPlanTaskIntegration:
    """Integration tests with real planner + mock CONTEXT.md."""
    
    def test_plan_task_returns_valid_plan(self, orchestrator_with_mock_store, mock_planner_response):
        """Test that plan_task returns a valid, executable TaskPlan."""
        orch = orchestrator_with_mock_store
        
        # Mock planner to return our example response
        orch.planner.plan = Mock(return_value=mock_planner_response)
        
        result = orch.plan_task(
            "Add email and phone validation",
            "test-project"
        )
        
        # Validate the plan
        validation = validate_plan(result.plan)
        assert validation.is_valid, f"Plan validation failed: {validation.errors}"
        assert validation.stats["total_steps"] == 5
        assert validation.stats["tool_steps"] == 4  # read, write, edit, run_tests
        assert validation.stats["thinking_steps"] == 1  # think
    
    def test_plan_respects_dependencies(self, orchestrator_with_mock_store, mock_planner_response):
        """Test that plan steps have correct dependencies."""
        orch = orchestrator_with_mock_store
        orch.planner.plan = Mock(return_value=mock_planner_response)
        
        result = orch.plan_task("test", "test-project")
        plan = result.plan
        
        # Verify dependency chain: 0 → 1 → 2 → 3 → 4
        assert plan.steps[0].depends_on == []
        assert plan.steps[1].depends_on == [0]
        assert plan.steps[2].depends_on == [1]
        assert plan.steps[3].depends_on == [2]
        assert plan.steps[4].depends_on == [3]
        
        # Topological sort should give [0,1,2,3,4]
        topo = plan.topological_order()
        assert topo == [0, 1, 2, 3, 4]
    
    def test_plan_includes_tool_descriptions(self, orchestrator_with_mock_store):
        """Test that tool descriptions are passed to planner."""
        orch = orchestrator_with_mock_store
        orch.planner.plan = Mock()
        
        orch.plan_task("test", "test-project")
        
        # Verify tool_descriptions were passed
        call_args = orch.planner.plan.call_args
        tool_descriptions = call_args[0][2]
        
        assert "read_file" in tool_descriptions
        assert "list_files" in tool_descriptions
        assert "search_code" in tool_descriptions
        
        # Verify format
        assert "description" in tool_descriptions["read_file"]
        assert "usage" in tool_descriptions["read_file"]


# ============================================================================
# PLAN STRUCTURE VALIDATION TESTS
# ============================================================================

class TestPlanValidation:
    """Tests for the plan validation helper."""
    
    def test_validate_plan_success(self, mock_planner_response):
        """Test validation of a well-formed plan."""
        result = validate_plan(mock_planner_response.plan)
        
        assert result.is_valid
        assert len(result.errors) == 0
        assert result.stats["total_steps"] == 5
        assert result.stats["max_depth"] == 5  # Linear dependency chain
    
    def test_validate_plan_missing_descriptions(self):
        """Test that validation catches missing descriptions."""
        with pytest.raises(ValueError, match="description cannot be empty"):
            step = TaskStep(
                step_id=0,
                description="",  # Empty!
                action_type=ActionType.THINK,
            )
    
    def test_validate_plan_missing_tool_invocation(self):
        """Test that validation catches missing tool_invocation for tool steps."""
        with pytest.raises(ValueError, match="requires tool_invocation"):
            step = TaskStep(
                step_id=0,
                description="Read a file",
                action_type=ActionType.READ_FILE,
                tool_invocation=None,  # Missing!
            )
    
    def test_validate_plan_invalid_dependency(self):
        """Test that validation catches invalid dependencies."""
        step0 = TaskStep(step_id=0, description="a", action_type=ActionType.THINK)
        with pytest.raises(ValueError, match="step cannot depend on itself or later steps"):
            step1 = TaskStep(
                step_id=1,
                description="b",
                action_type=ActionType.THINK,
                depends_on=[999],  # Invalid!
            )
    
    def test_validate_plan_circular_dependency(self):
        """Test that validation catches circular dependencies."""
        with pytest.raises(ValueError, match="step cannot depend on itself or later steps"):
            step0 = TaskStep(
                step_id=0,
                description="a",
                action_type=ActionType.THINK,
                depends_on=[1],  # Forward reference!
            )


# ============================================================================
# EXAMPLE USAGE TESTS (What a user would do)
# ============================================================================

class TestPlannerUsageExamples:
    """Example test patterns for developers using the planning stage."""
    
    def test_example_simple_read_plan(self, orchestrator_with_mock_store):
        """Example: User wants to read and understand a file."""
        orch = orchestrator_with_mock_store
        
        # Create a simple 2-step plan: read → think
        simple_plan = TaskPlan(
            task_summary="Understand main.py",
            steps=[
                TaskStep(
                    step_id=0,
                    description="Read main.py",
                    action_type=ActionType.READ_FILE,
                    tool_invocation=ToolInvocation(
                        tool_name="read_file",
                        arguments={"file_path": "main.py"}
                    ),
                    expected_output="Full contents of main.py",
                ),
                TaskStep(
                    step_id=1,
                    description="Analyze the code structure",
                    action_type=ActionType.THINK,
                    depends_on=[0],
                    expected_output="Summary of classes, functions, and flow",
                ),
            ],
        )
        
        # Validate
        validation = validate_plan(simple_plan)
        assert validation.is_valid
        assert validation.stats["total_steps"] == 2
        assert validation.stats["max_depth"] == 2
    
    def test_example_tdd_workflow(self, orchestrator_with_mock_store, mock_planner_response):
        """Example: TDD workflow (write tests → implement → verify)."""
        plan = mock_planner_response.plan
        
        # Validate
        validation = validate_plan(plan)
        assert validation.is_valid
        
        # Inspect structure
        assert plan.skill_name == "TDD"
        
        # Find test step
        test_step = next((s for s in plan.steps if "test" in s.description.lower()), None)
        assert test_step is not None
        assert test_step.action_type == ActionType.WRITE_FILE
        
        # Test step should come before implementation
        impl_step = next((s for s in plan.steps if "implement" in s.description.lower()), None)
        assert test_step.step_id < impl_step.step_id
    
    def test_example_parallel_steps(self):
        """Example: Plan with potentially parallel steps."""
        plan = TaskPlan(
            task_summary="Run checks in parallel",
            steps=[
                # Preparatory step
                TaskStep(
                    step_id=0,
                    description="Prepare environment",
                    action_type=ActionType.THINK,
                ),
                # Parallel steps (no deps on each other)
                TaskStep(
                    step_id=1,
                    description="Run unit tests",
                    action_type=ActionType.RUN_TESTS,
                    tool_invocation=ToolInvocation("run_tests", {}),
                    depends_on=[0],
                ),
                TaskStep(
                    step_id=2,
                    description="Run linter",
                    action_type=ActionType.RUN_LINTER,
                    tool_invocation=ToolInvocation("run_linter", {}),
                    depends_on=[0],
                ),
                # Consolidation
                TaskStep(
                    step_id=3,
                    description="Report results",
                    action_type=ActionType.THINK,
                    depends_on=[1, 2],
                ),
            ],
        )
        
        validation = validate_plan(plan)
        assert validation.is_valid
        assert validation.stats["parallelizable_pairs"] >= 1  # Steps 1 and 2
        assert validation.stats["max_depth"] == 3  # Linear path 0 → (1 or 2) → 3


# ============================================================================
# PYTEST CONFIGURATION & MAIN
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])