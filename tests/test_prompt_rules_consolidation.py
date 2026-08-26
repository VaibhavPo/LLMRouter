from src.core.prompt_rules import (
    EDIT_DISCIPLINE_RULES, TOOL_ARGS_SCHEMA, REQUIRED_TOOL_ARGS,
)
from src.core.plan_serde import dict_to_tool_invocation, PlanParseError
import pytest


def test_required_tool_args_covers_all_write_capable_tools():
    for tool in ("read_file", "search_code", "write_file", "edit_file"):
        assert tool in REQUIRED_TOOL_ARGS


def test_dict_to_tool_invocation_rejects_missing_file_path():
    with pytest.raises(PlanParseError, match="missing required argument"):
        dict_to_tool_invocation({"tool_name": "read_file", "arguments": {}})


def test_dict_to_tool_invocation_rejects_missing_edit_file_args():
    with pytest.raises(PlanParseError, match="missing required argument"):
        dict_to_tool_invocation({
            "tool_name": "edit_file",
            "arguments": {"file_path": "x.html"},  # missing old_str, new_str
        })


def test_dict_to_tool_invocation_accepts_complete_args():
    inv = dict_to_tool_invocation({
        "tool_name": "edit_file",
        "arguments": {"file_path": "x.html", "old_str": "a", "new_str": "b"},
    })
    assert inv.tool_name == "edit_file"


def test_dict_to_tool_invocation_allows_unlisted_tools_through():
    # list_files/run_tests aren't in REQUIRED_TOOL_ARGS -> no required check
    inv = dict_to_tool_invocation({"tool_name": "list_files", "arguments": {}})
    assert inv.tool_name == "list_files"


def test_replanner_prompts_include_shared_safety_rules():
    from src.core.executor.replanner import LocalReplanner, FullReplanner
    import inspect
    local_src = inspect.getsource(LocalReplanner.replan)
    full_src = inspect.getsource(FullReplanner.replan)
    assert "PLANNING_SAFETY_RULES" in local_src
    assert "PLANNING_SAFETY_RULES" in full_src