# src/core/planner_v2/__init__.py
# src/core/planner_v2/parsers.py
"""Response parsers."""

import json
from .interfaces import ResponseParser


class JSONParser(ResponseParser):
    """Parse JSON responses."""
    
    def parse(self, response: str) -> dict:
        """Parse JSON, with cleanup."""
        # Strip markdown code blocks if present
        if response.startswith("```json"):
            response = response[7:]  # Remove ```json
        if response.startswith("```"):
            response = response[3:]  # Remove ```
        if response.endswith("```"):
            response = response[:-3]  # Remove trailing ```
        
        response = response.strip()
        
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON: {e}\nResponse: {response[:200]}")


class YAMLParser(ResponseParser):
    """Parse YAML responses (for future use)."""
    
    def parse(self, response: str) -> dict:
        import yaml
        try:
            return yaml.safe_load(response)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML: {e}")


class MarkdownTableParser(ResponseParser):
    """Parse table-based plans (for future use)."""
    
    def parse(self, response: str) -> dict:
        # Implementation when needed
        pass