"""
test_planner_orchestrator_integration.py

Real integration test for the Planner -> Orchestrator -> Executor chain.

WHAT "REAL" MEANS HERE:
    The only thing faked is the external LM Studio SDK boundary —
    `lms.llm(model_id).respond(prompt, config=...)` inside
    `src.core.gateway._lmstudio_run`. Everything downstream of that call
    is the real production code:
        - src.core.planner_v2.providers.LMStudioProvider.call()
        - src.core.planner_v2.planner.Planner.plan()
        - src.orchestrator.orchestrator.Orchestrator.plan_task()
        - src.orchestrator.orchestrator.Orchestrator.execute_plan()

    This is deliberately NOT the same as swapping in
    `providers.MockProvider` — that would skip LMStudioProvider.call()
    entirely (the prompt-flattening: "System: {system}\nUser Request:
    {user}") and skip _lmstudio_run's reasoning-leak strip. Faking one
    level lower (the SDK call itself) means both of those real code
    paths execute and can be asserted against.

ASSUMPTIONS — flagged because I have NOT seen these files and am
inferring their shape from planner.py / providers.py / orchestrator.py.
Fix the names below if they don't match:

    1. src.core.planner_v2.config.PlannerBuilder.build_default()
       returns a fully-wired Planner (real prompt_builder, parser,
       validator, plan_factory) that expects the LLM to return a JSON
       object shaped like:
           {"task_summary": str, "steps": [...], "reasoning": str}
       Adjust FAKE_PLAN_JSON below if the real schema differs
       (e.g. field names in TaskPlan / step schema).

    2. src.core.task_plan.TaskPlan has a `.steps` list and
       PlannerResponse has `.plan` and `.reasoning`, per planner.py.

    3. Orchestrator.execute_plan() requires tool_runtime to be set
       (raises RuntimeError otherwise) — confirmed directly in
       orchestrator.py, so this test calls set_project_root() first
       against a throwaway tmp_path directory.

    4. ExecutorBuilder / Executor / StepExecutorFactory are real and
       importable at src.core.executor.*, matching the tree in
       ARCHITECTURE_AFTER_STEP4.md. If a THINK or SKILL step type is
       selected by the fake plan, model_provider / skill_factory also
       need to be real-ish — this test sticks to a single READ_FILE
       tool step to avoid pulling in the skill factory / think executor
       paths, which need their own fakes I haven't built yet.

If any of these assumptions are wrong, the test will fail at import
or at the first Planner.plan() call with a clear AttributeError /
ImportError rather than silently passing — that's intentional.
"""

import json
import types
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.planner_v2.providers import LMStudioProvider
from src.core.planner_v2.config import PlannerBuilder
from src.orchestrator.orchestrator import Orchestrator


# ---------------------------------------------------------------------
# Fake LM Studio SDK boundary only — everything above this is real.
# ---------------------------------------------------------------------

FAKE_PLAN_JSON = {
    "task_summary": "Read the target file",
    "reasoning": "Single-step read to inspect current contents before editing.",
    "steps": [
        {
            "step_id": 0,
            "description": "Read main.py",
            "action_type": "read_file",
            "depends_on": [],
            "tool_invocation": {
                "tool_name": "read_file",
                "arguments": {"file_path": "main.py"},
            },
        }
    ],
}


class _FakeLMSResult:
    """Mimics the object returned by lms.llm(...).respond(...)."""

    def __init__(self, content: str):
        self.content = content


class _FakeLMSModel:
    """Mimics the object returned by lms.llm(model_id)."""

    def __init__(self, content: str):
        self._content = content
        self.last_prompt = None
        self.last_config = None

    def respond(self, prompt, config=None):
        # Record what LMStudioProvider actually sent, so we can assert
        # on the real prompt-flattening behavior in providers.py.
        self.last_prompt = prompt
        self.last_config = config
        
        if "goal-completion judge" in prompt:
            return _FakeLMSResult('{"outcome": "pass", "reasoning": "fake pass"}')
            
        return _FakeLMSResult(self._content)


