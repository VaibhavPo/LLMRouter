"""
BootstrapRunner: produce a draft CONTEXT.md from a codebase snapshot.

Flow:
  1. infer(bootstrap_payload, change_request)
     → calls model with codebase snapshot
     → model writes CONTEXT.md with [UNKNOWN] placeholders
     → return draft as string

  2. finalise(draft_context_md, interview_answers)
     → replace [UNKNOWN] entries with answers
     → validate required sections present
     → return final CONTEXT.md
"""

import re
from dataclasses import dataclass
from src.bootstrap.codebase_reader import BootstrapPayload
from src.core.models import LM_STUDIO_API, DEFAULT_BOOTSTRAP_MODEL


@dataclass
class InferenceResult:
    """Result of calling infer()."""
    draft_context_md: str
    unknown_entries: list[str]  # parsed list of [UNKNOWN: ...] entries
    inference_tokens_used: int


class BootstrapRunner:
    """
    Run bootstrap inference to produce a draft CONTEXT.md from a codebase.
    """
    
    # Default model for inference
    DEFAULT_MODEL = DEFAULT_BOOTSTRAP_MODEL
    
    # LM Studio endpoint (can be overridden for testing)
    LM_STUDIO_API = LM_STUDIO_API
    
    # Required sections that must be present in final CONTEXT.md
    REQUIRED_SECTIONS = {
        "Problem Statement",
        "Business Context / Objectives",
        "Functional Requirements",
        "Non-Functional Requirements",
        "Tech Stack",
        "Architecture",
        "Shared Vocabulary",
        "Assumptions",
    }
    
    def __init__(self, model: str = None, lm_studio_api: str = None):
        """
        Args:
            model: LM Studio model name (default: gemma-4-e2b)
            lm_studio_api: LM Studio endpoint URL (for testing/mocking)
        """
        self.model = model or self.DEFAULT_MODEL
        self.lm_studio_api = lm_studio_api or self.LM_STUDIO_API
    
    def infer(
        self,
        bootstrap_payload: BootstrapPayload,
        change_request: str,
        use_mock: bool = False,
    ) -> InferenceResult:
        """
        Infer a draft CONTEXT.md from a codebase snapshot.
        
        Args:
            bootstrap_payload: output from CodebaseReader
            change_request: the user's modification request (for context)
            use_mock: if True, return a mock response (for testing)
        
        Returns:
            InferenceResult with draft CONTEXT.md and parsed [UNKNOWN] entries
        
        Raises:
            RuntimeError: if API call fails
        """
        # Build the inference prompt
        prompt = self._build_inference_prompt(bootstrap_payload, change_request)
        
        # Call the model
        if use_mock:
            response_text = self._mock_inference_response()
        else:
            response_text = self._call_lm_studio(prompt)
        
        # Extract CONTEXT.md from response
        draft_context_md = self._extract_context_md(response_text)
        
        # Parse [UNKNOWN] entries
        unknown_entries = self._parse_unknown_entries(draft_context_md)
        
        # Estimate tokens used (heuristic: chars / 4)
        tokens_used = len(response_text) // 4
        
        return InferenceResult(
            draft_context_md=draft_context_md,
            unknown_entries=unknown_entries,
            inference_tokens_used=tokens_used,
        )
    
    def finalise(
        self,
        draft_context_md: str,
        interview_answers: dict[str, str],
    ) -> str:
        """
        Merge interview answers into draft CONTEXT.md.
        
        Args:
            draft_context_md: draft with [UNKNOWN] placeholders
            interview_answers: dict mapping "[UNKNOWN: ...]" to answer text
                              or just the key (e.g., "Business Intent") to answer
        
        Returns:
            final CONTEXT.md with [UNKNOWN] replaced by answers
        
        Raises:
            ValueError: if final CONTEXT.md is missing required sections or has
                       unresolved [UNKNOWN] entries
        """
        final_md = draft_context_md
        
        # Find all [UNKNOWN: ...] entries in the draft
        unknown_pattern = r'\[UNKNOWN:\s*([^\]]+)\]'
        unknown_matches = re.findall(unknown_pattern, final_md)
        
        # Replace each [UNKNOWN] with the corresponding answer
        for unknown_key in unknown_matches:
            # Try exact match first
            if unknown_key in interview_answers:
                answer = interview_answers[unknown_key]
            # Try with "UNKNOWN: " prefix
            elif f"UNKNOWN: {unknown_key}" in interview_answers:
                answer = interview_answers[f"UNKNOWN: {unknown_key}"]
            else:
                # No answer found — leave as [UNKNOWN]
                continue
            
            # Replace in the markdown
            pattern = rf'\[UNKNOWN:\s*{re.escape(unknown_key)}\]'
            final_md = re.sub(pattern, answer, final_md)
        
        # Append Change Log entry (for tracking bootstrap events)
        final_md = self._append_change_log_entry(
            final_md,
            "Cold bootstrap: inferred from codebase, filled gaps via interview"
        )
        
        # Validate
        self._validate_context_md(final_md)
        
        return final_md
    
    def _build_inference_prompt(
        self,
        payload: BootstrapPayload,
        change_request: str,
    ) -> str:
        """
        Build the prompt for the inference model.
        
        Includes:
          - Detected stack and patterns
          - Directory tree
          - File contents (prioritized)
          - The change request
          - Instructions to produce CONTEXT.md with [UNKNOWN] markers
        """
        
        file_list = "\n".join(
            f"  - {path} (~{len(content)//4} tokens)"
            for path, content in payload.file_contents.items()
        )
        
        file_contents_section = "\n".join(
            f"## {path}\n```\n{content[:500]}{'...' if len(content) > 500 else ''}\n```\n"
            for path, content in payload.file_contents.items()
        )
        
        prompt = f"""You are analyzing an existing codebase to produce a CONTEXT.md document for bootstrap/onboarding.

## Codebase Summary

**Detected Stack:** {', '.join(payload.detected_stack) or 'unknown'}
**Detected Patterns:** {', '.join(payload.detected_patterns) or 'none'}

**Directory Tree:**
```
{payload.file_tree}
```

**Files Read:**
{file_list}

**File Contents:**

{file_contents_section}

## Change Request

The user wants to make this change to the project:
{change_request}

## Your Task

Read the codebase carefully and produce a CONTEXT.md document that captures:

1. **Problem Statement** — What problem does this code solve? (infer from README, entry points)
2. **Business Context / Objectives** — Why does this exist? Who uses it? (infer if possible, mark [UNKNOWN] if not)
3. **Functional Requirements** — What does it do? List the main features. (infer from routes, functions, models)
4. **Non-Functional Requirements** — Performance, scale, compliance, SLA requirements? (mark [UNKNOWN] unless obvious)
5. **Tech Stack** — Languages, frameworks, databases, deployment. (infer from config and detected stack)
6. **Architecture** — How is it organized? (infer from directory structure and key files)
7. **Shared Vocabulary** — Domain-specific terms the team uses. (infer from code comments and naming, mark [UNKNOWN] for business terms you can't infer)
8. **Assumptions** — What assumptions does the codebase make? (infer what you can)

## Guidelines

- Use `[UNKNOWN: <what you need to know>]` for anything you cannot infer from the code.
- Be specific: `[UNKNOWN: SLA requirements for API endpoints]` not just `[UNKNOWN: performance]`.
- Group related unknowns: instead of separate [UNKNOWN] for each compliance requirement, group them as `[UNKNOWN: compliance and regulatory requirements]`.
- Format with Markdown headers for each section.
- Be concise but complete.

## Output Format

Produce ONLY the CONTEXT.md content. No preamble, no explanation, just the structured markdown.
You MUST use EXACTLY these Markdown headers (using # or ##):
# Problem Statement
# Business Context / Objectives
# Functional Requirements
# Non-Functional Requirements
# Tech Stack
# Architecture
# Shared Vocabulary
# Assumptions

---

"""
        return prompt
    
    def _call_lm_studio(self, prompt: str) -> str:
        """
        Call LM Studio API.
        
        Args:
            prompt: the full prompt text
        
        Returns:
            response text from the model
        
        Raises:
            RuntimeError: if the API call fails
        """
        import json
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests library not installed; install with: pip install requests")
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,  # Lower temperature for consistency
            "max_tokens": 2048,
        }
        
        try:
            response = requests.post(
                self.lm_studio_api,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        
        except Exception as e:
            raise RuntimeError(f"LM Studio API call failed: {e}")
    
    def _mock_inference_response(self) -> str:
        """
        Return a mock inference response for testing.
        
        Used when use_mock=True to avoid requiring LM Studio running.
        """
        return """# Problem Statement
Payment service handles transaction processing for the legacy billing system. Receives charge requests, validates payment information, and coordinates with gateway providers (Stripe, PayPal).

# Business Context / Objectives
[UNKNOWN: What is the business priority for this service? What SLA exists?]

Maintains historical transaction records for compliance and reconciliation.

# Functional Requirements
- POST /charges — accept charge request with amount, currency, customer info
- Return success/failure with transaction ID
- Store charge history with timestamps and provider response
- Support idempotency for charge endpoint (new requirement)
- Webhook handlers for payment provider callbacks

# Non-Functional Requirements
[UNKNOWN: Expected QPS and latency targets?]
[UNKNOWN: Data retention policy and compliance requirements (GDPR, PCI-DSS)?]
Should handle concurrent requests from multiple merchants.

# Tech Stack
- Python 3.9+
- FastAPI web framework
- PostgreSQL for transactional data
- Redis (detected in config, unclear if in use)
- Docker for deployment

# Architecture
Monolithic FastAPI service with routes organized by domain (charges, webhooks, utilities). Database models use SQLAlchemy ORM. Alembic migrations manage schema evolution.

Structure:
- app/routes/ — API endpoints
- app/models.py — domain models (Charge, Customer, etc.)
- alembic/versions/ — database migrations (currently 3 revisions)
- tests/ — unit and integration tests

# Shared Vocabulary
[UNKNOWN: What are the key domain terms (merchant, issuer, acquirer, settlement)? What do teams call these internally?]

- Transaction: atomic unit of work representing a charge attempt
- Gateway: external payment processor (Stripe, PayPal)
- Settlement: process of moving funds after successful transaction

# Assumptions
- PostgreSQL is the source of truth for transaction state
- Webhook callbacks from providers are idempotent and can be replayed
- Single-region deployment (no multi-region failover)

# Open Questions
- Why is Redis in pyproject but no imports found? Is it for future use or legacy?
- What is the relationship between this service and the "legacy billing system" mentioned in README?
- Are there compliance frameworks (PCI-DSS, SOC2) that constrain the design?

"""
    
    def _extract_context_md(self, response_text: str) -> str:
        """
        Extract the CONTEXT.md markdown from the model's response.
        
        The model should output ONLY the markdown, but in case there's preamble,
        we extract the first markdown section (starts with # or ##).
        """
        # Look for the first markdown header
        lines = response_text.split('\n')
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('#'):
                start_idx = i
                break
        
        # Return from first header to end
        return '\n'.join(lines[start_idx:]).strip()
    
    def _parse_unknown_entries(self, context_md: str) -> list[str]:
        """
        Extract all [UNKNOWN: ...] entries from the markdown.
        
        Returns:
            list of unknown keys (without the [UNKNOWN: ] brackets)
        """
        pattern = r'\[UNKNOWN:\s*([^\]]+)\]'
        matches = re.findall(pattern, context_md)
        return matches
    
    def _append_change_log_entry(self, context_md: str, entry: str) -> str:
        """
        Append or create a Change Log section in the CONTEXT.md.
        
        Args:
            context_md: existing CONTEXT.md
            entry: description of the change
        
        Returns:
            context_md with Change Log entry appended/updated
        """
        from datetime import datetime
        
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        change_entry = f"- {timestamp}: {entry}"
        
        # Check if Change Log section exists
        if "# Change Log" in context_md or "## Change Log" in context_md:
            # Append to existing Change Log
            pattern = r'(# Change Log.*?)(?=\n#|\Z)'
            match = re.search(pattern, context_md, re.DOTALL)
            if match:
                old_section = match.group(1)
                new_section = old_section.rstrip() + "\n" + change_entry
                context_md = context_md.replace(old_section, new_section)
        else:
            # Create new Change Log section at the end
            context_md = context_md.rstrip() + "\n\n# Change Log\n" + change_entry
        
        return context_md
    
    def _validate_context_md(self, context_md: str) -> None:
        """
        Validate that CONTEXT.md has all required sections and no unresolved [UNKNOWN] entries.
        
        Raises:
            ValueError: if validation fails
        """
        # Check for unresolved [UNKNOWN] entries
        unknown_pattern = r'\[UNKNOWN:[^\]]+\]'
        unknowns = re.findall(unknown_pattern, context_md)
        if unknowns:
            raise ValueError(
                f"CONTEXT.md contains unresolved [UNKNOWN] entries after finalise(): {unknowns}"
            )
        
        # Check for required sections
        missing_sections = []
        for section in self.REQUIRED_SECTIONS:
            # Check if section name appears in the document (case-insensitive)
            # This is more robust than strict regex for headers.
            if section.lower() not in context_md.lower():
                missing_sections.append(section)
        
        if missing_sections:
            raise ValueError(
                f"CONTEXT.md missing required sections: {', '.join(missing_sections)}"
            )
