# src/orchestrator/orchestrator.py (UPDATED)
"""
orchestrator.py

Workflow orchestration: decides whether to grill, retrieves/stores CONTEXT.md,
routes to LLMGateway for code/diagnosis, and handles modify workflows.

Public interface:
    orchestrator = Orchestrator(project_root="/path/to/repo")
    result = orchestrator.run(user_request, project_id=None)
    modify_result = orchestrator.modify(project_id, change_request)
"""

from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from src.bootstrap.codebase_reader import CodebaseReader
from src.bootstrap.bootstrap_runner import BootstrapRunner
from src.bootstrap.bootstrap_interviewer import BootstrapInterviewer
from src.core.tool_runtime import ToolRegistry
from src.core.planner_v2.config import PlannerBuilder
from src.core.task_plan import PlannerResponse, TaskPlan
from src.core.executor.executor import ExecutorBuilder
from src.core.executor.interfaces import ExecutionResult
from src.orchestrator.triviality_judge import classify_change
from src.orchestrator.modify import merge_context
from src.context.context_store import ContextStore
from src.core import LLMGateway
from src.orchestrator.grilling import (
    GrillingRunner,
    DeltaFinalizationError,
)


@dataclass
class OrchestrationResult:
    """Result of running the orchestrator."""
    response: str
    context_md: Optional[str]
    project_id: str
    used_grilling: bool
    used_gateway: bool
    used_planning: bool = False


@dataclass
class ModifyResult:
    """Result of running modify()."""
    response: str
    updated_context_md: str
    project_id: str
    was_trivial: bool
    sections_updated: list[str]
    merge_warnings: list[str]  # e.g., ["Nonexistent Section: Foo"]


