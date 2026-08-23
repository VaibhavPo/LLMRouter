# src/tools/schemas.py
from dataclasses import dataclass
from typing import Any
from enum import Enum

class SafetyTier(str, Enum):
    """Tool safety classification."""
    READONLY = "readonly"      # read_file, search_code — no side effects
    WRITE_LOCAL = "write_local"  # write_file, edit_file — side effects, but localized
    SHELL = "shell"            # run_terminal — can run arbitrary commands

@dataclass
class ToolRequest:
    """What the model asks for."""
    tool_name: str
    arguments: dict[str, Any]

@dataclass
class ToolResult:
    """What the tool returns."""
    success: bool
    output: str | None          # stdout or result
    error: str | None           # stderr or error message
    metadata: dict[str, Any] | None = None  # e.g., line count, file size

class Tool:
    """Base class for all tools."""
    name: str
    description: str
    safety_tier: SafetyTier
    
    def validate(self, args: dict) -> tuple[bool, str]:
        """Validate input args. Return (valid, error_msg)."""
        raise NotImplementedError
    
    def execute(self, args: dict) -> ToolResult:
        """Execute the tool. Return ToolResult."""
        raise NotImplementedError