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
        
        # Create a multi-line file for line range testing
        multiline_content = "\n".join([
            "def function_a():",
            "    return 'a'",
            "",
            "def function_b():",
            "    x = 1",
            "    y = 2",
            "    return x + y",
            "",
            "def function_c():",
            "    pass",
        ])
        (project_root / "multiline.py").write_text(multiline_content)
        
        (project_root / "subdir").mkdir()
        (project_root / "subdir" / "nested.txt").write_text("nested content\n")
        
        yield str(project_root)

@pytest.fixture
def registry(temp_project):
    """Create a tool registry pointing to temp project."""
    return ToolRegistry(temp_project)

# ===== Existing tests (unchanged) =====

def test_read_file_success(registry):
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

# ===== NEW: Line range tests =====

def test_read_file_line_range_middle(registry):
    """Test reading a specific range of lines from the middle of a file."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 4,
            "end_line": 7
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "def function_b():" in result.output
    assert "x = 1" in result.output
    assert "return x + y" in result.output
    assert "def function_a():" not in result.output  # line 1, before range
    assert "def function_c():" not in result.output  # line 9, after range
    assert result.metadata["line_count"] == 4
    assert result.metadata["total_lines"] == 10
    assert result.metadata["range_requested"] == "4:7"

def test_read_file_line_range_start_only(registry):
    """Test reading from a start_line to end of file."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 9
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "def function_c():" in result.output
    assert "pass" in result.output
    assert result.metadata["line_count"] == 2  # lines 9–10
    assert result.metadata["range_requested"] == "9:10"

def test_read_file_line_range_end_only(registry):
    """Test reading from start of file to end_line."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "end_line": 3
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "def function_a():" in result.output
    assert "return 'a'" in result.output
    assert result.metadata["line_count"] == 3
    assert result.metadata["range_requested"] == "1:3"

def test_read_file_line_range_single_line(registry):
    """Test reading a single line."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 5,
            "end_line": 5
        }
    )
    result = registry.execute(request)
    
    assert result.success
    assert "x = 1" in result.output
    assert result.metadata["line_count"] == 1
    assert "4 |" not in result.output  # shouldn't include line 4
    assert "6 |" not in result.output  # shouldn't include line 6

def test_read_file_line_range_with_line_numbers(registry):
    """Test that output includes correct line numbers."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 1,
            "end_line": 3
        }
    )
    result = registry.execute(request)
    
    assert result.success
    # Check that line numbers are printed correctly
    assert "   1 |" in result.output  # Line 1 with line number
    assert "   2 |" in result.output  # Line 2 with line number
    assert "   3 |" in result.output  # Line 3 with line number

def test_read_file_line_range_out_of_bounds(registry):
    """Test that out-of-bounds line numbers are handled gracefully."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 100,  # File only has 10 lines
            "end_line": 150
        }
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "beyond file length" in result.error

def test_read_file_line_range_invalid_start_line(registry):
    """Test validation of invalid start_line."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 0  # Must be >= 1
        }
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "positive integer" in result.error

def test_read_file_line_range_end_before_start(registry):
    """Test validation of end_line < start_line."""
    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "file_path": "multiline.py",
            "start_line": 50,
            "end_line": 40
        }
    )
    result = registry.execute(request)
    
    assert not result.success
    assert "must be >=" in result.error

def test_read_file_large_file_warning(registry):
    """Test that large files generate a warning in metadata."""
    # Create a large file (>300 lines)
    project_root = Path(registry._tools["read_file"].project_root)
    large_content = "\n".join([f"line {i}" for i in range(1, 401)])
    (project_root / "large.py").write_text(large_content)
    
    request = ToolRequest(
        tool_name="read_file",
        arguments={"file_path": "large.py"}
    )
    result = registry.execute(request)
    
    assert result.success
    assert result.metadata["warning"] == "large file"
    assert result.metadata["line_count"] == 400

# ===== Existing list_files tests (unchanged) =====

def test_list_files_success(registry):
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