"""
Phase 7d: Context Manager Implementation
Thread-safe management of step outputs during execution.

The ContextManager allows:
1. Steps to store their outputs
2. Dependent steps to retrieve previous outputs
3. Safe concurrent access (thread-safety with locks)
4. Debugging via snapshots
"""

import threading
from typing import Dict, List, Optional
from src.core.executor.interfaces import ContextManager as ContextManagerInterface


class PlanExecutionContext(ContextManagerInterface):
    """
    Concrete implementation of ContextManager.
    
    Manages step outputs during plan execution. Thread-safe.
    
    Usage:
        ctx = PlanExecutionContext(project_context="... CONTEXT.md ...")
        
        # After step 0 completes:
        ctx.set_step_output(0, "file contents...")
        
        # Step 1 wants to read it:
        prev_output = ctx.get_step_output(0)
        
        # Get snapshot for audit log:
        snapshot = ctx.snapshot()
    """

    def __init__(self, project_context: str = ""):
        """
        Initialize the context manager.
        
        Args:
            project_context: The CONTEXT.md content (for reference by steps)
        """
        self.project_context = project_context
        self._step_outputs: Dict[int, str] = {}
        self._lock = threading.RLock()  # Use RLock for re-entrancy
        self._access_log: List[tuple] = []  # For debugging: (timestamp, step_id, action)

    def set_step_output(self, step_id: int, output: str) -> None:
        """
        Store output from a completed step.
        
        Args:
            step_id: The step that produced this output
            output: The output/result (as string)
        
        Thread-safe.
        """
        with self._lock:
            self._step_outputs[step_id] = output
            self._access_log.append((step_id, "SET", len(output)))

    def get_step_output(self, step_id: int) -> str:
        """
        Retrieve output from a completed step.
        
        Args:
            step_id: The step ID to retrieve
        
        Returns:
            The output (or empty string if not found)
        
        Thread-safe.
        """
        with self._lock:
            result = self._step_outputs.get(step_id, "")
            self._access_log.append((step_id, "GET", len(result)))
            return result

    def get_outputs_for_steps(self, step_ids: List[int]) -> Dict[int, str]:
        """
        Get outputs for multiple steps at once.
        
        Args:
            step_ids: List of step IDs to retrieve
        
        Returns:
            Dict mapping step_id → output (missing steps get empty string)
        
        Thread-safe. Atomic: all steps are retrieved in one lock.
        """
        with self._lock:
            return {step_id: self._step_outputs.get(step_id, "") for step_id in step_ids}

    def snapshot(self) -> Dict[int, str]:
        """
        Get a complete snapshot of all step outputs.
        
        Returns:
            Copy of all step_id → output mappings
        
        Thread-safe. Returns a copy so modifications don't affect internal state.
        """
        with self._lock:
            return dict(self._step_outputs)

    def get_for_depends_on(self, depends_on: List[int]) -> Dict[int, str]:
        """
        Convenience method to get outputs for all dependencies.
        
        Args:
            depends_on: List of step IDs this step depends on
        
        Returns:
            Dict of step_id → output
        """
        return self.get_outputs_for_steps(depends_on)

    def has_output(self, step_id: int) -> bool:
        """Check if a step has produced output."""
        with self._lock:
            return step_id in self._step_outputs

    def clear(self) -> None:
        """Clear all stored outputs (for testing)."""
        with self._lock:
            self._step_outputs.clear()
            self._access_log.clear()

    def access_log(self) -> List[tuple]:
        """
        Get the access log for debugging.
        
        Returns:
            List of (step_id, action, data_size) tuples
        """
        with self._lock:
            return list(self._access_log)

    def __repr__(self) -> str:
        """Debug representation."""
        with self._lock:
            n_steps = len(self._step_outputs)
            total_size = sum(len(v) for v in self._step_outputs.values())
        return f"PlanExecutionContext(steps={n_steps}, total_bytes={total_size})"


# ============================================================================
# Testing Utilities
# ============================================================================

class MockContextManager(ContextManagerInterface):
    """
    Mock ContextManager for testing.
    
    Allows tests to pre-load outputs without executing real steps.
    """

    def __init__(self):
        self.project_context = ""
        self._step_outputs: Dict[int, str] = {}

    def set_step_output(self, step_id: int, output: str) -> None:
        self._step_outputs[step_id] = output

    def get_step_output(self, step_id: int) -> str:
        return self._step_outputs.get(step_id, "")

    def get_outputs_for_steps(self, step_ids: List[int]) -> Dict[int, str]:
        return {step_id: self._step_outputs.get(step_id, "") for step_id in step_ids}

    def snapshot(self) -> Dict[int, str]:
        return dict(self._step_outputs)


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Create a context manager
    ctx = PlanExecutionContext(project_context="Language: Python\nFramework: FastAPI")

    # Simulate execution: step 0 reads a file
    ctx.set_step_output(0, "def user_schema():\n    return {...}")
    print(f"Step 0 output stored: {len(ctx.get_step_output(0))} bytes")

    # Step 1 depends on step 0 and wants to access it
    prev = ctx.get_step_output(0)
    print(f"Step 1 accessed step 0: {prev[:30]}...")

    # Get multiple outputs
    outputs = ctx.get_outputs_for_steps([0, 1])  # Step 1 doesn't exist yet
    print(f"Batch retrieval: {len(outputs)} steps")

    # Get snapshot
    snap = ctx.snapshot()
    print(f"Snapshot: {snap.keys()}")

    # Debug info
    print(f"Context: {ctx}")
    print(f"Access log: {ctx.access_log()}")