"""
Phase 7d: Main Executor Class
Orchestrates execution of TaskPlans.

The Executor reads a TaskPlan and executes it step-by-step:
1. Respects dependencies (topological ordering)
2. Dispatches each step to the right executor
3. Manages context passing between steps
4. Handles failures gracefully
5. Logs everything for audit/debugging

This is the orchestrator layer. It doesn't execute steps itself; it delegates
to StepExecutors. This follows the SOLID principle (Single Responsibility).
"""

from typing import Dict, List, Optional, Set
from dataclasses import field
from src.core.executor.interfaces import (
    StepExecutor,
    ContextManager,
    Logger,
    StepExecutorFactory,
    ExecutionResult,
    ExecutionError,
    StepExecutionError,
    StepStatus,
    DependencyError,
)
import time


class Executor:
    """
    Orchestrator for executing TaskPlans.
    
    Responsibilities:
    1. Load a TaskPlan
    2. Get execution order (respecting dependencies)
    3. For each step in order:
       a. Check if dependencies are satisfied
       b. Get the right StepExecutor for this action type
       c. Execute the step (with timeout)
       d. Handle success/failure
       e. Store output in context for dependent steps
    4. Return ExecutionResult with all outcomes
    
    Design: Loosely coupled.
    - Depends on interfaces, not implementations
    - Delegates execution to StepExecutors
    - No implementation-specific logic
    """

    def __init__(
        self,
        step_executor_factory: StepExecutorFactory,
        context_manager: ContextManager,
        logger: Logger,
        max_retries: int = 1,
        timeout_per_step: int = 300,
    ):
        """
        Initialize the executor.
        
        Args:
            step_executor_factory: Factory for creating step executors
            context_manager: Manager for step outputs
            logger: Logger for audit trail
            max_retries: Max retries per failed step
            timeout_per_step: Timeout per step in seconds
        """
        self.step_executor_factory = step_executor_factory
        self.context = context_manager
        self.logger = logger
        self.max_retries = max_retries
        self.timeout_per_step = timeout_per_step

    def execute(self, plan) -> ExecutionResult:
        """
        Execute a TaskPlan.
        
        Args:
            plan: TaskPlan to execute
        
        Returns:
            ExecutionResult with outcomes
        
        Raises:
            ExecutionError: If execution fails critically
        """
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"EXECUTION START: {plan.task_summary}")
        self.logger.info(f"{'='*60}")

        # Get execution order (respects dependencies)
        try:
            order = plan.topological_order()
            self.logger.debug(f"Execution order: {order}")
        except ValueError as e:
            raise DependencyError(f"Plan has circular dependencies: {e}")

        completed_steps: Set[int] = set()
        failed_steps: Set[int] = set()
        skipped_steps: Set[int] = set()
        errors: Dict[int, str] = {}

        # Execute each step in dependency order
        for step_id in order:
            step = plan.steps[step_id]

            # Check dependencies
            if not self._are_dependencies_satisfied(step, completed_steps, failed_steps):
                step.status = StepStatus.SKIPPED
                skipped_steps.add(step_id)
                self.logger.info(f"Step {step_id}: Skipped (dependency not ready)")
                continue

            # Execute the step
            try:
                self._execute_step(step, plan)
                completed_steps.add(step_id)

            except StepExecutionError as e:
                error_msg = str(e)
                errors[step_id] = error_msg
                failed_steps.add(step_id)

                self.logger.error(f"Step {step_id}: FAILED — {error_msg}")

                # Decide: retry? skip? abort?
                if self._should_retry(step, failed_steps):
                    self.logger.info(f"Retrying step {step_id}...")
                    # TODO: Implement retry logic
                    pass
                elif self._can_skip(step):
                    self.logger.info(f"Skipping step {step_id} (can_fail=True)")
                    skipped_steps.add(step_id)
                else:
                    self.logger.error(f"Aborting: step {step_id} failed and cannot skip")
                    raise ExecutionError(f"Step {step_id} failed: {error_msg}")

        # Done
        self.logger.info(f"\n{'='*60}")
        self.logger.info("EXECUTION COMPLETE")
        self.logger.info(f"{'='*60}")

        return ExecutionResult(
            plan=plan,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            skipped_steps=skipped_steps,
            context_snapshot=self.context.snapshot(),
            errors=errors,
        )

    def _execute_step(self, step, plan) -> None:
        """
        Execute a single step.
        
        Args:
            step: TaskStep to execute
            plan: Full TaskPlan (for reference)
        
        Raises:
            StepExecutionError: If execution fails
        """
        self.logger.info(f"\nExecuting step {step.step_id}: {step.description}")
        step.status = StepStatus.IN_PROGRESS
        start_time = time.time()

        try:
            # Get the right executor for this action type
            executor: StepExecutor = self.step_executor_factory.create(step.action_type)

            # Execute with timeout (simplified: no actual timeout yet)
            result = executor.execute(step, plan, self.context)

            # Success
            step.actual_output = result
            step.status = StepStatus.COMPLETED

            # Store in context for later steps
            self.context.set_step_output(step.step_id, result)

            elapsed = time.time() - start_time
            self.logger.info(f"✅ Step {step.step_id}: Completed in {elapsed:.2f}s")
            self.logger.debug(f"Output preview: {result[:100]}...")

        except Exception as e:
            elapsed = time.time() - start_time
            raise StepExecutionError(
                f"Step {step.step_id} execution failed after {elapsed:.2f}s: {e}"
            )

    def _are_dependencies_satisfied(
        self,
        step,
        completed_steps: Set[int],
        failed_steps: Set[int],
    ) -> bool:
        """
        Check if all dependencies of a step are satisfied.
        
        A dependency is satisfied if:
        - The dependency step is completed, OR
        - The dependency step failed but can_fail=True
        
        Args:
            step: TaskStep to check
            completed_steps: Set of completed step IDs
            failed_steps: Set of failed step IDs
        
        Returns:
            True if all dependencies satisfied
        """
        for dep_id in step.depends_on:
            if dep_id not in completed_steps and dep_id not in failed_steps:
                # Dependency not done yet
                return False
            
            if dep_id in failed_steps:
                # Dependency failed; check if it can fail
                dep_step = None  # TODO: Get from plan
                if dep_step and not dep_step.can_fail:
                    return False

        return True

    def _should_retry(self, step, failed_steps: Set[int]) -> bool:
        """
        Decide if we should retry a failed step.
        
        For now: simple policy
        - No retries for programming errors
        - Could retry for transient errors (network, timeout)
        
        Args:
            step: Failed TaskStep
            failed_steps: Set of all failed steps (for context)
        
        Returns:
            True if retry is allowed
        """
        # Simple policy: no retries yet
        # Could enhance with error type checking
        return False

    def _can_skip(self, step) -> bool:
        """
        Decide if we can skip a failed step.
        
        Args:
            step: Failed TaskStep
        
        Returns:
            True if step can be skipped without aborting
        """
        return step.can_fail


