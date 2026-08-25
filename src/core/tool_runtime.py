# src/core/tool_runtime.py (UPDATED)

# src/core/tool_runtime.py
from typing import Type
from src.tools.schemas import Tool, ToolRequest, ToolResult
from src.tools.file_tools import ReadFileTool, ListFilesTool, WriteFileTool, EditFileTool
from src.tools.search_tools import SearchCodeTool
from src.tools.shell_tools import RunTestsTool, RunLinterTool


class ToolRegistry:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self._tools: dict[str, Tool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        self.register(ReadFileTool(self.project_root))
        self.register(ListFilesTool(self.project_root))
        self.register(SearchCodeTool(self.project_root))
        self.register(WriteFileTool(self.project_root))
        self.register(EditFileTool(self.project_root))
        self.register(RunTestsTool(self.project_root))
        self.register(RunLinterTool(self.project_root))

    # ... rest unchanged
    
    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool
    
    def list_tools(self) -> list[dict]:
        """Return schema for all available tools (for model instruction)."""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "safety_tier": tool.safety_tier.value,
            })
        return schemas
    
    def execute(self, request: ToolRequest) -> ToolResult:
        """Execute a tool request."""
        if request.tool_name not in self._tools:
            known = ", ".join(sorted(self._tools.keys()))
            return ToolResult(
                success=False,
                output=None,
                error=(
                    f"Unknown tool: '{request.tool_name}' "
                    f"(known tools: {known}; check for a typo or a planner "
                    f"hallucinated tool name)"
                ),
            )
        
        tool = self._tools[request.tool_name]
        
        # Validation
        valid, error = tool.validate(request.arguments)
        if not valid:
            return ToolResult(
                success=False,
                output=None,
                error=self._actionable(
                    tool,
                    f"Validation failed: {error} "
                    f"(arguments given: {request.arguments})",
                ),
            )
        
        # Execution
        try:
            result = tool.execute(request.arguments)
        except Exception as e:
            # A tool raising instead of returning ToolResult(success=False) is
            # itself a bug in that tool, but the caller (a replanner) still
            # needs an actionable message, not a bare traceback.
            return ToolResult(
                success=False,
                output=None,
                error=self._actionable(
                    tool,
                    f"Tool raised {type(e).__name__}: {e} "
                    f"(arguments given: {request.arguments})",
                ),
            )

        if not result.success and result.error:
            result = ToolResult(
                success=False,
                output=result.output,
                error=self._actionable(tool, result.error),
            )

        # TODO: Phase 7e — audit logging here
        
        return result

    def _actionable(self, tool, base_error: str) -> str:
        """
        Wrap a raw tool error with what/state/likely-cause/next-action shape
        (Section 5). Individual tools can still return their own richer
        message (e.g. read_tools including line counts) -- this only adds a
        generic suggestion when the tool hasn't already.
        """
        if "consider" in base_error.lower() or "suggest" in base_error.lower():
            return base_error  # tool already gave a specific suggestion
        return f"{base_error} (tool: {tool.name}; description: {tool.description or 'n/a'})"