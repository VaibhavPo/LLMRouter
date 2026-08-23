"""
skills.grilling_runner

Public interface:
    runner = GrillingRunner(model_id, model_runner)
    
    # FULL GRILLING (new project):
    msg1 = runner.start_interview(project_description)
    msg2 = runner.continue_interview(user_answer)
    ...
    result = runner.finalize()  # produces full CONTEXT.md
    
    # DELTA GRILLING (modify existing project):
    msg1 = runner.start_delta_interview(context_md, change_request, affected_sections)
    msg2 = runner.continue_delta_interview(user_answer)
    ...
    delta_result = runner.finalize_delta(affected_sections)  # produces answers dict

Grilling is interactive and stateful, unlike tdd/diagnosis which are one-shot.
The runner maintains conversation history and passes it as context to each call.

This is a deep module — only public methods, everything else private.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.core.gateway import _lmstudio_run

_SKILL_DIR = Path(__file__).parent.parent / "skills" / "procedures"
_GRILLING_SKILL_PATH = _SKILL_DIR / "grilling.md"
_DELTA_GRILLING_SKILL_PATH = _SKILL_DIR / "delta_grill.md"

GRILLING_MODEL_ID = "google/gemma-4-e2b"
MAX_QUESTIONS = 25
MAX_DELTA_QUESTIONS = 5


@dataclass
class InterviewMessage:
    """A single turn in the grilling conversation."""
    speaker: str  # "assistant" or "user"
    content: str


@dataclass
class DiagnosticMessage:
    """What the runner returns after each turn."""
    question: str
    ask_count: int
    is_finalizing: bool = False


@dataclass
class GrillingResult:
    """Final output after finalize() — full CONTEXT.md."""
    context_md: str
    conversation_history: list = field(default_factory=list)
    ask_count: int = 0
    successfully_finalized: bool = False


@dataclass
class DeltaGrillingResult:
    """Final output after finalize_delta() — structured answers for patch."""
    answers: dict[str, str]           # {section_name: answer_text}
    change_summary: str               # one-line summary for Change Log
    conversation_history: list = field(default_factory=list)
    ask_count: int = 0
    successfully_finalized: bool = False


class DeltaFinalizationError(Exception):
    """Raised when delta interview JSON can't be parsed. Orchestrator.modify()
    catches this and offers manual-edit fallback."""
    pass


class GrillingRunner:
    """
    Stateful interview conductor. Maintains conversation history for both
    full grilling (new project) and delta grilling (modify existing).
    """

    def __init__(
        self,
        model_id: str = GRILLING_MODEL_ID,
        model_runner: Optional[Callable[[str, str], str]] = None,
    ):
        self.model_id = model_id
        self._model_runner = model_runner or _lmstudio_run
        self._conversation_history: list[InterviewMessage] = []
        self._ask_count = 0
        self._system_prompt = self._load_system_prompt()
        self._delta_system_prompt: Optional[str] = None

    def _load_system_prompt(self) -> str:
        return _GRILLING_SKILL_PATH.read_text(encoding="utf-8")

    def _load_delta_system_prompt(self) -> str:
        if self._delta_system_prompt is None:
            self._delta_system_prompt = _DELTA_GRILLING_SKILL_PATH.read_text(encoding="utf-8")
        return self._delta_system_prompt

    def _build_prompt_with_history(self, new_user_input: str = "") -> str:
        """
        Constructs the prompt: system + conversation history + new input.
        This is how we maintain context across multiple calls.
        Used only by full grilling (start_interview, continue_interview).
        """
        history_text = "\n".join(
            f"{msg.speaker.upper()}: {msg.content}"
            for msg in self._conversation_history
        )
        if history_text:
            history_text += "\n"

        if new_user_input:
            history_text += f"USER: {new_user_input}\nASSISTANT:"
        else:
            history_text += "ASSISTANT:"

        return f"{self._system_prompt}\n\n--- Conversation ---\n{history_text}"

    def _extract_finalization(self, response: str) -> tuple[str, bool]:
        """
        Check if the response is finalizing (saying it's ready to write CONTEXT.md).
        If it is, try to extract the CONTEXT.md from the same response.
        Used only by full grilling.
        """
        finalization_marker = "let me write context.md"
        is_finalizing = finalization_marker.lower() in response.lower()

        if is_finalizing:
            context_match = re.search(
                r"(### Problem Statement.*)",
                response,
                re.IGNORECASE | re.DOTALL
            )
            context_md = context_match.group(1) if context_match else ""
            return context_md, True

        return "", False

    # ========== FULL GRILLING (new project) ==========

    def start_interview(self, project_description: str) -> DiagnosticMessage:
        """
        Begin the full grilling conversation. Ask the first question.
        Resets conversation history — does not mix with prior delta interviews.
        """
        self._conversation_history = []
        self._ask_count = 0

        prompt = self._build_prompt_with_history(project_description)
        response = self._model_runner(self.model_id, prompt)

        self._ask_count += 1
        self._conversation_history.append(InterviewMessage("user", project_description))
        self._conversation_history.append(InterviewMessage("assistant", response))

        return DiagnosticMessage(
            question=response,
            ask_count=self._ask_count,
            is_finalizing=False,
        )

    def continue_interview(self, user_answer: str) -> DiagnosticMessage:
        """
        Continue the full grilling conversation with a user's answer.
        Model may ask a follow-up or move to a new area.
        """
        if self._ask_count >= MAX_QUESTIONS:
            raise RuntimeError(
                f"Reached max questions ({MAX_QUESTIONS}). Call finalize() instead."
            )

        prompt = self._build_prompt_with_history(user_answer)
        response = self._model_runner(self.model_id, prompt)

        self._ask_count += 1
        self._conversation_history.append(InterviewMessage("user", user_answer))
        self._conversation_history.append(InterviewMessage("assistant", response))

        context_md, is_finalizing = self._extract_finalization(response)

        if is_finalizing:
            return DiagnosticMessage(
                question=context_md if context_md else response,
                ask_count=self._ask_count,
                is_finalizing=True,
            )

        return DiagnosticMessage(
            question=response,
            ask_count=self._ask_count,
            is_finalizing=False,
        )

    def finalize(self) -> GrillingResult:
        """
        Force finalization of full grilling. Tell the model to write CONTEXT.md now.
        Called when the user or orchestrator decides "we have enough info."
        """
        finalize_prompt = (
            self._build_prompt_with_history(
                "We have enough information now. Please write CONTEXT.md with all "
                "sections (Problem Statement, Functional Requirements, Non-Functional Requirements, "
                "Assumptions, Risks and Constraints, Design Trade-offs, Shared Vocabulary, Open Questions)."
            )
        )

        response = self._model_runner(self.model_id, finalize_prompt)
        self._ask_count += 1

        context_md, _ = self._extract_finalization(response)
        if not context_md:
            context_md = response

        self._conversation_history.append(
            InterviewMessage("user", "Please write CONTEXT.md now.")
        )
        self._conversation_history.append(InterviewMessage("assistant", response))

        return GrillingResult(
            context_md=context_md,
            conversation_history=self._conversation_history,
            ask_count=self._ask_count,
            successfully_finalized=True,
        )

    # ========== DELTA GRILLING (modify existing project) ==========

    def start_delta_interview(
        self,
        context_md: str,
        change_request: str,
        affected_sections: list[str],
    ) -> DiagnosticMessage:
        """
        Begin a SCOPED interview about a single change to an existing project.
        Seeded with existing CONTEXT.md and flagged sections.
        Resets conversation history — does not mix with prior full grilling.
        """
        self._conversation_history = []
        self._ask_count = 0

        sections_note = ", ".join(affected_sections) if affected_sections else "unspecified"
        delta_system = self._load_delta_system_prompt()

        seed = (
            f"EXISTING CONTEXT.md:\n{context_md}\n\n"
            f"PROPOSED CHANGE:\n{change_request}\n\n"
            f"FLAGGED SECTIONS: {sections_note}\n\n"
            f"Ask ONLY what's needed to resolve ambiguity in this specific change. "
            f"Do not re-ask anything already answered in the existing CONTEXT.md. "
            f"Aim for 3-5 questions maximum."
        )

        prompt = f"{delta_system}\n\n--- Delta Interview ---\nUSER: {seed}\nASSISTANT:"
        response = self._model_runner(self.model_id, prompt)

        self._ask_count += 1
        self._conversation_history.append(InterviewMessage("user", seed))
        self._conversation_history.append(InterviewMessage("assistant", response))

        return DiagnosticMessage(
            question=response,
            ask_count=self._ask_count,
            is_finalizing=False,
        )

    def continue_delta_interview(self, user_answer: str) -> DiagnosticMessage:
        """
        Continue the scoped delta interview. Hard ceiling at MAX_DELTA_QUESTIONS.
        """
        if self._ask_count >= MAX_DELTA_QUESTIONS:
            raise RuntimeError(
                f"Reached max delta questions ({MAX_DELTA_QUESTIONS}). "
                f"Call finalize_delta() instead."
            )

        delta_system = self._load_delta_system_prompt()
        history_text = "\n".join(
            f"{msg.speaker.upper()}: {msg.content}" for msg in self._conversation_history
        )
        prompt = (
            f"{delta_system}\n\n--- Delta Interview ---\n"
            f"{history_text}\nUSER: {user_answer}\nASSISTANT:"
        )
        response = self._model_runner(self.model_id, prompt)

        self._ask_count += 1
        self._conversation_history.append(InterviewMessage("user", user_answer))
        self._conversation_history.append(InterviewMessage("assistant", response))

        return DiagnosticMessage(
            question=response,
            ask_count=self._ask_count,
            is_finalizing=False,
        )

    def finalize_delta(self, affected_sections: list[str]) -> DeltaGrillingResult:
        """
        Force finalization of the delta interview. Asks the model to summarize
        its answers as {section: answer} pairs, not a full CONTEXT.md rewrite.
        
        Raises DeltaFinalizationError if JSON can't be parsed — never silently
        writes malformed content. Orchestrator.modify() catches this and offers
        manual-edit fallback.
        """
        delta_system = self._load_delta_system_prompt()
        history_text = "\n".join(
            f"{msg.speaker.upper()}: {msg.content}" for msg in self._conversation_history
        )
        
        finalize_instruction = (
            "We have enough information about this specific change. Respond with "
            "ONLY a JSON object of this shape, no other text: "
            '{"answers": {"<section name>": "<what changed, in prose>", ...}, '
            '"change_summary": "<one sentence for a changelog>"}. '
            f"Only include keys from this list: {affected_sections}."
        )
        
        prompt = (
            f"{delta_system}\n\n--- Delta Interview ---\n"
            f"{history_text}\nUSER: {finalize_instruction}\nASSISTANT:"
        )
        response = self._model_runner(self.model_id, prompt)
        self._ask_count += 1

        self._conversation_history.append(InterviewMessage("user", finalize_instruction))
        self._conversation_history.append(InterviewMessage("assistant", response))

        # Parse JSON — fail loud
        json_start = response.find("{")
        json_end = response.rfind("}")
        if json_start == -1:
            raise DeltaFinalizationError(
                f"No JSON object found in delta finalization response: {response!r}"
            )

        try:
            data = json.loads(response[json_start:json_end + 1])
            answers = data.get("answers", {})
            change_summary = data.get("change_summary", "")
            
            if not answers or not change_summary:
                raise DeltaFinalizationError(
                    f"Delta finalization JSON missing 'answers' or 'change_summary': {data!r}"
                )
        except json.JSONDecodeError as e:
            raise DeltaFinalizationError(f"Malformed JSON in delta finalization: {e}") from e

        return DeltaGrillingResult(
            answers=answers,
            change_summary=change_summary,
            conversation_history=self._conversation_history,
            ask_count=self._ask_count,
            successfully_finalized=True,
        )