# ============================================================================
# BUILDER / CONFIGURATION
# ============================================================================

class ExecutorBuilder:
    """
    Builder for creating configured Executor instances.
    
    Handles wiring all dependencies (factory, context manager, logger).
    """

    def __init__(self, tool_runtime, logger=None):
        """
        Initialize the builder.
        
        Args:
            tool_runtime: ToolRegistry instance
            logger: Optional Logger (uses ConsoleLogger if None)
        """
        self.tool_runtime = tool_runtime
        self.logger = logger or ConsoleLogger()

    def build(self, model_provider, skill_factory) -> Executor:
        """
        Build a standard Executor.
        
        Args:
            model_provider: LLMProvider for THINK steps
            skill_factory: SkillFactory for SKILL_WORKFLOW steps
        
        Returns:
            Configured Executor instance
        """
        from step_executor import DefaultStepExecutorFactory
        from context_manager import PlanExecutionContext

        step_executor_factory = DefaultStepExecutorFactory(
            tool_runtime=self.tool_runtime,
            model_provider=model_provider,
            skill_factory=skill_factory,
        )

        context_manager = PlanExecutionContext()

        return Executor(
            step_executor_factory=step_executor_factory,
            context_manager=context_manager,
            logger=self.logger,
            max_retries=1,
            timeout_per_step=300,
        )

    def build_with_timeout(self, model_provider, skill_factory, timeout: int) -> Executor:
        """
        Build an Executor with custom timeout.
        
        Args:
            model_provider: LLMProvider
            skill_factory: SkillFactory
            timeout: Timeout per step in seconds
        
        Returns:
            Configured Executor with custom timeout
        """
        executor = self.build(model_provider, skill_factory)
        executor.timeout_per_step = timeout
        return executor


# ============================================================================
# LOGGING
# ============================================================================

class ConsoleLogger(Logger):
    """
    Simple console-based logger.
    
    Can be replaced with database logger (Phase 7e) or other implementations.
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def info(self, message: str) -> None:
        if self.verbose:
            print(f"[INFO] {message}")

    def debug(self, message: str) -> None:
        if self.verbose:
            print(f"[DEBUG] {message}")

    def warning(self, message: str) -> None:
        print(f"[WARNING] {message}")

    def error(self, message: str) -> None:
        print(f"[ERROR] {message}")


class SilentLogger(Logger):
    """No-op logger for testing."""

    def info(self, message: str) -> None:
        pass

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


# ============================================================================
# TESTING UTILITIES
# ============================================================================

if __name__ == "__main__":
    print("Executor module loaded successfully!")
    print("Key classes:")
    print("  - Executor: main orchestrator")
    print("  - ExecutorBuilder: configuration")
    print("  - ConsoleLogger: logging")