@pytest.fixture
def fake_lms(monkeypatch):
    """
    Patches `lms.llm` inside src.core.gateway (where _lmstudio_run
    imports it as `import lmstudio as lms`) so every call to the SDK
    returns FAKE_PLAN_JSON as a JSON string, regardless of model_id.

    Real code paths still exercised: LMStudioProvider.call() ->
    _lmstudio_run() -> lms.llm(...).respond(...) -> reasoning-strip ->
    Planner's real ResponseParser / PlanValidator / PlanFactory.
    """
    fake_model = _FakeLMSModel(json.dumps(FAKE_PLAN_JSON))

    def fake_llm(model_id):
        return fake_model

    fake_lms_module = types.SimpleNamespace(llm=fake_llm)
    monkeypatch.setattr("src.core.gateway.lms", fake_lms_module)
    return fake_model


@pytest.fixture
def project_root(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('hello')\n")
    return tmp_path


@pytest.fixture
def orchestrator_with_context(project_root, monkeypatch):
    """
    Real Orchestrator, real ContextStore, but with a CONTEXT.md
    pre-seeded so plan_task() doesn't require running the grilling
    interview first.
    """
    orch = Orchestrator(project_root=project_root)
    orch.context_store.save(
        "test-project",
        "### Problem Statement\nA tiny test project.\n",
    )
    return orch


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

class TestLMStudioProviderRealCall:
    """
    Confirms LMStudioProvider.call()'s actual behavior against the
    signature every evaluator/replanner assumes:
        call(system_prompt, user_prompt, temperature, max_tokens) -> str
    """

    def test_call_returns_string_and_flattens_prompt(self, fake_lms):
        provider = LMStudioProvider("google/gemma-4-e2b")

        result = provider.call(
            system_prompt="You are a planner.",
            user_prompt="Plan: read main.py",
            temperature=0.1,
            max_tokens=2048,
        )

        assert isinstance(result, str)
        assert json.loads(result) == FAKE_PLAN_JSON

        # Assert the real flattening behavior in providers.py actually ran.
        assert "System: You are a planner." in fake_lms.last_prompt
        assert "User Request: Plan: read main.py" in fake_lms.last_prompt

        # Assert temperature/max_tokens were actually forwarded to the SDK.
        assert fake_lms.last_config == {"max_tokens": 2048, "temperature": 0.1}


class TestPlannerRealIntegration:
    """
    Drives the real Planner (via PlannerBuilder.build_default()) through
    a fake-SDK-backed LMStudioProvider, with no MockProvider anywhere.
    """

    def test_plan_task_returns_valid_plan(self, orchestrator_with_context, fake_lms):
        orch = orchestrator_with_context

        response = orch.plan_task(
            "Read main.py before editing it", project_id="test-project"
        )

        assert response.plan is not None
        assert len(response.plan.steps) == 1
        assert response.reasoning == FAKE_PLAN_JSON["reasoning"]

    def test_plan_task_missing_context_raises(self, orchestrator_with_context, fake_lms):
        orch = orchestrator_with_context
        with pytest.raises(ValueError):
            orch.plan_task("do something", project_id="nonexistent-project")


class TestExecutePlanRealIntegration:
    """
    End-to-end: plan_task() -> execute_plan(), against a real
    tool_runtime rooted at a tmp_path, with the LM Studio SDK faked
    at the boundary. Uses a single READ_FILE step to avoid needing
    fakes for the THINK/SKILL executor paths.
    """

    def test_plan_then_execute_reads_real_file(
        self, orchestrator_with_context, fake_lms, project_root
    ):
        orch = orchestrator_with_context

        planner_response = orch.plan_task(
            "Read main.py before editing it", project_id="test-project"
        )

        result = orch.execute_plan(
            planner_response.plan,
            task_id="test-project-readmain",
            original_task="Read main.py before editing it",
        )

        assert 0 in result.completed_steps
        assert result.failed_steps == set() or not result.failed_steps
        # main.py's real contents should have flowed through the real
        # ToolStepExecutor -> tool_runtime -> read_file tool.
        assert "hello" in result.context_snapshot.get(0, "")

    def test_execute_plan_without_project_root_raises(self, fake_lms):
        # No project_root passed to Orchestrator() -> tool_runtime is None.
        orch = Orchestrator()
        orch.context_store.save(
            "no-root-project", "### Problem Statement\nX\n"
        )
        planner_response = orch.plan_task(
            "Read main.py", project_id="no-root-project"
        )
        with pytest.raises(RuntimeError):
            orch.execute_plan(
                planner_response.plan,
                task_id="no-root-project-x",
                original_task="Read main.py",
            )