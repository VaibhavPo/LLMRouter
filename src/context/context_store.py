"""
context_store.py

Simple file-based storage for CONTEXT.md files.
One file per project, stored in contexts/ directory.

Public interface:
    store = ContextStore()
    store.save("my-blog-app", context_md_string)
    retrieved = store.load("my-blog-app")
"""

from pathlib import Path


class ContextStore:
    """File-based CONTEXT.md storage."""

    def __init__(self, base_dir: str = "contexts"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def _context_path(self, project_id: str) -> Path:
        """Safe path for a project's CONTEXT.md."""
        # Sanitize project_id to prevent path traversal attacks
        safe_id = "".join(c for c in project_id if c.isalnum() or c in "-_")
        return self.base_dir / f"{safe_id}.md"

    def save(self, project_id: str, context_md: str) -> str:
        """
        Save CONTEXT.md for a project.
        Returns the path where it was saved.
        """
        path = self._context_path(project_id)
        path.write_text(context_md, encoding="utf-8")
        return str(path)

    def load(self, project_id: str) -> str | None:
        """
        Load CONTEXT.md for a project.
        Returns None if project doesn't exist.
        """
        path = self._context_path(project_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def exists(self, project_id: str) -> bool:
        """Check if a project's CONTEXT.md exists."""
        return self._context_path(project_id).exists()

    def delete(self, project_id: str) -> bool:
        """Delete a project's CONTEXT.md. Returns True if deleted, False if didn't exist."""
        path = self._context_path(project_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_projects(self) -> list[str]:
        """List all stored project IDs."""
        return [
            p.stem for p in self.base_dir.glob("*.md")
        ]