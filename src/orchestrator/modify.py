"""
context_merge.py

Patches specific sections of an existing CONTEXT.md and appends a Change
Log entry. Never a blind overwrite — every section not in `answers` is
preserved exactly as-is.

Public interface:
    merge_result = merge_context(old_context_md, answers, change_summary)

No classification, no interviewing — this module only patches and merges.
Assumes CONTEXT.md sections are formatted as `### Section Name` headers,
confirmed against real gemma-4-e2b output.
"""

import re
from datetime import datetime, timezone

from pydantic import BaseModel

_SECTION_HEADER_RE = re.compile(
    r"^### (.+?)\s*\n(.*?)(?=^### |\Z)",
    re.MULTILINE | re.DOTALL,
)

_CHANGE_LOG_HEADER = "### Change Log"


class MergeResult(BaseModel):
    merged_context: str
    change_log_entry: str
    sections_updated: list[str]
    sections_not_found: list[str] = []  # flagged, never silently dropped


def _split_sections(context_md: str) -> dict[str, str]:
    """
    Parse CONTEXT.md into {section_name: section_body}, preserving order
    via dict insertion order (Python 3.7+ guarantee).
    """
    sections: dict[str, str] = {}
    for match in _SECTION_HEADER_RE.finditer(context_md):
        name = match.group(1).strip()
        body = match.group(2).rstrip()
        sections[name] = body
    return sections


def _rebuild(sections: dict[str, str]) -> str:
    """Reassemble sections back into a CONTEXT.md string, same order."""
    parts = []
    for name, body in sections.items():
        parts.append(f"### {name}\n{body}".rstrip())
    return "\n\n".join(parts) + "\n"


def _format_change_log_entry(change_request: str, change_summary: str, sections_updated: list[str]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections_str = ", ".join(sections_updated) if sections_updated else "none"
    return (
        f"- **{timestamp}** — {change_summary}\n"
        f"  - Change request: {change_request}\n"
        f"  - Sections updated: {sections_str}"
    )


def merge_context(
    old_context_md: str,
    answers: dict[str, str],
    change_request: str,
    change_summary: str,
) -> MergeResult:
    """
    Patch the sections named in `answers` with their new content, append
    the new content under the existing section body (not a replace — the
    delta answer describes what CHANGED, so it's appended as an addendum
    to preserve prior context), and append a Change Log entry.

    Sections in `answers` that don't exist in old_context_md are reported
    in `sections_not_found`, never silently dropped — caller decides how
    to surface that (e.g. Orchestrator.modify() can warn the user).
    """
    sections = _split_sections(old_context_md)
    sections_updated: list[str] = []
    sections_not_found: list[str] = []

    for section_name, new_content in answers.items():
        if section_name in sections:
            sections[section_name] = (
                f"{sections[section_name]}\n\n"
                f"**Update:** {new_content}"
            )
            sections_updated.append(section_name)
        else:
            sections_not_found.append(section_name)

    change_log_entry = _format_change_log_entry(change_request, change_summary, sections_updated)

    if _CHANGE_LOG_HEADER.replace("### ", "") in sections:
        sections["Change Log"] = f"{sections['Change Log']}\n{change_log_entry}"
    else:
        sections["Change Log"] = change_log_entry

    merged = _rebuild(sections)

    return MergeResult(
        merged_context=merged,
        change_log_entry=change_log_entry,
        sections_updated=sections_updated,
        sections_not_found=sections_not_found,
    )