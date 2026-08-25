# src/core/planner_v2/interfaces.py
"""Abstractions (not implementations!)."""
# src/core/planner_v2/interfaces.py
"""
Interfaces for planner components.
These define contracts that implementations must honor.
Planner depends on interfaces, not implementations.
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.task_plan import TaskPlan


class LLMProvider(ABC):
    """Contract for LLM providers (LM Studio, OpenAI, Anthropic, etc.)"""
    
    @abstractmethod
    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """
        Call an LLM and return text response.
        
        Args:
            system_prompt: System instructions
            user_prompt: User message
            temperature: Sampling temperature (0.0–1.0)
            max_tokens: Max response length
        
        Returns:
            Text response from model
        
        Raises:
            Exception: If LLM call fails
        """
        pass


class PromptBuilder(ABC):
    """Contract for building prompts from components."""
    
    @abstractmethod
    def build_user_prompt(
        self,
        user_request: str,
        context_md: str,
        tool_descriptions: dict,
    ) -> str:
        """Build user-facing prompt."""
        pass
    
    @abstractmethod
    def system_prompt(self) -> str:
        """Return system prompt."""
        pass


class ResponseParser(ABC):
    """Contract for parsing LLM responses."""
    
    @abstractmethod
    def parse(self, response: str) -> dict:
        """
        Parse LLM response into dict.
        
        Args:
            response: Raw LLM response text
        
        Returns:
            Parsed dict (usually JSON-like structure)
        
        Raises:
            ValueError: If parsing fails
        """
        pass


class PlanValidator(ABC):
    """Contract for validating parsed plans."""
    
    @abstractmethod
    def validate(self, plan_dict: dict) -> None:
        """
        Validate plan dict. Raise if invalid.
        
        Args:
            plan_dict: Parsed plan data
        
        Raises:
            ValueError: If plan is invalid
        """
        pass


class Logger(ABC):
    """Contract for logging."""
    
    @abstractmethod
    def info(self, message: str): pass
    
    @abstractmethod
    def debug(self, message: str): pass
    
    @abstractmethod
    def error(self, message: str): pass


class PlanFactory(ABC):
    """Contract for creating TaskPlan from validated dict."""
    
    @abstractmethod
    def create(self, plan_dict: dict) -> "TaskPlan":
        """Convert validated dict to TaskPlan object."""
        pass