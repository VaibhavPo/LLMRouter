# src/tools/file_tools.py
import os
from pathlib import Path
from .schemas import Tool, ToolResult, SafetyTier

class ReadFileTool(Tool):
    """Read a file and return its contents (optionally by line range)."""
    
    name = "read_file"
    description = "Read a file or a range of lines from a file"
    safety_tier = SafetyTier.READONLY
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
    
    def validate(self, args: dict) -> tuple[bool, str]:
        """Check that file_path is within project_root, and line args are sensible."""
        if "file_path" not in args:
            return False, "missing 'file_path' argument"
        
        p = Path(args["file_path"])
        file_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
        
        # Security: prevent path traversal attacks
        try:
            file_path.relative_to(self.project_root)
        except ValueError:
            return False, f"file_path must be within {self.project_root}"
        
        if not file_path.exists():
            return False, f"file does not exist: {file_path}"
        
        if not file_path.is_file():
            return False, f"not a file (maybe a directory): {file_path}"
        
        # Validate line range arguments (if provided)
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        
        # Line numbers are optional, but if present, must be valid integers
        if start_line is not None:
            if not isinstance(start_line, int) or start_line < 1:
                return False, "start_line must be a positive integer (1-indexed)"
        
        if end_line is not None:
            if not isinstance(end_line, int) or end_line < 1:
                return False, "end_line must be a positive integer (1-indexed)"
        
        # end_line must be >= start_line if both provided
        if start_line is not None and end_line is not None:
            if end_line < start_line:
                return False, "end_line must be >= start_line"
        
        return True, ""
    
    def execute(self, args: dict) -> ToolResult:
        """Read the file (or line range) and return it."""
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)
        
        try:
            p = Path(args["file_path"])
            file_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
            content = file_path.read_text(encoding="utf-8")
            
            # Split into lines (preserve line endings for accurate line counting)
            lines = content.splitlines(keepends=True)
            total_lines = len(lines)
            
            start_line = args.get("start_line")
            end_line = args.get("end_line")
            
            # If line range specified, extract that range
            if start_line is not None or end_line is not None:
                # Default: if only start_line, go to end of file
                if start_line is None:
                    start_line = 1
                if end_line is None:
                    end_line = total_lines
                
                # Convert to 0-indexed for Python slicing
                start_idx = max(0, start_line - 1)
                end_idx = min(total_lines, end_line)  # end_line is inclusive
                
                # Bounds check
                if start_idx >= total_lines:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"start_line {start_line} is beyond file length ({total_lines} lines)"
                    )
                
                selected_lines = lines[start_idx:end_idx]
                selected_content = "".join(selected_lines)
                
                # Add line numbers for clarity (helpful for planner/executor)
                output_lines = []
                for i, line in enumerate(selected_lines, start=start_line):
                    output_lines.append(f"{i:4d} | {line}")
                
                output = "".join(output_lines)
                
                return ToolResult(
                    success=True,
                    output=output,
                    error=None,
                    metadata={
                        "line_count": len(selected_lines),
                        "total_lines": total_lines,
                        "range_requested": f"{start_line}:{end_line}",
                        "size_bytes": len(output.encode("utf-8"))
                    }
                )
            else:
                # No line range specified: return the whole file
                # For large files, warn in metadata
                output_lines = []
                for i, line in enumerate(lines, start=1):
                    output_lines.append(f"{i:4d} | {line}")
                
                output = "".join(output_lines)
                
                return ToolResult(
                    success=True,
                    output=output,
                    error=None,
                    metadata={
                        "line_count": total_lines,
                        "range_requested": "full file",
                        "size_bytes": len(output.encode("utf-8")),
                        "warning": "large file" if total_lines > 300 else None
                    }
                )
        
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Read failed: {e}")

# src/tools/file_tools.py (UPDATED ListFilesTool)