class Orchestrator:
    """
    Main workflow orchestrator. Decides whether to grill, manages CONTEXT.md,
    routes to code/diagnosis via LLMGateway, and handles modify workflows.
    
    Properly manages tool runtime boundaries per project.
    """

    def __init__(
        self,
        context_store: Optional[ContextStore] = None,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize orchestrator.
        
        Args:
            context_store: Where to store/load CONTEXT.md files. Defaults to local file store.
            project_root: Filesystem root for tool runtime boundaries. Can be set later
                         via set_project_root() before calling modify/run.
        """
        self.context_store = context_store or ContextStore()
        self.grilling_runner = GrillingRunner()
        self.gateway = LLMGateway()
        
        # Tool runtime — validate and initialize
        if project_root is not None:
            project_root = Path(project_root).resolve()
            if not project_root.exists():
                raise ValueError(f"project_root does not exist: {project_root}")
            if not project_root.is_dir():
                raise ValueError(f"project_root is not a directory: {project_root}")
        
        self.project_root = project_root
        self.tool_runtime = ToolRegistry(str(project_root)) if project_root else None
        
        # Initialize planner with builder
        planner_builder = PlannerBuilder()
        self.planner = planner_builder.build_default()

        # Executor wiring — built lazily since it needs tool_runtime,
        # which may not be set until set_project_root() is called.
        self._executor_builder: Optional[ExecutorBuilder] = None
        self._model_provider = None
        self._checkpoint_model_provider = None
        self._skill_factory = None
        self._history_store = None
        self.history_storage_dir = "execution_history"

    def _get_model_provider(self):
        """
        Lazily construct the LLMProvider used for THINK/DESIGN steps.

        Resolves via ModelTier.HIGH_REASONING (model_tiers.py) rather
        than hardcoding a model_id here, so this stays in sync with
        whatever the Planner itself resolves to instead of drifting
        into its own separately-hardcoded model.
        """
        if self._model_provider is None:
            from src.core.planner_v2.providers import LMStudioProvider
            from src.core.model_tiers import ModelTier, resolve_tier
            self._model_provider = LMStudioProvider(resolve_tier(ModelTier.HIGH_REASONING))
        return self._model_provider

    def _get_skill_factory(self):
        """
        Lazily construct the SkillFactory used for SKILL_WORKFLOW steps.

        ASSUMPTION: src.skills.skill_factory.SkillFactory takes no
        required constructor args. Adjust if it needs the tool_runtime,
        project_root, or a procedures path.
        """
        if self._skill_factory is None:
            from src.skills.skill_factory import SkillFactory
            self._skill_factory = SkillFactory()
        return self._skill_factory

    def _get_checkpoint_model_provider(self):
        """
        Lazily construct the LLMProvider used for checkpoint verdicts
        (VALID/UNCERTAIN/INVALID/UNRECOVERABLE).

        Resolves via ModelTier.MID_REASONING, falling back to
        HIGH_REASONING if MID_REASONING has no model assigned yet (see
        model_tiers.py — no lightweight model has been benchmarked
        specifically for checkpoint-verdict JSON as of this writing;
        qwen3-1.7b is only proven "usable with caveats" as a plain
        classifier, not this task). The fallback is intentionally
        conservative rather than cheap: it never silently promotes an
        unbenchmarked model into a live-router role. Once a cheap tier
        is benchmarked for this specific task, assign it in
        model_tiers.py's _TIER_REGISTRY[ModelTier.MID_REASONING] and
        this resolves automatically — no call-site changes needed.
        """
        if self._checkpoint_model_provider is None:
            from src.core.planner_v2.providers import LMStudioProvider
            from src.core.model_tiers import ModelTier, resolve_tier
            model_id = resolve_tier(ModelTier.MID_REASONING, fallback_tier=ModelTier.HIGH_REASONING)
            self._checkpoint_model_provider = LMStudioProvider(model_id)
        return self._checkpoint_model_provider

    def execute_plan(
        self,
        plan: TaskPlan,
        task_id: str,
        original_task: str,
        model_provider=None,
        skill_factory=None,
        checkpoint_model_provider=None,
        final_validation_model_provider=None,
    ) -> ExecutionResult:
        """
        Execute a TaskPlan via the checkpoint/evidence-based Executor.

        Requires tool_runtime to be initialized (project_root set), since
        ToolStepExecutor/VerifyStepExecutor dispatch through it.

        Args:
            plan: TaskPlan to execute (typically planner_response.plan
                  from plan_task())
            task_id: identifies this *task* across attempts, used for
                     ExecutionHistoryStore lookup/relevant_history_text on
                     a future planning call for the same task. Callers
                     that don't want history persisted at all can still
                     pass any stable string here -- history simply won't
                     be read back unless the same task_id recurs.
            original_task: human-readable goal, persisted alongside
                            task_id in ExecutionHistoryStore.
            model_provider: Optional LLMProvider override for THINK/DESIGN
                             steps and for local/full replanning (strong
                             tier). Defaults to _get_model_provider()
                             (ModelTier.HIGH_REASONING).
            skill_factory: Optional SkillFactory override for
                            SKILL_WORKFLOW steps. Defaults to
                            _get_skill_factory().
            checkpoint_model_provider: Optional LLMProvider override for
                             checkpoint verdicts (cheap tier). Defaults to
                             _get_checkpoint_model_provider() -- see that
                             method's docstring for why the default is
                             conservative rather than actually cheap.
            final_validation_model_provider: Optional LLMProvider override
                             for final goal validation (strong tier, same
                             as replanning). Defaults to
                             _get_model_provider() (ModelTier.HIGH_REASONING).

                             IMPORTANT: previously this was never passed to
                             ExecutorBuilder.build() at all, which meant
                             final_validator silently defaulted to
                             NoopFinalValidator -- every execution declared
                             "success" the moment all steps completed,
                             regardless of whether the actual goal was met.
                             That's now fixed: a real ModelFinalValidator
                             runs by default. If you actually want the old
                             Noop behavior (e.g. a fast dev loop where you
                             don't want an extra LLM call per execution),
                             pass a NoopFinalValidator-backed provider
                             explicitly rather than relying on an implicit
                             default -- silent opt-out was the bug.

        Returns:
            ExecutionResult with completed/failed/skipped steps,
            final_outcome ("success"/"failure"/"aborted"), and
            replan_count.

        Raises:
            RuntimeError: if tool_runtime is not initialized.
        """
        if self.tool_runtime is None:
            raise RuntimeError(
                "Tool runtime not initialized. Call set_project_root() first, "
                "or initialize Orchestrator with project_root parameter."
            )

        if self._executor_builder is None:
            self._executor_builder = ExecutorBuilder(self.tool_runtime)

        resolved_model_provider = model_provider or self._get_model_provider()

        executor = self._executor_builder.build(
            model_provider=resolved_model_provider,
            skill_factory=skill_factory or self._get_skill_factory(),
            checkpoint_model_provider=checkpoint_model_provider or self._get_checkpoint_model_provider(),
            # replan_model_provider intentionally omitted: ExecutorBuilder.build()
            # already defaults it to model_provider, which is HIGH_REASONING --
            # matching LocalReplanner/FullReplanner's own "strong tier" requirement.
            final_validation_model_provider=(
                final_validation_model_provider or resolved_model_provider
            ),
            history_storage_dir=self.history_storage_dir,
            tool_descriptions=self.get_tool_descriptions(),
        )

        return executor.execute(plan, task_id=task_id, original_task=original_task)

    def plan_and_execute(
        self,
        user_request: str,
        project_id: str,
    ) -> ExecutionResult:
        """
        Convenience: plan a task, then execute it immediately.

        For interactive flows where the user should confirm the plan
        before execution, call plan_task() and execute_plan() separately
        instead (see cli/main.py's `execute` command).
        """
        planner_response = self.plan_task(user_request, project_id)
        task_id = self._generate_task_id(project_id, user_request)
        return self.execute_plan(planner_response.plan, task_id=task_id, original_task=user_request)

    def _generate_task_id(self, project_id: str, user_request: str) -> str:
        """
        Scopes ExecutionHistoryStore attempts to (project, specific
        request). Reusing project_id alone would merge history across
        unrelated requests within the same project, which would defeat
        relevant_history_text()'s point -- a retry of request B would see
        failures from an unrelated earlier request A.
        """
        import hashlib
        request_hash = hashlib.sha1(user_request.encode("utf-8")).hexdigest()[:8]
        return f"{project_id}-{request_hash}"

    def _get_history_store(self):
        """
        Lazily construct the ExecutionHistoryStore, shared between
        plan_task() (reads relevant prior failures before planning) and
        execute_plan() (writes new attempts/failures during execution).

        Both need to point at the same history_storage_dir so a failure
        written during execute_plan() is actually visible to plan_task()
        on the next attempt for the same task_id. Returns None if
        history_storage_dir isn't set (history is fully optional).
        """
        if self._history_store is None and self.history_storage_dir:
            from src.core.executor.execution_history import ExecutionHistoryStore
            self._history_store = ExecutionHistoryStore(self.history_storage_dir)
        return self._history_store

    def _get_prior_failure_summary(self, project_id: str, user_request: str, max_chars: int = 800) -> str:
        """
        Fetch a compact summary of the most relevant prior failed attempt
        at this same task, for the planner to avoid repeating -- NOT the
        full execution history.

        NOTE: this reuses ExecutionHistoryStore.relevant_history_text(),
        the same method FullReplanner already calls. I haven't seen
        execution_history.py's implementation, so I can't confirm it
        already filters down to "just the single most relevant failure"
        the way a get_last_failed_attempt()-style method would -- it may
        return more than that. The max_chars truncation below is a
        defensive cap, not a real fix for that if relevant_history_text()
        turns out to return multi-attempt detail. If truncated output
        looks unhelpful in practice (cut off mid-sentence, or missing the
        actually-relevant failure because it truncated the wrong end),
        that's the signal a purpose-built method is needed instead --
        send execution_history.py and this can be tightened properly.
        """
        history = self._get_history_store()
        if history is None:
            return ""

        task_id = self._generate_task_id(project_id, user_request)
        try:
            text = history.relevant_history_text(task_id)
        except Exception as e:
            # History being unavailable/corrupt should never block planning.
            print(f"⚠️  Could not load execution history (continuing without it): {e}")
            return ""

        if not text:
            return ""
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n...(truncated)"
        return text

    def plan_task(self, user_request: str, project_id: str) -> PlannerResponse:
        """
        Generate a TaskPlan for a user request.
        
        Args:
            user_request: What the user wants done
            project_id: Project to pull CONTEXT.md from
        
        Returns:
            PlannerResponse with TaskPlan
        """
        context_md = self.context_store.load(project_id)
        if context_md is None:
            raise ValueError(f"No CONTEXT.md for project {project_id}")
        
        tool_descriptions = self.get_tool_descriptions()

        prior_failure = self._get_prior_failure_summary(project_id, user_request)
        if prior_failure:
            print(f"\nFound a relevant prior failure for this task -- including it in planning context.")

        return self.planner.plan(user_request, context_md, tool_descriptions, prior_failure=prior_failure)
    
    def set_project_root(self, project_root: str | Path):
        """
        Set or update the project root for tool execution.
        Call this before modify() if orchestrator was initialized without a project_root.
        """
        project_root = Path(project_root).resolve()
        if not project_root.exists():
            raise ValueError(f"project_root does not exist: {project_root}")
        if not project_root.is_dir():
            raise ValueError(f"project_root is not a directory: {project_root}")
        
        self.project_root = project_root
        self.tool_runtime = ToolRegistry(str(project_root))
    
    def execute_tool(self, tool_name: str, args: dict):
        """
        Execute a tool request. Requires project_root to be set.
        
        Args:
            tool_name: Name of the tool (e.g., "read_file", "list_files")
            args: Arguments for the tool (e.g., {"file_path": "src/main.py"})
        
        Returns:
            ToolResult with success/output/error
        
        Raises:
            RuntimeError: if tool_runtime is not initialized
        """
        if self.tool_runtime is None:
            raise RuntimeError(
                "Tool runtime not initialized. Call set_project_root() first, "
                "or initialize Orchestrator with project_root parameter."
            )
        
        from src.tools.schemas import ToolRequest
        request = ToolRequest(tool_name=tool_name, arguments=args)
        result = self.tool_runtime.execute(request)
        return result
    
    def get_tool_descriptions(self) -> dict:
        """
        Return human-readable descriptions of available tools for planner.
        Includes usage examples and approximate context cost.
        """
        return {
            "read_file": {
                "description": "Read a file or specific lines from a file",
                "usage": [
                    "read_file(file_path='src/gateway.py')",
                    "read_file(file_path='src/gateway.py', start_line=47, end_line=95)",
                ],
                "required_arguments": ["file_path"],
                "optional_arguments": ["start_line (int)", "end_line (int)"],
                "context_cost": "50–300 tokens depending on range",
                "safety_tier": "readonly",
            },
            "list_files": {
                "description": "List files and directories in a path with metadata",
                "usage": ["list_files(path='src')"],
                "required_arguments": [],
                "optional_arguments": ["path (default '.')", "include_hidden (bool)", "recursive (bool)"],
                "context_cost": "10–50 tokens",
                "safety_tier": "readonly",
            },
            "search_code": {
                "description": (
                    "Search for text or regex patterns in code files. The "
                    "search term MUST be passed as 'pattern' — not 'query', "
                    "not 'search_term'. There is no other accepted key for it."
                ),
                "usage": [
                    "search_code(pattern='def handle', path='src/core')",
                    "search_code(pattern='TODO', max_results=5)",
                ],
                "required_arguments": ["pattern"],
                "optional_arguments": ["path", "max_results (int)"],
                "context_cost": "50–200 tokens depending on matches",
                "safety_tier": "readonly",
            },
            "write_file": {
                "description": (
                    "Write content to a file, creating it and any parent "
                    "directories if they don't exist. Overwrites the "
                    "entire file if it already exists — use edit_file "
                    "instead if you only want to change part of an "
                    "existing file."
                ),
                "usage": [
                    "write_file(file_path='src/new_module.py', content='...')",
                ],
                "required_arguments": ["file_path", "content (string)"],
                "context_cost": "varies with content length",
                "safety_tier": "write_local",
            },
            "edit_file": {
                "description": (
                    "Edit an EXISTING file via exact string replacement. "
                    "old_str must be an exact, verbatim substring of the "
                    "file's current contents (read the file first to copy "
                    "it precisely) — this is NOT a natural-language "
                    "instruction like 'add a class here'. If old_str "
                    "appears more than once in the file, either make it "
                    "more specific (include surrounding context lines) or "
                    "pass replace_all=true. Fails if old_str is not found "
                    "verbatim, or if the file doesn't exist (use "
                    "write_file for new files)."
                ),
                "usage": [
                    "edit_file(file_path='layout/theme.liquid', "
                    "old_str='<body>', new_str='<body class=\"floating\">')",
                    "edit_file(file_path='assets/base.css', "
                    "old_str='.card { }', new_str='.card { animation: float 3s ease-in-out infinite; }')",
                ],
                "required_arguments": [
                    "file_path",
                    "old_str (exact substring, non-empty, must appear in file)",
                    "new_str",
                ],
                "optional_arguments": ["replace_all (bool, default false — required if old_str appears more than once)"],
                "context_cost": "varies with content length",
                "safety_tier": "write_local",
            },
        }

    def run(
        self,
        user_request: str,
        project_id: Optional[str] = None,
        skip_grilling: bool = False,
    ) -> OrchestrationResult:
        """
        Main entry point for new/work workflows.
        Routes the user request through the grilling → code pipeline.
        """
        context_md = None
        used_grilling = False
        used_gateway = False

        if project_id is None:
            project_id = self._generate_project_id(user_request)

        # Load or grill
        if not skip_grilling:
            if not self.context_store.exists(project_id):
                context_md = self._run_grilling(user_request)
                if context_md is None:
                    return OrchestrationResult(
                        response="",
                        context_md=None,
                        project_id=project_id,
                        used_grilling=False,
                        used_gateway=False,
                    )
                self.context_store.save(project_id, context_md)
                used_grilling = True
            else:
                context_md = self.context_store.load(project_id)
        else:
            # skip_grilling=True: still load existing context if available
            if self.context_store.exists(project_id):
                context_md = self.context_store.load(project_id)

        # Decide plan-vs-direct once per request, using the same
        # classifier LLMGateway already runs internally. This does NOT
        # call the LLM twice for the direct path: classify_only() here
        # IS the classification handle() would have run anyway, so we
        # reuse it below instead of letting handle() re-classify.
        used_planning = False
        try:
            classification = self.gateway.classify_only(user_request)
        except Exception as e:
            # Classifier failure: fail toward the cheaper path (direct
            # gateway), not toward planning. Mirrors modify()'s existing
            # "classifier error -> default to safer/simpler" pattern,
            # inverted here since for planning the *safe* default is
            # "don't invoke the heavier multi-step machinery."
            print(f"⚠️  Classifier error (skipping planning): {e}")
            classification = None

        can_plan = (
            classification is not None
            and classification.requires_planning
            and self.tool_runtime is not None
        )

        if classification is not None and classification.requires_planning and self.tool_runtime is None:
            print(
                "\n⚠️  This request looks like it needs multi-step planning, "
                "but no project_root is set (tool execution unavailable). "
                "Falling back to a direct response. Run 'set-root <path>' "
                "first to enable planning for requests like this."
            )

        if can_plan:
            print(f"\nRequest classified as needing planning — running Planner + Executor...")
            try:
                planner_response = self.plan_task(user_request, project_id)
                task_id = self._generate_task_id(project_id, user_request)
                exec_result = self.execute_plan(
                    planner_response.plan,
                    task_id=task_id,
                    original_task=user_request,
                )
                response = exec_result.summary() if hasattr(exec_result, "summary") else str(exec_result)
                used_planning = True
            except Exception as e:
                # Planning/execution failed outright: fall back to the
                # direct gateway path rather than surfacing a raw
                # exception, same fail-soft posture as the classifier
                # error handling above.
                print(f"⚠️  Planning/execution failed ({e}), falling back to direct response...")
                response = self.gateway.handle(user_request, context_md=context_md)
        else:
            print(f"\nProcessing request with LLMGateway...")
            response = self.gateway.handle(
                user_request,
                context_md=context_md,
                _precomputed_classification=classification,
            )

        used_gateway = not used_planning

        return OrchestrationResult(
            response=response,
            context_md=context_md,
            project_id=project_id,
            used_grilling=used_grilling,
            used_gateway=used_gateway,
            used_planning=used_planning,
        )

    def modify(self, project_id: str, change_request: str) -> ModifyResult:
        """
        Modify an existing project: judge triviality, optionally delta-grill,
        merge into CONTEXT.md, route to gateway, and save.
        
        Flow:
          1. Load existing CONTEXT.md
          2a. If found: classify change, delta-grill if significant, merge, route to gateway
          2b. If NOT found: enter cold-bootstrap sub-path
              - Prompt for codebase path
              - CodebaseReader → infer → interview → finalise
              - Save bootstrapped CONTEXT.md
              - Then classify and continue as normal
        
        Args:
            project_id: Project identifier (used to store/retrieve CONTEXT.md)
            change_request: Description of the change
        
        Returns:
            ModifyResult with response, updated context, and warnings
        """
        # Load existing CONTEXT.md
        context_md = self.context_store.load(project_id)
        if context_md is None:
            print(f"\n{'='*60}")
            print("No CONTEXT.md found. Starting cold bootstrap...")
            print(f"{'='*60}\n")
            
            context_md = self._bootstrap_from_codebase(project_id, change_request)
            if context_md is None:
                raise ValueError("Cold bootstrap failed — no CONTEXT.md produced")

        # Classify the change
        print(f"\n{'='*60}")
        print("CLASSIFYING CHANGE")
        print(f"{'='*60}")
        
        try:
            classification = classify_change(context_md, change_request)
        except Exception as e:
            # Classifier error: default to significant (safer)
            print(f"⚠️  Classifier error (defaulting to significant): {e}")
            classification_verdict = "significant"
            affected_sections = []
        else:
            classification_verdict = classification.verdict
            affected_sections = classification.affected_sections
            print(f"Verdict: {classification.verdict.upper()}")
            print(f"Reason: {classification.reason}")
            if affected_sections:
                print(f"Affected sections: {', '.join(affected_sections)}")

        # Route based on triviality
        updated_context_md = context_md
        merge_warnings: list[str] = []
        
        if classification_verdict == "trivial":
            print("\n→ Change is TRIVIAL. Skipping delta interview.")
        else:
            # Significant: run delta interview
            print("\n→ Change is SIGNIFICANT. Running scoped delta interview...")
            
            try:
                updated_context_md, merge_warnings = self._run_delta_interview_and_merge(
                    context_md,
                    change_request,
                    affected_sections,
                )
            except DeltaFinalizationError as e:
                print(f"\n⚠️  Delta interview parse error: {e}")
                print("Offer user manual edit fallback?")
                choice = input("Continue with gateway anyway? (yes/no): ").strip().lower()
                if choice != "yes":
                    raise
                # Proceed with unmodified context
                updated_context_md = context_md

        # Save updated CONTEXT.md
        self.context_store.save(project_id, updated_context_md)

        # Route to gateway (with updated context)
        print(f"\nProcessing change with LLMGateway...")
        response = self.gateway.handle(change_request, context_md=updated_context_md)

        # Warnings for user
        warnings_summary = []
        if merge_warnings:
            for warning in merge_warnings:
                print(f"⚠️  {warning}")
                warnings_summary.append(warning)

        return ModifyResult(
            response=response,
            updated_context_md=updated_context_md,
            project_id=project_id,
            was_trivial=(classification_verdict == "trivial"),
            sections_updated=affected_sections,
            merge_warnings=warnings_summary,
        )

    # (rest of methods unchanged from original)
    def _run_delta_interview_and_merge(
        self,
        context_md: str,
        change_request: str,
        affected_sections: list[str],
    ) -> tuple[str, list[str]]:
        """Run delta grilling interview and merge results into CONTEXT.md."""
        print(f"\n{'='*60}")
        print("DELTA INTERVIEW")
        print(f"{'='*60}\n")

        import sys
        
        msg = self.grilling_runner.start_delta_interview(
            context_md, change_request, affected_sections
        )
        print(f"Q{msg.ask_count}: {msg.question}\n")

        is_interactive = sys.stdin.isatty()

        if not is_interactive:
            print("[Running in non-interactive mode — finalizing delta interview]")
            result = self.grilling_runner.finalize_delta(affected_sections)
        else:
            # Interactive loop
            while msg.ask_count < 5:  # MAX_DELTA_QUESTIONS
                user_answer = input("Your answer: ").strip()
                if not user_answer:
                    print("(skipped)")
                    continue
                if user_answer.lower() in ["quit", "exit", "done"]:
                    print("\nForcing finalization...")
                    break
                msg = self.grilling_runner.continue_delta_interview(user_answer)
                print(f"\nQ{msg.ask_count}: {msg.question}\n")

            result = self.grilling_runner.finalize_delta(affected_sections)

        print(f"\n{'='*60}")
        print("DELTA INTERVIEW COMPLETE")
        print(f"{'='*60}")
        print(f"Total questions: {result.ask_count}\n")

        # Merge results into CONTEXT.md
        merge_result = merge_context(
            old_context_md=context_md,
            answers=result.answers,
            change_request=change_request,
            change_summary=result.change_summary,
        )

        warnings = []
        if merge_result.sections_not_found:
            for section in merge_result.sections_not_found:
                warnings.append(f"Nonexistent section: '{section}' (interview mentioned it, but CONTEXT.md doesn't have it)")

        print(f"Updated sections: {', '.join(merge_result.sections_updated)}")
        if warnings:
            for w in warnings:
                print(f"  ⚠️  {w}")

        return merge_result.merged_context, warnings

    def _generate_project_id(self, request: str) -> str:
        """Generate a project ID from the user's request."""
        stop_words = {"a", "an", "the"}
        words = [word for word in request.split() if word.lower() not in stop_words][:3]
        project_id = "-".join(words).lower()
        project_id = "".join(c for c in project_id if c.isalnum() or c == "-")
        return project_id or "project"

    def _run_grilling(self, project_description: str) -> str:
        """Run grilling interview."""
        import sys
        
        print(f"\n{'='*60}")
        print("GRILLING INTERVIEW")
        print(f"{'='*60}\n")

        msg = self.grilling_runner.start_interview(project_description)
        print(f"Q{msg.ask_count}: {msg.question}\n")

        is_interactive = sys.stdin.isatty()

        if not is_interactive:
            print("[Running in non-interactive mode — finalizing grilling]")
            result = self.grilling_runner.finalize()
        else:
            while not msg.is_finalizing:
                user_answer = input("Your answer: ").strip()
                if not user_answer:
                    print("(skipped)")
                    continue
                if user_answer.lower() in ["quit", "exit", "done"]:
                    print("\nForcing finalization...")
                    break
                msg = self.grilling_runner.continue_interview(user_answer)
                if msg.is_finalizing:
                    print(f"\n{msg.question}")
                    break
                else:
                    print(f"\nQ{msg.ask_count}: {msg.question}\n")

            result = self.grilling_runner.finalize()

        # Validate CONTEXT.md
        required_sections = [
            "Problem Statement",
            "Functional Requirements",
            "Assumptions",
            "Shared Vocabulary",
        ]
        context_md = result.context_md
        missing = [s for s in required_sections if s.lower() not in context_md.lower()]

        if missing:
            print(f"\n⚠️  CONTEXT.md is incomplete. Missing sections: {', '.join(missing)}")
            print("Continue grilling? (yes/no/edit)")
            choice = input("> ").strip().lower()

            if choice == "yes":
                print("\nContinuing interview...\n")
                return self._run_grilling(project_description)  # Recursive retry
            elif choice == "edit":
                print("\nEnter CONTEXT.md manually (type 'END' on a new line when done):")
                lines = []
                while True:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)
                context_md = "\n".join(lines)

        print(f"\n{'='*60}")
        print("GRILLING COMPLETE")
        print(f"{'='*60}")
        print(f"Total questions: {result.ask_count}\n")

        return context_md

    def _bootstrap_from_codebase(
        self,
        project_id: str,
        change_request: str,
    ) -> Optional[str]:
        """Cold bootstrap: read codebase, infer CONTEXT.md, interview user."""
        from pathlib import Path
        from src.bootstrap.codebase_reader import CodebaseReader
        from src.bootstrap.bootstrap_runner import BootstrapRunner
        from src.bootstrap.bootstrap_interviewer import BootstrapInterviewer
        
        # 1. Prompt for codebase path
        print("Enter the path to the codebase (e.g., /home/user/my-project):")
        codebase_path = input("> ").strip().strip('"').strip("'")
        
        if not codebase_path:
            print("Aborted.")
            return None
        
        path = Path(codebase_path)
        if not path.exists():
            print(f"❌ Path does not exist: {codebase_path}")
            return None
        
        if not path.is_dir():
            print(f"❌ Path is not a directory: {codebase_path}")
            return None
        
        # Set tool runtime for this project
        try:
            self.set_project_root(path)
        except ValueError as e:
            print(f"❌ Failed to set project root: {e}")
            return None
        
        # 2. CodebaseReader
        print(f"\nReading codebase from {codebase_path}...")
        try:
            reader = CodebaseReader()
            payload = reader.read(str(path))
            print(f"  ✓ Read {len(payload.file_contents)} files")
            print(f"  ✓ Detected stack: {', '.join(payload.detected_stack) or 'unknown'}")
            print(f"  ✓ Token budget: {payload.total_tokens_used} / 4000")
        except Exception as e:
            print(f"❌ CodebaseReader failed: {e}")
            return None
        
        # 3. BootstrapRunner.infer()
        print(f"\nInferring CONTEXT.md from codebase...")
        try:
            runner = BootstrapRunner()
            inference_result = runner.infer(payload, change_request, use_mock=False)
            draft_context_md = inference_result.draft_context_md
            unknown_entries = inference_result.unknown_entries
            print(f"  ✓ Draft produced with {len(unknown_entries)} [UNKNOWN] entries")
        except Exception as e:
            print(f"❌ Inference failed: {e}")
            return None
        
        # 4. BootstrapInterviewer.run()
        print(f"\n{'='*60}")
        print("BOOTSTRAP INTERVIEW")
        print(f"{'='*60}")
        try:
            interviewer = BootstrapInterviewer()
            interview_result = interviewer.run(draft_context_md)
            
            if interview_result.unresolved:
                print(f"\n⚠️  {len(interview_result.unresolved)} question(s) unresolved.")
                choice = input("Retry unanswered questions? (yes/no): ").strip().lower()
                if choice == "yes":
                    # Could implement a retry loop here, for now just continue
                    pass
        except Exception as e:
            print(f"❌ Interview failed: {e}")
            return None
        
        # 5. BootstrapRunner.finalise()
        print(f"\nFinalizing CONTEXT.md...")
        try:
            final_context_md = runner.finalise(draft_context_md, interview_result.answers)
            print(f"  ✓ CONTEXT.md finalized and validated")
        except ValueError as e:
            print(f"❌ Finalization failed: {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error during finalization: {e}")
            return None
        
        # 6. ContextStore.save()
        try:
            self.context_store.save(project_id, final_context_md)
            print(f"  ✓ Saved to contexts/{project_id}.md")
        except Exception as e:
            print(f"❌ Failed to save CONTEXT.md: {e}")
            return None
        
        # 7. Return
        print(f"\n{'='*60}")
        print("BOOTSTRAP COMPLETE")
        print(f"{'='*60}\n")
        
        return final_context_md

    def retrieve_context(self, project_id: str) -> Optional[str]:
        """Manually retrieve CONTEXT.md for a project."""
        return self.context_store.load(project_id)

    def list_projects(self) -> list[str]:
        """List all projects with stored CONTEXT.md."""
        return self.context_store.list_projects()