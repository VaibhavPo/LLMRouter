# src/core/tool_runtime.py (UPDATED)

from typing import Type
from src.tools.schemas import Tool, ToolRequest, ToolResult
from src.tools.file_tools import ReadFileTool, ListFilesTool
from src.tools.search_tools import SearchCodeTool


class ToolRegistry:
    """Registry of available tools."""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self._tools: dict[str, Tool] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register the initial set of tools."""
        # Readonly tools
        self.register(ReadFileTool(self.project_root))
        self.register(ListFilesTool(self.project_root))
        self.register(SearchCodeTool(self.project_root))
        # Phase 7b and beyond will add write/shell tools
    
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
            return ToolResult(
                success=False,
                output=None,
                error=f"Unknown tool: {request.tool_name}"
            )
        
        tool = self._tools[request.tool_name]
        
        # Validation
        valid, error = tool.validate(request.arguments)
        if not valid:
            return ToolResult(success=False, output=None, error=f"Validation failed: {error}")
        
        # Execution
        result = tool.execute(request.arguments)
        
        # TODO: Phase 7e — audit logging here
        
        return result