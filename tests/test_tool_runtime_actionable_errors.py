from src.core.tool_runtime import ToolRegistry
from src.tools.schemas import ToolRequest, ToolResult, Tool, SafetyTier


class FailingValidateTool(Tool):
    name = "failing_validate"
    description = "always fails validation"
    safety_tier = SafetyTier.READONLY

    def validate(self, arguments):
        return False, "missing 'file_path'"

    def execute(self, arguments):
        raise AssertionError("should not be called")


class RaisingTool(Tool):
    name = "raising_tool"
    description = "raises instead of returning ToolResult"
    safety_tier = SafetyTier.READONLY

    def validate(self, arguments):
        return True, None

    def execute(self, arguments):
        raise RuntimeError("disk on fire")


class SpecificSuggestionTool(Tool):
    name = "specific"
    description = "already gives a good suggestion"
    safety_tier = SafetyTier.READONLY

    def validate(self, arguments):
        return True, None

    def execute(self, arguments):
        return ToolResult(success=False, output=None,
                           error="old_str not found (340 lines; consider read_file first)")


def registry_with(*tools):
    reg = ToolRegistry.__new__(ToolRegistry)
    reg.project_root = "."
    reg._tools = {}
    for t in tools:
        reg.register(t)
    return reg


def test_unknown_tool_lists_known_tools():
    reg = registry_with(FailingValidateTool())
    result = reg.execute(ToolRequest(tool_name="nope", arguments={}))
    assert not result.success
    assert "failing_validate" in result.error


def test_validation_failure_includes_arguments_given():
    reg = registry_with(FailingValidateTool())
    result = reg.execute(ToolRequest(tool_name="failing_validate", arguments={"x": 1}))
    assert not result.success
    assert "missing 'file_path'" in result.error
    assert "{'x': 1}" in result.error


def test_tool_raising_exception_is_caught_and_made_actionable():
    reg = registry_with(RaisingTool())
    result = reg.execute(ToolRequest(tool_name="raising_tool", arguments={}))
    assert not result.success
    assert "disk on fire" in result.error
    assert "RuntimeError" in result.error


def test_generic_failure_gets_tool_context_appended():
    class GenericFailTool(Tool):
        name = "generic"
        description = "some tool"
        safety_tier = SafetyTier.READONLY

        def validate(self, arguments):
            return True, None

        def execute(self, arguments):
            return ToolResult(success=False, output=None, error="something went wrong")

    reg = registry_with(GenericFailTool())
    result = reg.execute(ToolRequest(tool_name="generic", arguments={}))
    assert not result.success
    assert "tool: generic" in result.error


def test_tool_with_its_own_specific_suggestion_is_left_alone():
    reg = registry_with(SpecificSuggestionTool())
    result = reg.execute(ToolRequest(tool_name="specific", arguments={}))
    assert result.error == "old_str not found (340 lines; consider read_file first)"