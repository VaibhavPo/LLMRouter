"""
CodebaseReader: turn a filesystem path into a bounded, prioritized BootstrapPayload.

Core logic:
  1. Walk the directory tree, respecting .gitignore + built-in filters
  2. Score files by priority (README > entry points > models > config > everything else)
  3. Read files in priority order until token budget is exhausted
  4. Return a BootstrapPayload with file contents, detected stack, patterns, and metadata
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


@dataclass
class BootstrapPayload:
    """The output of CodebaseReader.read() — a bounded, prioritized snapshot of a codebase."""
    
    file_tree: str                      # rendered directory structure (for context)
    file_contents: dict[str, str]       # relative_path -> content, in priority order
    detected_stack: list[str]           # e.g. ["python", "fastapi", "postgres"]
    detected_patterns: list[str]        # e.g. ["pytest", "alembic migrations present"]
    total_tokens_used: int
    files_skipped: list[str]            # what got cut for budget, for transparency


class CodebaseReader:
    """
    Reads a filesystem path and produces a BootstrapPayload.
    
    Token budget is a hard ceiling; priority ordering ensures you get the most
    informative files first, not whatever happens to be alphabetically first.
    """
    
    # Built-in exclusions (before .gitignore is even checked)
    ALWAYS_SKIP_DIRS = {
        ".git",
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".tox",
        "dist",
        "build",
        "*.egg-info",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "tmp",
        "temp",
        ".next",
        "out",
        "coverage",
        "htmlcov",
        ".coverage",
    }
    
    # Binary file extensions to skip
    BINARY_EXTENSIONS = {
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".o",
        ".a",
        ".zip",
        ".tar",
        ".gz",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".pdf",
        ".exe",
        ".bin",
        ".whl",
    }
    
    # File priority scoring
    PRIORITY_PATTERNS = {
        1: [
            r"^README",
            r"^ARCHITECTURE",
            r"^DESIGN",
            r"docs/.*\.md$",
        ],
        2: [
            r"^(main|app|index|__main__|manage|server|run)\.py$",
            r"^(main|app|index|server)\.js$",
            r"^(main|app|index|server)\.ts$",
            r"^src/(index|main|app)\.(py|js|ts)$",
            r"^Dockerfile$",
            r"^\.dockerignore$",
        ],
        3: [
            r"models\.py$",
            r"schema\.py$",
            r"schemas\.py$",
            r"types\.py$",
            r"domain\.py$",
            r"entities\.py$",
            r".*\.prisma$",
            r"schema\.sql$",
            r"types\.ts$",
            r"interfaces\.ts$",
        ],
        4: [
            r"pyproject\.toml$",
            r"setup\.py$",
            r"setup\.cfg$",
            r"requirements\.txt$",
            r"requirements-.*\.txt$",
            r"Pipfile$",
            r"poetry\.lock$",
            r"package\.json$",
            r"package-lock\.json$",
            r"pnpm-lock\.yaml$",
            r"yarn\.lock$",
            r"\.env\.example$",
            r"\.env\.sample$",
            r"config\.py$",
            r"config\.toml$",
            r"settings\.py$",
        ],
    }
    
    def __init__(self, token_budget: int = 12_000):
        """
        Args:
            token_budget: max tokens to read (approximated as chars / 4)
        """
        self.token_budget = token_budget
        self.char_budget = token_budget * 4  # heuristic: 1 token ≈ 4 chars
    
    def read(self, path: str) -> BootstrapPayload:
        """
        Read a directory and return a BootstrapPayload.
        
        Args:
            path: directory path (must exist and be a directory)
        
        Returns:
            BootstrapPayload with file contents, detected stack, patterns
        
        Raises:
            ValueError: if path doesn't exist or isn't a directory
            PermissionError: if unable to read the directory
        """
        root = Path(path).resolve()
        
        if not root.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not root.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        # Render directory structure
        file_tree = self._render_tree(root)
        
        # Collect all candidate files
        candidates = self._collect_candidates(root)
        
        # Detect stack and patterns
        detected_stack = self._detect_stack(candidates, root)
        detected_patterns = self._detect_patterns(candidates, root)
        
        # Read files in priority order until budget is exhausted
        file_contents = {}
        total_chars = 0
        files_skipped = []
        
        for rel_path, priority in sorted(candidates, key=lambda x: (x[1], x[0])):
            file_path = root / rel_path
            
            # Skip if we've exhausted the budget
            if total_chars >= self.char_budget:
                files_skipped.append(str(rel_path))
                continue
            
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                
                # Truncate individual files if needed
                if total_chars + len(content) > self.char_budget:
                    remaining = self.char_budget - total_chars
                    content = content[:remaining]
                    files_skipped.append(f"{rel_path} (truncated)")
                
                file_contents[str(rel_path)] = content
                total_chars += len(content)
            
            except (OSError, IOError) as e:
                # Unreadable file — log and skip
                files_skipped.append(f"{rel_path} (error: {type(e).__name__})")
        
        return BootstrapPayload(
            file_tree=file_tree,
            file_contents=file_contents,
            detected_stack=detected_stack,
            detected_patterns=detected_patterns,
            total_tokens_used=total_chars // 4,
            files_skipped=files_skipped,
        )
    
    def _collect_candidates(self, root: Path) -> list[tuple[str, int]]:
        """
        Walk the directory and return a list of (relative_path, priority) tuples.
        
        Respects .gitignore if present, skips binary files and built-in exclusions.
        
        Returns:
            list of (rel_path, priority) tuples, where priority is 1-5 (or float('inf') for skipped)
        """
        candidates = []
        gitignore_rules = self._parse_gitignore(root)
        
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            current_dir = Path(dirpath)
            
            # Filter out directories we should skip
            dirnames[:] = [
                d for d in dirnames
                if not self._should_skip_dir(d, current_dir, root, gitignore_rules)
            ]
            
            # Check each file
            for filename in filenames:
                file_path = current_dir / filename
                rel_path = file_path.relative_to(root)
                
                # Skip binary files
                if file_path.suffix.lower() in self.BINARY_EXTENSIONS:
                    continue
                
                # Check gitignore
                if self._matches_gitignore(str(rel_path), gitignore_rules):
                    continue
                
                # Assign priority
                priority = self._score_priority(str(rel_path))
                candidates.append((str(rel_path), priority))
        
        return candidates
    
    def _should_skip_dir(
        self, dirname: str, current_dir: Path, root: Path, gitignore_rules: list
    ) -> bool:
        """Check if a directory should be skipped."""
        # Skip if name is in built-in exclusions
        if dirname in self.ALWAYS_SKIP_DIRS:
            return True
        
        # Skip if matches .gitignore
        rel_path = current_dir.relative_to(root)
        dir_path = rel_path / dirname if rel_path != Path(".") else Path(dirname)
        if self._matches_gitignore(str(dir_path), gitignore_rules):
            return True
        
        # Skip symlinks (to avoid infinite loops)
        if (current_dir / dirname).is_symlink():
            return True
        
        return False
    
    def _parse_gitignore(self, root: Path) -> list[str]:
        """
        Parse .gitignore if it exists.
        
        Returns a list of patterns. We do a dead-simple implementation:
        - Each line is a pattern
        - # lines are comments
        - Empty lines are skipped
        - No negation (!) support yet
        
        Real .gitignore parsing is complex; this is v1.
        """
        gitignore_path = root / ".gitignore"
        if not gitignore_path.exists():
            return []
        
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (OSError, IOError):
            return []
        
        patterns = []
        for line in lines:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Negation not supported in v1
            if line.startswith("!"):
                continue
            patterns.append(line)
        
        return patterns
    
    def _matches_gitignore(self, path: str, patterns: list[str]) -> bool:
        """
        Simple gitignore matching.
        
        Handles:
          - Exact filename matches: "*.pyc"
          - Directory patterns: ".git", "node_modules"
          - Path patterns: "dist/", "build/"
        
        Not handled (v1 limitation):
          - Negation (!)
          - ** (recursive wildcard)
          - Edge cases in ** and / semantics
        """
        from fnmatch import fnmatch
        
        for pattern in patterns:
            # Remove trailing / if present
            pattern = pattern.rstrip("/")
            
            # Try exact match
            if fnmatch(path, pattern) or fnmatch(Path(path).name, pattern):
                return True
            
            # Try directory match: if pattern is a dir, skip anything inside it
            if "/" not in pattern and fnmatch(path, f"{pattern}/*"):
                return True
        
        return False
    
    def _score_priority(self, rel_path: str) -> int:
        """
        Assign priority (1-5, lower is higher priority) based on filename patterns.
        
        Returns:
            int: 1-5 (1 = highest), or 5 if no match (lowest)
        """
        import re
        
        for priority in [1, 2, 3, 4]:
            for pattern in self.PRIORITY_PATTERNS[priority]:
                if re.search(pattern, rel_path):
                    return priority
        
        # Default priority for unmatched files
        return 5
    
    def _detect_stack(self, candidates: list[tuple[str, int]], root: Path) -> list[str]:
        """
        Scan config files to detect tech stack.
        
        Looks for: pyproject.toml, package.json, Dockerfile, requirements.txt, etc.
        
        Returns:
            list of detected tech/framework names, e.g. ["python", "fastapi", "postgres"]
        """
        detected = set()
        config_files = {path: priority for path, priority in candidates if priority == 4}
        
        for config_file in config_files:
            path = root / config_file
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().lower()
                
                # Python
                if "pyproject.toml" in config_file or "requirements.txt" in config_file:
                    detected.add("python")
                
                # Python frameworks
                if "fastapi" in content:
                    detected.add("fastapi")
                if "django" in content:
                    detected.add("django")
                if "flask" in content:
                    detected.add("flask")
                if "sqlalchemy" in content:
                    detected.add("sqlalchemy")
                if "pydantic" in content:
                    detected.add("pydantic")
                
                # JavaScript/Node
                if "package.json" in config_file:
                    detected.add("javascript")
                    if "react" in content:
                        detected.add("react")
                    if "next" in content:
                        detected.add("nextjs")
                    if "express" in content:
                        detected.add("express")
                    if "typescript" in content or "tsconfig" in config_file:
                        detected.add("typescript")
                
                # Databases
                if "postgres" in content or "postgresql" in content:
                    detected.add("postgres")
                if "mysql" in content:
                    detected.add("mysql")
                if "mongodb" in content or "mongo" in content:
                    detected.add("mongodb")
                if "redis" in content:
                    detected.add("redis")
                
                # Docker
                if "Dockerfile" in config_file:
                    detected.add("docker")
            
            except (OSError, IOError):
                continue
        
        return sorted(list(detected))
    
    def _detect_patterns(self, candidates: list[tuple[str, int]], root: Path) -> list[str]:
        """
        Scan file listing for common patterns (testing frameworks, migration tools, etc.).
        
        Returns:
            list of detected patterns, e.g. ["pytest", "alembic migrations"]
        """
        detected = set()
        all_paths = {path for path, _ in candidates}
        
        # Testing
        if any("test_" in p or "_test.py" in p for p in all_paths):
            detected.add("pytest")
        if any("spec.js" in p or "spec.ts" in p for p in all_paths):
            detected.add("jest")
        
        # Migrations
        if any("alembic" in p or "migrations/" in p for p in all_paths):
            detected.add("alembic migrations")
        if any("migrate" in p and ".go" in p for p in all_paths):
            detected.add("sql-migrate")
        
        # API documentation
        if any("openapi" in p or "swagger" in p for p in all_paths):
            detected.add("openapi/swagger")
        
        # CI/CD
        if any(".github/workflows" in p for p in all_paths):
            detected.add("github actions")
        if any(".gitlab-ci" in p for p in all_paths):
            detected.add("gitlab-ci")
        if any(".circleci" in p for p in all_paths):
            detected.add("circleci")
        
        return sorted(list(detected))
    
    def _render_tree(self, root: Path, prefix: str = "", max_depth: int = 3) -> str:
        """
        Render a directory tree as a string, limited to max_depth levels.
        
        Used for context — shows the user the structure without reading files.
        """
        if max_depth == 0:
            return ""
        
        lines = [str(root.name) + "/"]
        
        try:
            entries = sorted(root.iterdir())
        except PermissionError:
            return lines[0] + " [permission denied]"
        
        # Filter out obvious clutter
        entries = [
            e for e in entries
            if e.name not in self.ALWAYS_SKIP_DIRS and not e.name.startswith(".")
        ]
        
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            current_prefix = "└── " if is_last else "├── "
            next_prefix = "    " if is_last else "│   "
            
            if entry.is_dir():
                lines.append(prefix + current_prefix + entry.name + "/")
                if max_depth > 1:
                    subtree = self._render_tree(entry, prefix + next_prefix, max_depth - 1)
                    if subtree:
                        lines.extend(subtree.split("\n")[1:])  # Skip the dir name, already added
            else:
                lines.append(prefix + current_prefix + entry.name)
        
        return "\n".join(lines)
