# src/core/planner_v2/parsers.py
"""Response parsing."""
# src/core/planner_v2/parsers.py
"""Response parsers."""

import json
from .interfaces import ResponseParser
from src.core.plan_serde import strip_code_fence


class JSONParser(ResponseParser):
    """Parse JSON responses."""
    
    def parse(self, response: str) -> dict:
        """Parse JSON, with cleanup."""
        response = strip_code_fence(response)
        
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