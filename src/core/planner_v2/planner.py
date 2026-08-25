# src/core/planner_v2/planner.py
"""Main orchestrator."""
# src/core/planner_v2/planner.py
"""
Main Planner orchestrator.
Loosely coupled: delegates to injected components.
"""

from .interfaces import (
    LLMProvider, PromptBuilder, ResponseParser, PlanValidator,
    Logger, PlanFactory
)
from src.core.task_plan import TaskPlan, PlannerResponse


class Planner:
    """
    Generates TaskPlans by orchestrating injected components.
    
    This class is loosely coupled: it only knows about interfaces,
    not concrete implementations. Swap any component without changing Planner.
    """
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        prompt_builder: PromptBuilder,
        parser: ResponseParser,
        validator: PlanValidator,
        plan_factory: PlanFactory,
        logger: Logger,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        """
        Initialize Planner with dependencies.
        
        Args:
            llm_provider: How to call the LLM
            prompt_builder: How to build prompts
            parser: How to parse responses
            validator: How to validate plans
            plan_factory: How to create TaskPlan objects
            logger: How to log
            temperature: LLM temperature
            max_tokens: Max response length
        """
        self.llm = llm_provider
        self.prompts = prompt_builder
        self.parser = parser
        self.validator = validator
        self.factory = plan_factory
        self.logger = logger
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def plan(
        self,
        user_request: str,
        context_md: str,
        tool_descriptions: dict,
        prior_failure: str = "",
    ) -> PlannerResponse:
        """
        Generate a TaskPlan for a request.
        
        Args:
            user_request: What the user wants done
            context_md: Project CONTEXT.md
            tool_descriptions: Available tools
            prior_failure: Optional compact summary of the most relevant
                past failed attempt at this same task (from
                ExecutionHistoryStore), so the planner doesn't repeat a
                mistake it already made. Deliberately NOT the full
                execution history -- just enough to avoid re-treading the
                same wrong assumption. Pass "" (default) if there's no
                relevant prior failure, or history isn't available.
        
        Returns:
            PlannerResponse with TaskPlan
        
        Raises:
            ValueError: If planning fails
        """
        self.logger.info("="*60)
        self.logger.info("PLANNER: Generating task plan...")
        self.logger.info("="*60)
        
        try:
            # Step 1: Build prompts
            system_prompt = self.prompts.system_prompt()
            # Defensive: not every PromptBuilder implementation (e.g. a
            # test double, or one written before this param existed) is
            # guaranteed to accept prior_failure. Try the richer call
            # first; fall back to the original signature rather than
            # breaking any builder that hasn't been updated.
            import inspect
            sig = inspect.signature(self.prompts.build_user_prompt)
            if "prior_failure" in sig.parameters:
                user_prompt = self.prompts.build_user_prompt(
                    user_request, context_md, tool_descriptions,
                    prior_failure=prior_failure,
                )
            else:
                user_prompt = self.prompts.build_user_prompt(
                    user_request, context_md, tool_descriptions
                )
            
            self.logger.debug(f"System prompt: {system_prompt[:100]}...")
            self.logger.debug(f"User prompt: {user_prompt[:100]}...")
            
            # Step 2: Call LLM
            self.logger.info("Calling LLM provider...")
            response = self.llm.call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            
            self.logger.info(f"LLM responded: {len(response)} chars")
            self.logger.debug(f"Response: {response[:200]}...")
            
            # Step 3: Parse response
            self.logger.info("Parsing response...")
            plan_dict = self.parser.parse(response)
            
            self.logger.debug(f"Parsed: {plan_dict}")
            
            # Step 4: Validate
            self.logger.info("Validating plan...")
            self.validator.validate(plan_dict)
            
            self.logger.info("✅ Validation passed")
            
            # Step 5: Create TaskPlan object
            self.logger.info("Creating TaskPlan object...")
            plan = self.factory.create(plan_dict)
            
            self.logger.info(f"✅ Plan generated: {len(plan.steps)} steps")
            
            return PlannerResponse(
                plan=plan,
                reasoning=plan_dict.get("reasoning", ""),
            )
        
        except ValueError as e:
            self.logger.error(f"❌ Planning failed: {e}")
            raise
        except Exception as e:
            self.logger.error(f"❌ Unexpected error: {e}")
            raise ValueError(f"Planning failed: {e}")