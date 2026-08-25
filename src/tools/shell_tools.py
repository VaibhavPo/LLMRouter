# src/tools/shell_tools.py
"""Shell tools: run tests and linters as subprocesses."""

import subprocess
from pathlib import Path
from .schemas import Tool, ToolResult, SafetyTier


class RunTestsTool(Tool):
    """Run pytest against a test path and return the output."""

    name = "run_tests"
    description = "Run pytest against a test path and return pass/fail output"
    safety_tier = SafetyTier.SHELL

    def __init__(self, project_root: str, timeout_seconds: int = 120):
        self.project_root = Path(project_root).resolve()
        self.timeout_seconds = timeout_seconds

    def validate(self, args: dict) -> tuple[bool, str]:
        test_path = args.get("test_path", "tests")
        p = Path(test_path)
        full_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()

        try:
            full_path.relative_to(self.project_root)
        except ValueError:
            return False, f"test_path must be within {self.project_root}"

        if not full_path.exists():
            return False, f"test_path does not exist: {full_path}"

        return True, ""

    def execute(self, args: dict) -> ToolResult:
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)

        test_path = args.get("test_path", "tests")

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", test_path, "-v"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")

            return ToolResult(
                success=(result.returncode == 0),
                output=output,
                error=None if result.returncode == 0 else f"pytest exited with code {result.returncode}",
                metadata={"return_code": result.returncode, "test_path": test_path},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error=f"Tests timed out after {self.timeout_seconds}s")
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Test run failed: {e}")


class RunLinterTool(Tool):
    """Run flake8 against a path and return the output."""

    name = "run_linter"
    description = "Run flake8 against a path and return lint findings"
    safety_tier = SafetyTier.SHELL

    def __init__(self, project_root: str, timeout_seconds: int = 60):
        self.project_root = Path(project_root).resolve()
        self.timeout_seconds = timeout_seconds

    def validate(self, args: dict) -> tuple[bool, str]:
        path = args.get("path", ".")
        p = Path(path)
        full_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()

        try:
            full_path.relative_to(self.project_root)
        except ValueError:
            return False, f"path must be within {self.project_root}"

        if not full_path.exists():
            return False, f"path does not exist: {full_path}"

        return True, ""

    def execute(self, args: dict) -> ToolResult:
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)

        path = args.get("path", ".")

        try:
            result = subprocess.run(
                ["python", "-m", "flake8", path],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            output = result.stdout or "(no lint issues found)"

            return ToolResult(
                success=(result.returncode == 0),
                output=output,
                error=None if result.returncode == 0 else "Linter reported issues",
                metadata={"return_code": result.returncode, "path": path},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error=f"Linter timed out after {self.timeout_seconds}s")
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Lint run failed: {e}")