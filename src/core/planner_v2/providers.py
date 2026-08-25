# src/core/planner_v2/providers.py
"""LLM implementations."""
# src/core/planner_v2/providers.py
"""
Concrete implementations of interfaces.
These can be swapped without changing Planner.
"""

from .interfaces import LLMProvider
from src.core.gateway import _lmstudio_run


class LMStudioProvider(LLMProvider):
    """LM Studio backend."""
    
    def __init__(self, model_id: str, base_url: str = "http://localhost:1234"):
        self.model_id = model_id
    
    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """Call LM Studio."""
        # Combine system and user prompt for _lmstudio_run
        prompt = f"System: {system_prompt}\nUser Request: {user_prompt}"
        response = _lmstudio_run(self.model_id, prompt, max_tokens=max_tokens, temperature=temperature)
        return response


class MockProvider(LLMProvider):
    """Mock provider for testing."""
    
    def __init__(self, response: str = '{"task_summary": "mock", "steps": []}'):
        self.response = response
    
    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """Return pre-canned response."""
        return self.response


# Future: Add more providers without touching Planner
class OpenAIProvider(LLMProvider):
    """OpenAI backend (for future use)."""
    
    def call(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        # Implementation when needed
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic backend (for future use)."""
    
    def call(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        # Implementation when needed
        pass