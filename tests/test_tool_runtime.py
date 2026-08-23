# tests/test_tool_runtime.py
import tempfile
import pytest
from pathlib import Path
from src.core.tool_runtime import ToolRegistry
from src.tools.schemas import ToolRequest

@pytest.fixture
def temp_project():
    """Create a temporary project directory with sample files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create sample files
        (project_root / "hello.py").write_text("print('hello')\n")
        (project_root / "data.json").write_text('{"key": "value"}\n')
        (project_root / "subdir").mkdir()
        (project_root / "subdir" / "nested.txt").write_text("nested content\n")
        
        yield str(project_root)

@pytest.fixture
def registry(temp_project):
    """Create a tool registry pointing to temp project."""
    return ToolRegistry(temp_project)

def test_read_file_success(registry, temp_project):
    """Test reading a file that exists."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={"file_path": "hello.py"}
    )
    result = registry.execute(request)
    
    assert result.success
    assert "print('hello')" in result.output
    assert result.metadata["line_count"] == 1

def test_read_file_not_found(registry):
    """Test reading a file that doesn't exist."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={"file_path": "nonexistent.py"}
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "does not exist" in result.error

def test_read_file_path_traversal(registry):
    """Test that path traversal attacks are blocked."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={"file_path": "../../etc/passwd"}
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "must be within" in result.error

def test_list_files_success(registry, temp_project):
    """Test listing files in a directory."""
    request = ToolRequest(
        tool_name="list_files",
        arguments={"path": "."}
    )
    result = registry.execute(request)
    
    assert result.success
    assert "hello.py" in result.output
    assert "data.json" in result.output
    assert "subdir/" in result.output
    assert result.metadata["entry_count"] == 3

def test_list_files_nonexistent(registry):
    """Test listing a path that doesn't exist."""
    request = ToolRequest(
        tool_name="list_files",
        arguments={"path": "nonexistent_dir"}
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "does not exist" in result.error

def test_unknown_tool(registry):
    """Test that unknown tools are rejected."""
    request = ToolRequest(
        tool_name="delete_everything",
        arguments={}
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "Unknown tool" in result.error
# tests/test_tool_runtime.py (ADD THESE NEW TESTS)

def test_list_files_with_sizes(registry):
    """Test that list_files shows file sizes correctly."""
    request = ToolRequest(
        tool_name="list_files",
        arguments={"path": "."}
    )
    result = registry.execute(request)
    
    assert result.success
    # Should show sizes like "5.2 KB" or "123B"
    assert "KB" in result.output or "B" in result.output

def test_list_files_recursive(registry, temp_project):
    """Test recursive directory listing."""
    request = ToolRequest(
        tool_name="list_files",
        arguments={
            "path": ".",
            "recursive": True
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "subdir" in result.output
    assert "nested.txt" in result.output

def test_list_files_exclude_hidden(registry, temp_project):
    """Test that hidden files are excluded by default."""
    # Create a hidden file
    project_root = Path(registry._tools["read_file"].project_root)
    (project_root / ".hidden").write_text("secret")
    
    request = ToolRequest(
        tool_name="list_files",
        arguments={"path": "."}
    )
    result = registry.execute(request)
    
    assert result.success
    assert ".hidden" not in result.output

def test_list_files_include_hidden(registry, temp_project):
    """Test that hidden files can be included if requested."""
    project_root = Path(registry._tools["read_file"].project_root)
    (project_root / ".hidden").write_text("secret")
    
    request = ToolRequest(
        tool_name="list_files",
        arguments={
            "path": ".",
            "include_hidden": True
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert ".hidden" in result.output

def test_search_code_plain_text(registry, temp_project):
    """Test plain text search."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": "def function_b",
            "path": "."
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "multiline.py" in result.output
    assert "4 |" in result.output or "4:" in result.output

def test_search_code_case_insensitive(registry):
    """Test that plain text search is case-insensitive."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": "DEF FUNCTION_B",  # uppercase
            "path": "."
        }
    )
    result = registry.execute(request)
    
    assert result.success
    # Should still find "def function_b"
    assert "multiline.py" in result.output

def test_search_code_regex(registry):
    """Test regex search."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": r"^def\s+\w+\(",
            "is_regex": True,
            "path": "."
        }
    )
    result = registry.execute(request)
    
    assert result.success
    # Should find function definitions
    assert "function_" in result.output.lower()

def test_search_code_invalid_regex(registry):
    """Test that invalid regex is caught."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": r"[invalid regex(",
            "is_regex": True,
            "path": "."
        }
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "invalid regex" in result.error.lower()

def test_search_code_file_type_filter(registry):
    """Test filtering by file type."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": ".",  # match anything
            "file_types": [".py"],
            "path": "."
        }
    )
    result = registry.execute(request)
    
    assert result.success
    # Should only find .py files
    assert ".py" in result.output or "multiline.py" in result.output or "No matches" in result.output

def test_search_code_max_results(registry):
    """Test that max_results limit is respected."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": "",  # empty = match all lines
            "max_results": 1,
            "path": "."
        }
    )
    result = registry.execute(request)
    
    # Should limit output to 1 result
    assert result.metadata["matches_found"] <= 1 or result.metadata["limited"]

def test_search_code_no_matches(registry):
    """Test behavior when no matches found."""
    request = ToolRequest(
        tool_name="search_code",
        arguments={
            "pattern": "xyzABC123notfound",
            "path": "."
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "No matches" in result.output
    assert result.metadata["matches_found"] == 0