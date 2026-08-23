# src/tools/search_tools.py
"""Search tools for code exploration."""

import re
from pathlib import Path
from .schemas import Tool, ToolResult, SafetyTier


class SearchCodeTool(Tool):
    """Search for code patterns (regex or plain text) in files."""
    
    name = "search_code"
    description = "Search for text or regex patterns in code files"
    safety_tier = SafetyTier.READONLY
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
    
    def validate(self, args: dict) -> tuple[bool, str]:
        """Validate search arguments."""
        if "pattern" not in args:
            return False, "missing 'pattern' argument"
        
        pattern = args["pattern"]
        if not isinstance(pattern, str) or not pattern.strip():
            return False, "pattern must be a non-empty string"
        
        # Optional: path to search within
        path = args.get("path", ".")
        p = Path(path)
        search_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
        
        try:
            search_path.relative_to(self.project_root)
        except ValueError:
            return False, f"path must be within {self.project_root}"
        
        if not search_path.exists():
            return False, f"path does not exist: {search_path}"
        
        # Validate regex if specified
        is_regex = args.get("is_regex", False)
        if is_regex:
            try:
                re.compile(pattern)
            except re.error as e:
                return False, f"invalid regex pattern: {e}"
        
        # Validate file extension filter
        file_types = args.get("file_types")
        if file_types is not None:
            if not isinstance(file_types, list):
                return False, "file_types must be a list (e.g., ['.py', '.js'])"
        
        # Validate max_results
        max_results = args.get("max_results", 50)
        if not isinstance(max_results, int) or max_results < 1:
            return False, "max_results must be a positive integer"
        
        return True, ""
    
    def execute(self, args: dict) -> ToolResult:
        """Search for patterns in code."""
        valid, error = self.validate(args)
        if not valid:
            return ToolResult(success=False, output=None, error=error)
        
        try:
            pattern = args["pattern"]
            p = Path(args.get("path", "."))
            search_path = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()
            is_regex = args.get("is_regex", False)
            file_types = args.get("file_types")  # e.g., ['.py', '.js']
            max_results = args.get("max_results", 50)
            
            # Compile regex if needed
            if is_regex:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"regex compile failed: {e}"
                    )
            
            matches = []
            files_searched = 0
            
            # Walk directory
            for root, dirs, filenames in search_path.walk():
                # Skip common non-code directories
                dirs[:] = [
                    d for d in dirs
                    if d not in {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache"}
                ]
                
                for filename in filenames:
                    file_path = Path(root) / filename
                    
                    # Filter by file type if specified
                    if file_types:
                        if file_path.suffix not in file_types:
                            continue
                    
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        
                        for line_num, line in enumerate(lines, start=1):
                            if is_regex:
                                if regex.search(line):
                                    matches.append((file_path, line_num, line.strip()))
                            else:
                                if pattern.lower() in line.lower():
                                    matches.append((file_path, line_num, line.strip()))
                            
                            if len(matches) >= max_results:
                                break
                        
                        files_searched += 1
                    
                    except (UnicodeDecodeError, PermissionError):
                        # Skip binary/unreadable files
                        continue
                    
                    if len(matches) >= max_results:
                        break
                
                if len(matches) >= max_results:
                    break
            
            # Format output
            if not matches:
                output = f"No matches found for '{pattern}'"
                return ToolResult(
                    success=True,
                    output=output,
                    error=None,
                    metadata={
                        "files_searched": files_searched,
                        "matches_found": 0,
                    }
                )
            
            # Group by file
            matches_by_file = {}
            for file_path, line_num, line in matches:
                rel_path = str(file_path.relative_to(self.project_root))
                if rel_path not in matches_by_file:
                    matches_by_file[rel_path] = []
                matches_by_file[rel_path].append((line_num, line))
            
            # Format for output
            output_lines = []
            for file_path in sorted(matches_by_file.keys()):
                output_lines.append(f"\n{file_path}:")
                for line_num, line in sorted(matches_by_file[file_path])[:10]:  # Max 10 per file
                    # Truncate long lines
                    display_line = line[:100] + "..." if len(line) > 100 else line
                    output_lines.append(f"  {line_num:5d} | {display_line}")
                
                if len(matches_by_file[file_path]) > 10:
                    output_lines.append(f"  ... (+{len(matches_by_file[file_path]) - 10} more matches)")
            
            output = "\n".join(output_lines)
            
            return ToolResult(
                success=True,
                output=output,
                error=None,
                metadata={
                    "pattern": pattern,
                    "files_searched": files_searched,
                    "matches_found": len(matches),
                    "limited": len(matches) >= max_results,
                }
            )
        
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Search failed: {e}")