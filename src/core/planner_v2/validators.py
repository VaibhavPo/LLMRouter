# src/core/planner_v2/validators.py
"""Plan validation."""
# src/core/planner_v2/validators.py
"""Plan validators."""

from .interfaces import PlanValidator


class TaskPlanValidator(PlanValidator):
    """Validate TaskPlan dict structure."""
    
    def validate(self, plan_dict: dict) -> None:
        """Validate plan structure."""
        # Check required fields
        if "task_summary" not in plan_dict:
            raise ValueError("Missing 'task_summary'")
        
        if "steps" not in plan_dict:
            raise ValueError("Missing 'steps'")
        
        steps = plan_dict["steps"]
        if not isinstance(steps, list):
            raise ValueError("'steps' must be a list")
        
        if not steps:
            raise ValueError("Plan must have at least one step")
        
        # Validate each step
        for i, step in enumerate(steps):
            self._validate_step(step, i)
    
    def _validate_step(self, step: dict, index: int) -> None:
        """Validate a single step."""
        if "step_id" not in step:
            raise ValueError(f"Step {index}: missing 'step_id'")
        
        if step["step_id"] != index:
            raise ValueError(f"Step {index}: step_id must be {index}, got {step['step_id']}")
        
        if "description" not in step:
            raise ValueError(f"Step {index}: missing 'description'")
        
        if "action_type" not in step:
            raise ValueError(f"Step {index}: missing 'action_type'")


class NoopValidator(PlanValidator):
    """Validator that accepts anything (for testing)."""
    
    def validate(self, plan_dict: dict) -> None:
        pass