class ListFilesTool(Tool):
    """List files and directories in a path with metadata."""
    
    name = "list_files"
    description = "List files and directories in a path with size and metadata"
    safety_tier = SafetyTier.READONLY
    
    def __init__(self, project_root: str, max_depth: int = 1):
        self.project_root = Path(project_root).resolve()
        self.max_depth = max_depth  # How many levels to show
    
    def validate(self, args: dict) -> tuple[bool, str]:
        path_arg = args.get("path", ".")
        p = Path(path_arg)
        dir_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
        
        try:
            dir_path.relative_to(self.project_root)
        except ValueError:
            return False, f"path must be within {self.project_root}"
        
        if not dir_path.exists():
            return False, f"path does not exist: {dir_path}"
        
        if not dir_path.is_dir():
            return False, f"not a directory: {dir_path}"
        
        # Validate optional include_hidden flag
        include_hidden = args.get("include_hidden", False)
        if not isinstance(include_hidden, bool):
            return False, "include_hidden must be true or false"
        
        # Validate optional recursive flag
        recursive = args.get("recursive", False)
        if not isinstance(recursive, bool):
            return False, "recursive must be true or false"
        
        return True, ""
    
    def execute(self, args: dict) -> ToolResult:
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)
        
        try:
            path_arg = args.get("path", ".")
            p = Path(path_arg)
            dir_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
            include_hidden = args.get("include_hidden", False)
            recursive = args.get("recursive", False)
            
            # Collect entries
            entries = []
            
            if recursive:
                # Walk directory tree
                for root, dirs, files in dir_path.walk():
                    # Filter hidden directories if needed
                    if not include_hidden:
                        dirs[:] = [d for d in dirs if not d.startswith(".")]
                    
                    depth = len(Path(root).relative_to(dir_path).parts)
                    indent = "  " * depth
                    
                    # Add directories
                    for d in sorted(dirs):
                        if d.startswith(".") and not include_hidden:
                            continue
                        rel_path = Path(root) / d
                        entries.append(f"{indent}{d}/ (directory)")
                    
                    # Add files
                    for f in sorted(files):
                        if f.startswith(".") and not include_hidden:
                            continue
                        rel_path = Path(root) / f
                        try:
                            size_kb = rel_path.stat().st_size / 1024
                            if size_kb < 1:
                                size_str = f"{rel_path.stat().st_size}B"
                            else:
                                size_str = f"{size_kb:.1f}KB"
                        except:
                            size_str = "?"
                        entries.append(f"{indent}{f} ({size_str})")
            else:
                # Single directory listing
                try:
                    items = sorted(dir_path.iterdir())
                except PermissionError:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Permission denied: {dir_path}"
                    )
                
                for item in items:
                    if item.name.startswith(".") and not include_hidden:
                        continue
                    
                    try:
                        if item.is_dir():
                            entries.append(f"{item.name}/ (directory)")
                        else:
                            size_kb = item.stat().st_size / 1024
                            if size_kb < 1:
                                size_str = f"{item.stat().st_size}B"
                            else:
                                size_str = f"{size_kb:.1f}KB"
                            entries.append(f"{item.name} ({size_str})")
                    except (PermissionError, OSError):
                        # Skip inaccessible items
                        continue
            
            if not entries:
                output = "(empty directory)"
            else:
                output = "\n".join(entries)
            
            return ToolResult(
                success=True,
                output=output,
                error=None,
                metadata={
                    "entry_count": len(entries),
                    "path": str(dir_path.relative_to(self.project_root)),
                    "recursive": recursive,
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"List failed: {e}")
class WriteFileTool(Tool):
    """Write content to a file, creating it (and parent dirs) if needed."""

    name = "write_file"
    description = (
        "Write content to a file, creating parent directories if needed. "
        "Example: write_file(file_path='src/new_module.py', content='hello world')"
    )
    safety_tier = SafetyTier.WRITE_LOCAL

    _KEY_ALIASES = {
        "content_to_insert": "content",
        "content_to_add": "content",
        "text": "content",
        "path": "file_path",
    }

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()

    def _normalize_args(self, args: dict) -> dict:
        """Map common wrong argument keys models emit to the real ones.
        Never overwrites a correct key that's already present."""
        normalized = dict(args)
        for wrong_key, right_key in self._KEY_ALIASES.items():
            if wrong_key in normalized and right_key not in normalized:
                normalized[right_key] = normalized.pop(wrong_key)
        return normalized

    def validate(self, args: dict) -> tuple[bool, str]:
        args = self._normalize_args(args)
        if "file_path" not in args:
            return False, "missing 'file_path' argument"
        if "content" not in args:
            return False, "missing 'content' argument"
        if not isinstance(args["content"], str):
            return False, "content must be a string"

        p = Path(args["file_path"])
        file_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()

        try:
            file_path.relative_to(self.project_root)
        except ValueError:
            return False, f"file_path must be within {self.project_root}"

        if file_path.exists() and file_path.is_dir():
            return False, f"file_path is a directory: {file_path}"

        return True, ""

    def execute(self, args: dict) -> ToolResult:
        args = self._normalize_args(args)
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)

        try:
            p = Path(args["file_path"])
            file_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
            content = args["content"]

            existed_before = file_path.exists()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Wrote {len(content.encode('utf-8'))} bytes to {file_path.relative_to(self.project_root)}",
                error=None,
                metadata={
                    "file_path": str(file_path.relative_to(self.project_root)),
                    "bytes_written": len(content.encode("utf-8")),
                    "created_new": not existed_before,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Write failed: {e}")


class EditFileTool(Tool):
    """Edit an existing file via exact string replacement (find-and-replace)."""

    name = "edit_file"
    description = (
        "Replace an exact string in an existing file with new content. "
        "Example: edit_file(file_path='src/app.py', old_str='old text', new_str='new text')"
    )
    safety_tier = SafetyTier.WRITE_LOCAL

    _KEY_ALIASES = {
        "content_to_insert": "new_str",
        "content_to_add": "new_str",
        "new_content": "new_str",
        "old_content": "old_str",
        "text": "new_str",
        "path": "file_path",
    }

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()

    def _normalize_args(self, args: dict) -> dict:
        normalized = dict(args)
        for wrong_key, right_key in self._KEY_ALIASES.items():
            if wrong_key in normalized and right_key not in normalized:
                normalized[right_key] = normalized.pop(wrong_key)
        return normalized

    def validate(self, args: dict) -> tuple[bool, str]:
        args = self._normalize_args(args)
        for key in ("file_path", "old_str", "new_str"):
            if key not in args:
                return False, f"missing '{key}' argument"

        p = Path(args["file_path"])
        file_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()

        try:
            file_path.relative_to(self.project_root)
        except ValueError:
            return False, f"file_path must be within {self.project_root}"

        if not file_path.exists():
            return False, f"file does not exist: {file_path}"
        if not file_path.is_file():
            return False, f"not a file: {file_path}"

        old_str = args["old_str"]
        if not isinstance(old_str, str) or old_str == "":
            return False, "old_str must be a non-empty string"

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return False, f"could not read file to validate: {e}"

        count = content.count(old_str)
        if count == 0:
            return False, "old_str not found in file"
        replace_all = args.get("replace_all", False)
        if count > 1 and not replace_all:
            return False, f"old_str appears {count} times; pass replace_all=true or make old_str more specific"

        return True, ""

    def execute(self, args: dict) -> ToolResult:
        args = self._normalize_args(args)
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)

        try:
            p = Path(args["file_path"])
            file_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
            old_str = args["old_str"]
            new_str = args["new_str"]
            replace_all = args.get("replace_all", False)

            content = file_path.read_text(encoding="utf-8")
            count = content.count(old_str)
            new_content = content.replace(old_str, new_str) if replace_all else content.replace(old_str, new_str, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Replaced {count if replace_all else 1} occurrence(s) in {file_path.relative_to(self.project_root)}",
                error=None,
                metadata={
                    "file_path": str(file_path.relative_to(self.project_root)),
                    "replacements": count if replace_all else 1,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Edit failed: {e}")