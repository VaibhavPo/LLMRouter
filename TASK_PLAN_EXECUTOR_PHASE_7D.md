# Personal Local AI Coding Assistant — Task Plan Phase 7 Executor

**Document Date:** August 23, 2026  
**Current Status:** Phase 7 (Tool Runtime) — Planner Complete, Executor In Design  
**Next Phase:** Phase 7d — Executor Implementation  

---

## Executive Summary

This document captures:
1. **Complete work history** — Phases 0–7c: what's built, tested, proven
2. **Architecture snapshot** — How components fit together today
3. **Step 3: Executor Design** — How execution of TaskPlans will work
4. **Integration roadmap** — How Executor connects to everything

**For new contributors:** This is the "resume" of the project. Read this to understand the full context before starting Phase 7d.

---

# PART 1: COMPLETE WORK HISTORY

## Project Vision

Build a **personal AI coding assistant** that:
- Runs locally on my machine (no cloud APIs)
- Uses LM Studio + multiple local LLMs instead of expensive cloud models
- Includes: Model Router + Orchestrator + Tool Runtime + Context Manager + Verification Loop + Skill Layer
- Integrates with VS Code (Phase 11)

**No fine-tuning planned initially** — rely on prompting, routing, context management, tool orchestration, and skill discipline.

---

## Proven Models (Phase 1 Benchmark Evidence)

All models tested against real task batteries. No assumptions.

| Model | Role | Proven | Benchmark |
|-------|------|--------|-----------|
| `nemotron-3-nano-4b` (4B) | Fast coder | ✅ 6/6 tests, ~5s | Primary executor for simple tasks |
| `essentialai/rnj-1` (gemma3 8.3B) | Coder, large context | ✅ 6/6 tests, ~7s | Executor for complex/multi-file tasks |
| `qwen3-4b-thinking` (4B) | Reasoning, planning, debugging | ✅ 3/3 diagnoses, 10–49s | Planner, Debugger (reasoning tier) |
| `gemma-4-e2b` (4.6B) | Secondary coder, vision candidate | ✅ Proven coder (6/6, ~11s); vision untested | Future: reviewer or vision model |
| `qwen3-vl-4b` (4B) | Vision (candidate) | 🔲 Not yet benchmarked | Vision branch blocked until tested |
| `qwen3-1.7b` (1.7B) | Classifier | ⚠️ Proven with caveats | Classification only; unreliable on `requires_vision` |

**Excluded models:**
- ❌ `deepseek-r1-8b` — 130–230s+, runaway generation
- ❌ `qwen3.5-9b` — No usable quant at budget; real tests: syntax errors, 94–120s+

---

## Architecture: Complete System

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INPUT (CLI)                         │
│  (new / work / modify / list / delete / plan / execute)         │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (Phase 4–5)                     │
│  ├─ run()            → Manage new projects + grilling           │
│  ├─ modify()         → Edit existing projects + delta interview │
│  ├─ plan_task()      → Generate TaskPlan (Phase 7b)            │
│  ├─ execute_tool()   → Dispatch tool calls (Phase 7)           │
│  └─ get_tool_descriptions() → List available tools             │
└──────────────┬──────────────────────┬──────────────────────────┘
               ↓                      ↓
        ┌─────────────────┐   ┌──────────────────┐
        │ GRILLING        │   │ CONTEXT STORE    │
        │ (Phase 3)       │   │ (Phase 4)        │
        │                 │   │ CONTEXT.md       │
        │ GrillingRunner  │   │ persistence      │
        │ - interview()   │   │                  │
        │ - delta_grill() │   │ Per-project      │
        │ - finalize()    │   │ shared vocab     │
        └─────────────────┘   └──────────────────┘
               ↓
    ┌──────────────────────────┐
    │  LLM GATEWAY (Phase 2)   │
    │ ├─ Classification        │
    │ │  (qwen3-1.7b)         │
    │ │  task_type + skill     │
    │ │                        │
    │ ├─ Route by Model        │
    │ │  router.py: which      │
    │ │  model gets this task  │
    │ │                        │
    │ └─ Route by Skill        │
    │    (Phase 6)             │
    │    TDD / Diagnosis /     │
    │    Planning / etc.       │
    └──────────────────────────┘
             ↓
  ┌─────────────────────────────┐
  │   PLANNER (Phase 7b/7c)     │
  │   ✨ Loosely Coupled Design  │
  │                             │
  │  PlannerBuilder             │
  │  ├─ build_default()         │
  │  ├─ build_diagnosis()       │
  │  ├─ build_tdd()             │
  │  ├─ build_mock() [testing]  │
  │  └─ build_custom()          │
  │                             │
  │  Planner (orchestrator)     │
  │  ├─ LLMProvider             │
  │  │  (LMStudio, Mock, ...)   │
  │  ├─ PromptBuilder           │
  │  │  (Default, Diagnosis, ..)│
  │  ├─ ResponseParser          │
  │  │  (JSON, YAML, ...)       │
  │  ├─ PlanValidator           │
  │  └─ Logger                  │
  │                             │
  │  Outputs: TaskPlan          │
  │  ├─ task_summary            │
  │  ├─ steps[] with deps       │
  │  ├─ relevant_files          │
  │  └─ skill_name              │
  └─────────────────────────────┘
             ↓
  ┌──────────────────────────────┐
  │  EXECUTOR (Phase 7d) ← YOU   │
  │  ARE HERE (In Design)        │
  │                              │
  │  Reads: TaskPlan             │
  │  Executes: step-by-step      │
  │  Uses: Tool Runtime          │
  │  Returns: ExecutionResult    │
  └──────────────────────────────┘
             ↓
  ┌──────────────────────────────┐
  │   TOOL RUNTIME (Phase 7a–7c) │
  │   ✨ Complete & Tested       │
  │                              │
  │  ToolRegistry                │
  │  ├─ read_file                │
  │  │  (with line ranges!)      │
  │  ├─ list_files               │
  │  │  (recursive, sizes)       │
  │  ├─ search_code              │
  │  │  (regex + plain text)     │
  │  ├─ [write_file] (Phase 7b)  │
  │  ├─ [edit_file] (Phase 7b)   │
  │  ├─ [run_tests] (Phase 7d)   │
  │  ├─ [run_terminal] (Phase 7b)│
  │  └─ [git_*] (Phase 7c)       │
  │                              │
  │  SafetyTier:                 │
  │  ├─ READONLY ✓               │
  │  ├─ WRITE_LOCAL (Phase 7b)   │
  │  ├─ SHELL (Phase 7b)         │
  │  ├─ EXTERNAL_AI (Phase 7c)   │
  │  └─ EXTERNAL_NETWORK (Phase 7c) │
  └──────────────────────────────┘
             ↓
   ┌────────────────────┐
   │  USER OUTPUT       │
   │  (code, plan, etc) │
   └────────────────────┘
```

---

## Phase-by-Phase Completion Status

### ✅ Phase 0: Understand Architecture
- Learned: models, routers, agents, orchestrators, tools, context, memory
- Status: Complete

### ✅ Phase 1: Connect Python to LM Studio
- Built: `lmstudio.py` client wrapper
- Benchmarked: All models against real tasks
- Status: Complete (vision benchmark still pending, but not blocking)

### ✅ Phase 2: Basic Router
- Built: `gateway.py` with model routing by task_type
- Models: nemotron (fast), rnj-1 (complex), qwen3-4b (reasoning)
- Status: Complete, proven

### ✅ Phase 3: Intelligent Classifier
- Built: `_CLASSIFIER_SYSTEM_PROMPT` in gateway.py
- Outputs: task_type + skill_name
- Status: Complete with caveats (qwen3-1.7b unreliable on requires_vision)

### ✅ Phase 4: Model Registry
- Built: `model_registry.py` with role-to-model mapping
- Status: Complete, used by router

### ✅ Phase 4.5: Modify Workflow (Triviality Judge)
- Built: `triviality_judge.py` — classify changes as TRIVIAL or SIGNIFICANT
- Status: Complete, working end-to-end

### ✅ Phase 4.6: Cold Bootstrap
- Built: `CodebaseReader` → `BootstrapRunner` → `BootstrapInterviewer`
- Reads codebase, infers CONTEXT.md, interviews user, finalizes
- Status: Complete, 12/12 tests passing

### ✅ Phase 5: Planner (Partial, now complete with Executor design)
- **Grilling skill:** Proven (google/gemma-4-e2b, 7-question interview, complete CONTEXT.md)
- **Delta re-grill:** For significant changes (Phase 4.5)
- **Orchestrator.modify():** Integrates both paths (existing context or cold bootstrap)
- Status: Grilling proven; planning moved to Phase 7 (redesigned as loosely-coupled)

### ✅ Phase 6: Classifier Skill Routing
- Built: Extended classifier to output `skill_name` (TDD, Diagnosis, Planning, etc.)
- Built: `skill_factory.py` with TDD + Diagnosis evaluation
- Status: Complete, 4/4 canonical TDD tests passing

### 🟡 Phase 7: Tool Runtime (Partial — 7a–7c complete, 7d in design)

#### ✅ Phase 7a: Tool Schemas + Registry
- Built: `ToolRequest`, `ToolResult`, `Tool` base class
- Built: `ToolRegistry` with validation + dispatch
- Status: Complete, tested

#### ✅ Phase 7b: Readonly Tools
- Built: `read_file` (with line ranges!), `list_files` (recursive, sizes), `search_code` (regex + plain)
- Tests: 15+ passing
- Status: Complete, proven

#### ✅ Phase 7c: Planner (Loosely Coupled)
- **Design:** Planner is orchestrator that depends on interfaces, not implementations
- **Components:**
  - `interfaces.py` — LLMProvider, PromptBuilder, ResponseParser, PlanValidator, Logger, PlanFactory
  - `providers.py` — LMStudioProvider, MockProvider (easily add more)
  - `parsers.py` — JSONParser (easily add YAML, etc.)
  - `validators.py` — TaskPlanValidator
  - `prompts.py` — DefaultPromptBuilder, DiagnosisPromptBuilder, TDDPromptBuilder
  - `planner.py` — Main orchestrator (pure orchestration, no implementation)
  - `config.py` — PlannerBuilder (wiring), ConsoleLogger, TaskPlanFactory
- **TaskPlan schema:** Defined in `src/core/task_plan.py`
  - ActionType (read_file, search_code, think, write_file, edit_file, run_tests, skill_workflow, etc.)
  - TaskStep with dependencies, estimated time, status tracking
  - Built-in validation and topological ordering
- **Why loosely coupled:**
  - Swap LLM provider without touching Planner
  - Add new prompt types without modifying Planner
  - Change parser (JSON→YAML) without Planner changes
  - Easy testing with MockProvider
  - Follows SOLID + DRY + KISS + Composition over Inheritance + LoK
- **Tests:** 11+ passing (schemas, validation, dependency resolution)
- Status: Complete, production-ready

#### 🟢 Phase 7d: Executor (Next — This Document)
- **What it does:** Reads TaskPlan, executes steps in dependency order, uses Tool Runtime
- **Design:** Will follow same loosely-coupled principles as Planner
- **Status:** In design phase (this document)

#### ⏳ Phase 7e: Safety & Audit Logging
- Planned: Model-level permissions, SQLite audit log, graceful error handling
- Status: Not started (post-7d)

#### ⏳ Phase 7f: Integration & Benchmarking
- Planned: Wire executor into gateway/orchestrator, test skill-following
- Status: Not started (post-7e)

### ⏳ Phase 8: Verification Loop + TDD Skill
- Planned: Integrate TDD skill from Phase 6 into verification loop
- Will use run_tests tool to actually execute tests
- Status: Ready to build (needs executor)

### ⏳ Phase 9: Context Manager + Domain Modeling
- Planned: Living CONTEXT.md with repo tree + embeddings
- Status: Phase 4 done (simple file store); Phase 9 is enhancement

### ⏳ Phase 10: Memory + Handoff
- Planned: Session compaction for resuming across invocations
- Status: Not started

### ⏳ Phase 11: VS Code Integration
- Planned: Continue/Cline plugin or custom extension
- Status: Not started (depends on phases 7–10)

### ⏳ Phase 12: Benchmarking
- Planned: Skill-following benchmarks (not just model accuracy)
- Status: Not started (post-phase 7–10)

### ⏳ Phase 13: Intelligent Routing
- Planned: Route by skill + model + context budget
- Status: Not started

### ⏳ Phase 14: Skill Layer Rollout
- Planned: Adopt tdd → diagnosing-bugs → grilling → others
- Each skill gated by local model benchmark
- Status: TDD integration ready (Phase 8)

---

# PART 2: ARCHITECTURE SNAPSHOT (TODAY)

## Technology Stack

```
src/
├── bootstrap/              # Cold bootstrap (Phase 4.6)
│   ├── codebase_reader.py  # Read files + infer stack
│   ├── bootstrap_runner.py # Infer CONTEXT.md draft
│   └── bootstrap_interviewer.py # Parse [UNKNOWN], ask Q's
│
├── core/                   # Core orchestration
│   ├── gateway.py          # Model routing + classification (Phase 2–3)
│   ├── task_plan.py        # TaskPlan schema + validation
│   ├── tool_runtime.py     # Tool registry + dispatch (Phase 7a)
│   │
│   ├── planner_v2/         # Loosely-coupled planner (Phase 7c)
│   │   ├── __init__.py
│   │   ├── interfaces.py   # Abstractions (LLMProvider, etc.)
│   │   ├── providers.py    # Implementations (LMStudio, Mock, ...)
│   │   ├── parsers.py      # Response parsing (JSON, YAML, ...)
│   │   ├── validators.py   # Plan validation
│   │   ├── prompts.py      # Prompt builders (Default, Diagnosis, TDD)
│   │   ├── planner.py      # Main orchestrator
│   │   └── config.py       # PlannerBuilder + wiring
│   │
│   └── executor/           # ← NEXT: Your execution layer (Phase 7d)
│       ├── __init__.py
│       ├── interfaces.py   # Abstractions
│       ├── executor.py     # Main orchestrator
│       ├── step_runner.py  # Run individual steps
│       ├── context_manager.py # Manage step outputs
│       └── config.py       # ExecutorBuilder + wiring
│
├── orchestrator/           # Main orchestrator (Phase 4–5)
│   ├── orchestrator.py     # Entry point
│   ├── triviality_judge.py # TRIVIAL vs SIGNIFICANT (Phase 4.5)
│   ├── modify.py           # Context merge logic
│   └── grilling.py         # Grilling interview management
│
├── skills/                 # Skill implementations (Phase 6)
│   ├── skill_factory.py    # Route by skill, evaluate
│   ├── skill_loader.py     # Load .md procedures, phase gate
│   └── procedures/
│       ├── tdd.md          # TDD: RED-GREEN-REFACTOR
│       ├── diagnosis.md    # Diagnosis: MINIMIZE-HYPOTHESIZE-INSTRUMENT-FIX-VERIFY
│       └── ...
│
├── context/                # Context storage (Phase 4)
│   └── context_store.py    # File-based CONTEXT.md persistence
│
├── tools/                  # Tool implementations (Phase 7)
│   ├── __init__.py
│   ├── schemas.py          # Tool base classes + result types
│   ├── file_tools.py       # read_file, list_files (Phase 7b)
│   ├── search_tools.py     # search_code (Phase 7b)
│   ├── write_tools.py      # write_file, edit_file (Phase 7b — future)
│   ├── shell_tools.py      # run_tests, run_terminal (Phase 7d — future)
│   └── git_tools.py        # git_diff, etc. (Phase 7c — future)
│
├── safety/                 # Safety & permissions (Phase 7e — future)
│   ├── sandbox.py          # Subprocess isolation
│   ├── restrictions.py     # Command whitelist/blacklist
│   └── permissions.py      # Model → tool access control
│
├── bootstrap.py            # Entry point
├── cli/
│   └── main.py             # CLI: new/work/modify/plan/execute/list/delete
│
├── lmstudio.py             # LM Studio API wrapper (Phase 1)
└── model_registry.py       # Role → model mapping (Phase 4)

tests/
├── test_task_plan.py       # TaskPlan schema + validation (11+ tests)
├── test_tool_runtime.py    # Tool registry + tools (28+ tests)
├── test_planner_v2.py      # Planner with mock provider (7+ tests)
└── ...

CONTEXT/                    # Context storage (project-specific)
└── {project_id}.md         # CONTEXT.md per project
```

---

## Data Flow Example: "Add email validation to UserSchema"

```
User Command
├─ Input: "modify myproject Add email validation to UserSchema"
│
├─ Orchestrator.modify(project_id="myproject", change_request="...")
│  ├─ Load CONTEXT.md from contexts/myproject.md
│  ├─ Classify change: TrivialityJudge → "SIGNIFICANT"
│  ├─ Run delta interview (scoped re-grill)
│  ├─ Merge answers into CONTEXT.md
│  └─ Pass to LLMGateway
│
├─ LLMGateway.handle(change_request, context_md=..., ...)
│  ├─ Classify: qwen3-1.7b → task_type="simple_code", skill_name="TDD"
│  ├─ Route to skill: TDD
│  └─ Dispatch: run_skill(TDD, request, context_md)
│
├─ SkillFactory.run_skill(TDD, ...)
│  ├─ Load tdd.md procedure
│  ├─ Run model: nemotron-3-nano-4b (fast coder)
│  ├─ Get output: RED/GREEN/REFACTOR code
│  └─ Evaluate: phase gating, signature checks, stub detection
│
└─ Output to User
   └─ Complete RED/GREEN/REFACTOR response with feedback

DESIRED FLOW (with Executor, Phase 7d):
───────────────────────────────────────

User Command
├─ Input: "modify myproject Add email validation to UserSchema"
│
├─ Orchestrator.plan_task(project_id, change_request)
│  ├─ Load CONTEXT.md
│  ├─ Call Planner.plan()
│  └─ Get TaskPlan with steps:
│     0. read_file(src/models/user.py)
│     1. search_code(pattern="validate.*email")
│     2. think (design validation approach)
│     3. skill_workflow(TDD) [depends on 2]
│     4. run_tests [depends on 3]
│
├─ Orchestrator.execute(TaskPlan)
│  │  ← This is Phase 7d: EXECUTOR
│  ├─ Executor.execute(plan)
│  │  ├─ Get next ready step (dependencies satisfied)
│  │  │  └─ Step 0 is ready (no deps)
│  │  ├─ Execute step 0: read_file(src/models/user.py)
│  │  │  ├─ Tool.execute() → file content
│  │  │  ├─ Step.status = COMPLETED
│  │  │  ├─ Step.actual_output = file content
│  │  │  └─ Mark step 0 as done
│  │  │
│  │  ├─ Get next ready step
│  │  │  └─ Step 1 is ready (step 0 done)
│  │  ├─ Execute step 1: search_code(pattern="validate.*email")
│  │  │  ├─ Tool.execute() → matching lines
│  │  │  ├─ Step.status = COMPLETED
│  │  │  └─ Mark step 1 as done
│  │  │
│  │  ├─ Get next ready step
│  │  │  └─ Step 2 is ready (steps 0, 1 done)
│  │  ├─ Execute step 2: think
│  │  │  ├─ No tool; just call model to reason
│  │  │  ├─ Step.actual_output = reasoning
│  │  │  └─ Mark step 2 as done
│  │  │
│  │  ├─ Get next ready step
│  │  │  └─ Step 3 is ready (step 2 done, depends_on=[2])
│  │  ├─ Execute step 3: skill_workflow(TDD)
│  │  │  ├─ Call TDD skill with gathered context
│  │  │  ├─ Step.actual_output = RED/GREEN/REFACTOR
│  │  │  └─ Mark step 3 as done
│  │  │
│  │  ├─ Get next ready step
│  │  │  └─ Step 4 is ready (step 3 done)
│  │  ├─ Execute step 4: run_tests
│  │  │  ├─ Tool.execute(run_tests) → test results
│  │  │  ├─ Step.status = COMPLETED (or FAILED if tests fail)
│  │  │  └─ Mark step 4 as done
│  │  │
│  │  └─ All steps done; return ExecutionResult
│  │
│  └─ Execution complete
│
└─ Output to User
   ├─ Plan summary
   ├─ Step-by-step results
   ├─ Final code + test results
   └─ Explanation of what happened
```

---

# PART 3: STEP 3 — EXECUTOR DESIGN (PHASE 7D)

## 3.1: Executor Responsibilities

The **Executor** reads a TaskPlan and runs it step-by-step. It must:

1. **Respect dependencies** — Execute steps in order respecting depends_on
2. **Call tools** — For each step with a tool_invocation, call Tool Runtime
3. **Call models** — For steps that need thinking (THINK, DESIGN, SKILL_WORKFLOW)
4. **Manage context** — Keep outputs from earlier steps available for later steps
5. **Track state** — Update step.status, step.actual_output, step.error
6. **Handle failures** — Decide: retry? skip? abort?
7. **Log everything** — Audit trail for debugging
8. **Return results** — ExecutionResult with step-by-step outputs

---

## 3.2: Design Principles (Same as Planner)

The Executor will be **loosely coupled** following SOLID + DRY + KISS + Composition:

```
Executor depends on:
├─ interfaces.py (abstractions)
│  ├─ StepExecutor (execute one step)
│  ├─ ContextManager (store/retrieve step outputs)
│  ├─ ModelCaller (call LLM for THINK/DESIGN steps)
│  ├─ ToolCaller (dispatch to Tool Runtime)
│  └─ Logger
│
├─ step_executor.py (implementations)
│  ├─ ToolStepExecutor (for TOOL-based actions)
│  ├─ ThinkStepExecutor (for THINK/DESIGN)
│  ├─ SkillStepExecutor (for SKILL_WORKFLOW)
│  └─ VerifyStepExecutor (for RUN_TESTS/VERIFY)
│
├─ context_manager.py
│  └─ PlanExecutionContext (thread-safe dict of step outputs)
│
└─ executor.py (main orchestrator)
   └─ Executor (orchestrates, doesn't implement)
```

---

## 3.3: Executor Architecture

```python
# src/core/executor/executor.py

class Executor:
    """
    Executes a TaskPlan step-by-step, respecting dependencies.
    Loosely coupled: depends on interfaces, not implementations.
    """
    
    def __init__(
        self,
        step_executor_factory: StepExecutorFactory,
        context_manager: ContextManager,
        logger: Logger,
        max_retries: int = 2,
        timeout_per_step: int = 300,
    ):
        """Initialize with dependencies."""
        self.step_executor_factory = step_executor_factory
        self.context = context_manager
        self.logger = logger
        self.max_retries = max_retries
        self.timeout_per_step = timeout_per_step
    
    def execute(self, plan: TaskPlan) -> ExecutionResult:
        """
        Execute a TaskPlan.
        
        Args:
            plan: TaskPlan to execute
        
        Returns:
            ExecutionResult with outcomes of all steps
        
        Raises:
            ExecutionError: If execution fails critically
        """
        # Get execution order (respects dependencies)
        try:
            order = plan.topological_order()
        except ValueError as e:
            raise ExecutionError(f"Plan has circular dependencies: {e}")
        
        completed_steps = set()
        failed_steps = set()
        
        # Execute each step in order
        for step_id in order:
            step = plan.steps[step_id]
            
            # Check if dependencies are satisfied
            if not step.is_ready(completed_steps):
                step.status = StepStatus.SKIPPED
                self.logger.info(f"Step {step_id}: Skipped (dependency not ready)")
                continue
            
            # Execute the step
            try:
                self._execute_step(step, plan)
                completed_steps.add(step_id)
                
            except StepExecutionError as e:
                failed_steps.add(step_id)
                step.status = StepStatus.FAILED
                step.error = str(e)
                
                self.logger.error(f"Step {step_id}: Failed — {e}")
                
                # Decide: retry? skip? abort?
                if self._should_retry(step, failed_steps):
                    self.logger.info(f"Retrying step {step_id}...")
                    # Retry logic here
                elif self._can_skip(step):
                    self.logger.info(f"Skipping step {step_id} (can_fail=True)")
                else:
                    self.logger.error(f"Aborting: step {step_id} failed and cannot skip")
                    raise ExecutionError(f"Step {step_id} failed: {e}")
        
        # Return results
        return ExecutionResult(
            plan=plan,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            context=self.context.snapshot(),
        )
    
    def _execute_step(self, step: TaskStep, plan: TaskPlan):
        """Execute a single step."""
        self.logger.info(f"\nExecuting step {step.step_id}: {step.description}")
        step.status = StepStatus.IN_PROGRESS
        
        try:
            # Get the right executor for this action type
            executor = self.step_executor_factory.create(step.action_type)
            
            # Execute with timeout
            result = self._run_with_timeout(
                executor.execute,
                step=step,
                plan=plan,
                context=self.context,
            )
            
            step.actual_output = result
            step.status = StepStatus.COMPLETED
            
            # Store in context for later steps
            self.context.set_step_output(step.step_id, result)
            
            self.logger.info(f"✅ Step {step.step_id}: Completed")
            self.logger.debug(f"Output: {result[:200]}...")
            
        except Exception as e:
            raise StepExecutionError(f"Step {step.step_id} execution failed: {e}")
    
    def _run_with_timeout(self, func, **kwargs):
        """Run function with timeout."""
        # Implementation: use signal or threading timeout
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Step exceeded {self.timeout_per_step}s")
        
        # Set timeout (Unix only)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.timeout_per_step)
        
        try:
            result = func(**kwargs)
            signal.alarm(0)  # Cancel alarm
            return result
        except TimeoutError as e:
            signal.alarm(0)
            raise
    
    def _should_retry(self, step: TaskStep, failed_steps: set) -> bool:
        """Decide if we should retry this step."""
        # Retry conditions: transient failures (network, timeout)
        # Don't retry: programming errors
        return False  # Implement based on error type
    
    def _can_skip(self, step: TaskStep) -> bool:
        """Decide if we can skip this step."""
        return step.can_fail
```

---

## 3.4: Step Executors (Implementations)

```python
# src/core/executor/step_executor.py

class StepExecutor(ABC):
    """Interface for executing a step."""
    
    @abstractmethod
    def execute(self, step: TaskStep, plan: TaskPlan, context: ContextManager) -> str:
        """Execute a step. Return output."""
        pass


class ToolStepExecutor(StepExecutor):
    """Execute a step that calls a tool."""
    
    def __init__(self, tool_runtime: ToolRegistry):
        self.tool_runtime = tool_runtime
    
    def execute(self, step: TaskStep, plan: TaskPlan, context: ContextManager) -> str:
        """Call tool and return result."""
        if not step.tool_invocation:
            raise ValueError(f"Step {step.step_id} has no tool invocation")
        
        result = self.tool_runtime.execute(
            ToolRequest(
                tool_name=step.tool_invocation.tool_name,
                arguments=step.tool_invocation.arguments,
            )
        )
        
        if not result.success:
            raise StepExecutionError(f"Tool failed: {result.error}")
        
        return result.output


class ThinkStepExecutor(StepExecutor):
    """Execute a thinking step (no tool, just reasoning)."""
    
    def __init__(self, model_provider: LLMProvider):
        self.model = model_provider
    
    def execute(self, step: TaskStep, plan: TaskPlan, context: ContextManager) -> str:
        """Call model to reason through the step."""
        # Build prompt from step description + previous outputs
        prompt = self._build_thinking_prompt(step, context)
        
        response = self.model.call(
            system_prompt="You are a careful reasoner. Think through the problem step-by-step.",
            user_prompt=prompt,
            temperature=0.1,  # Precise thinking
            max_tokens=1024,
        )
        
        return response
    
    def _build_thinking_prompt(self, step: TaskStep, context: ContextManager) -> str:
        """Build a prompt that includes previous step outputs."""
        # Example:
        # "We just read UserSchema (see below). We searched for validation patterns.
        #  Now, based on these findings, design the validation approach."
        
        previous_outputs = []
        for dep_id in step.depends_on:
            output = context.get_step_output(dep_id)
            previous_outputs.append(f"Step {dep_id} output:\n{output}\n")
        
        return f"""Task: {step.description}

Previous findings:
{chr(10).join(previous_outputs)}

Think through this carefully and provide your reasoning."""


class SkillStepExecutor(StepExecutor):
    """Execute a skill workflow (TDD, Diagnosis, etc.)."""
    
    def __init__(self, skill_factory):
        self.skill_factory = skill_factory
    
    def execute(self, step: TaskStep, plan: TaskPlan, context: ContextManager) -> str:
        """Run a skill."""
        # Get skill name from plan or step
        skill_name = plan.skill_name or "unknown"
        
        # Gather context from previous steps
        previous_outputs = {dep_id: context.get_step_output(dep_id) 
                           for dep_id in step.depends_on}
        
        # Call skill
        result = self.skill_factory.run_skill(
            skill_name=skill_name,
            request=step.description,
            context_md=previous_outputs,  # Pass gathered context
        )
        
        if not result.passed:
            raise StepExecutionError(f"Skill validation failed: {result.feedback}")
        
        return result.output


class VerifyStepExecutor(StepExecutor):
    """Execute verification (RUN_TESTS, VERIFY, etc.)."""
    
    def __init__(self, tool_runtime: ToolRegistry):
        self.tool_runtime = tool_runtime
    
    def execute(self, step: TaskStep, plan: TaskPlan, context: ContextManager) -> str:
        """Run tests or verification."""
        result = self.tool_runtime.execute(
            ToolRequest(
                tool_name=step.tool_invocation.tool_name,
                arguments=step.tool_invocation.arguments,
            )
        )
        
        if not result.success:
            raise StepExecutionError(f"Tests failed: {result.output}")
        
        return result.output
```

---

## 3.5: Context Manager

```python
# src/core/executor/context_manager.py

class ContextManager:
    """
    Manages step outputs during execution.
    Thread-safe. Accessible to all executors.
    """
    
    def __init__(self, project_context: str = ""):
        self.project_context = project_context  # CONTEXT.md
        self._step_outputs = {}  # step_id → output
        self._lock = threading.Lock()
    
    def set_step_output(self, step_id: int, output: str):
        """Store step output for later steps."""
        with self._lock:
            self._step_outputs[step_id] = output
    
    def get_step_output(self, step_id: int) -> str:
        """Retrieve step output."""
        with self._lock:
            return self._step_outputs.get(step_id, "")
    
    def get_outputs_for_steps(self, step_ids: list[int]) -> dict:
        """Get outputs for multiple steps."""
        with self._lock:
            return {step_id: self._step_outputs.get(step_id, "") 
                   for step_id in step_ids}
    
    def snapshot(self) -> dict:
        """Get a snapshot of all outputs (for debugging)."""
        with self._lock:
            return dict(self._step_outputs)
```

---

## 3.6: Results

```python
# src/core/executor/results.py

@dataclass
class ExecutionResult:
    """Result of executing a TaskPlan."""
    
    plan: TaskPlan
    completed_steps: set[int]
    failed_steps: set[int]
    context: dict  # step outputs
    
    def summary(self) -> str:
        """Human-readable summary."""
        total = len(self.plan.steps)
        passed = len(self.completed_steps)
        failed = len(self.failed_steps)
        
        return f"""
Execution Summary
─────────────────
Task: {self.plan.task_summary}
Steps: {passed}/{total} completed, {failed} failed

Step outcomes:
"""
        for step in self.plan.steps:
            status_emoji = {
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⊘",
                StepStatus.PENDING: "⏳",
            }.get(step.status, "?")
            
            return f"  {status_emoji} Step {step.step_id}: {step.description}"
```

---

## 3.7: Configuration & Builder

```python
# src/core/executor/config.py

class ExecutorBuilder:
    """Builder for creating configured Executor instances."""
    
    def __init__(self, tool_runtime: ToolRegistry):
        self.tool_runtime = tool_runtime
        self.logger = ConsoleLogger()
    
    def build(self, model_provider: LLMProvider, skill_factory) -> Executor:
        """Build a standard Executor."""
        step_executor_factory = StepExecutorFactory(
            tool_runtime=self.tool_runtime,
            model_provider=model_provider,
            skill_factory=skill_factory,
        )
        
        return Executor(
            step_executor_factory=step_executor_factory,
            context_manager=ContextManager(),
            logger=self.logger,
            max_retries=2,
            timeout_per_step=300,
        )
    
    def build_with_timeout(self, model_provider, skill_factory, timeout: int) -> Executor:
        """Build with custom timeout."""
        executor = self.build(model_provider, skill_factory)
        executor.timeout_per_step = timeout
        return executor


class StepExecutorFactory:
    """Factory for creating step executors by action type."""
    
    def __init__(self, tool_runtime, model_provider, skill_factory):
        self.tool_runtime = tool_runtime
        self.model_provider = model_provider
        self.skill_factory = skill_factory
    
    def create(self, action_type: ActionType) -> StepExecutor:
        """Create the right executor for an action."""
        if action_type in {ActionType.READ_FILE, ActionType.SEARCH_CODE, 
                          ActionType.LIST_FILES, ActionType.WRITE_FILE,
                          ActionType.EDIT_FILE, ActionType.RUN_TESTS}:
            return ToolStepExecutor(self.tool_runtime)
        
        elif action_type in {ActionType.THINK, ActionType.DESIGN, 
                            ActionType.REVIEW_FINDINGS}:
            return ThinkStepExecutor(self.model_provider)
        
        elif action_type == ActionType.SKILL_WORKFLOW:
            return SkillStepExecutor(self.skill_factory)
        
        elif action_type in {ActionType.VERIFY, ActionType.RUN_LINTER}:
            return VerifyStepExecutor(self.tool_runtime)
        
        else:
            raise ValueError(f"Unknown action type: {action_type}")
```

---

## 3.8: Integration into Orchestrator

```python
# src/orchestrator/orchestrator.py (ADD)

from src.core.executor.config import ExecutorBuilder

class Orchestrator:
    def __init__(self, ...):
        # ... existing init ...
        
        # Initialize executor (Phase 7d)
        executor_builder = ExecutorBuilder(self.tool_runtime)
        # Create executor when needed, or once here with a default model
        self.executor_builder = executor_builder
    
    def execute_plan(self, plan: TaskPlan) -> ExecutionResult:
        """Execute a TaskPlan."""
        # Get appropriate model for execution
        executor = self.executor_builder.build(
            model_provider=LMStudioProvider("qwen/qwen3-4b-thinking-2507"),
            skill_factory=self.skill_factory,
        )
        
        return executor.execute(plan)
```

---

## 3.9: Full Workflow (with Planner + Executor)

```
User: "modify myproject Add email validation to UserSchema"

1. Orchestrator.modify(project_id, change_request)
   ├─ Load CONTEXT.md
   ├─ Classify: SIGNIFICANT
   ├─ Run delta interview
   └─ Merge CONTEXT.md

2. LLMGateway.handle(change_request, context_md)
   ├─ Classify: skill_name="TDD"
   └─ For TDD: planner is involved? Depends on gateway routing
   
3. ⚠️ Question: Gateway → Planner → Executor, or Gateway → Skill?
   
   Current design: Gateway routes by skill, which calls skill_factory.
   New design should be: Gateway recognizes complex tasks, routes to Planner.
   Planner → generates TaskPlan.
   Executor → runs TaskPlan.
   
   Decision: Add PLANNING_GATE to gateway:
   ─────────────────────────────────────
   IF task is complex (multi-step, needs research):
      → route to Planner.plan()
      → get TaskPlan
      → route to Executor.execute()
   ELSE:
      → route to skill directly (as before)

4. Planner.plan(change_request, context_md, tool_descriptions)
   ├─ Call qwen3-4b-thinking with prompt
   ├─ Get TaskPlan: 5 steps
   │  ├─ Step 0: read_file(src/models/user.py)
   │  ├─ Step 1: search_code(pattern="validate.*email")
   │  ├─ Step 2: think (design approach)
   │  ├─ Step 3: skill_workflow(TDD) [depends on 2]
   │  └─ Step 4: run_tests [depends on 3]
   └─ Return PlannerResponse

5. Executor.execute(plan)
   ├─ Topological sort: 0 → 1 → 2 → 3 → 4
   ├─ Execute step 0: read_file → UserSchema content
   ├─ Execute step 1: search_code → validation patterns found
   ├─ Execute step 2: think → reasoning + strategy
   ├─ Execute step 3: skill_workflow(TDD) → RED/GREEN/REFACTOR
   ├─ Execute step 4: run_tests → ✅ All tests pass
   └─ Return ExecutionResult

6. Output to user
   ├─ Plan summary
   ├─ Step-by-step outcomes
   ├─ Final code + test results
   └─ Explanation
```

---

## 3.10: Error Handling Strategy

| Error | Retry? | Skip? | Abort? |
|-------|--------|-------|--------|
| Tool call fails (file not found) | No | Only if step.can_fail | Yes |
| Model call timeout | Yes (1–2x) | No | Yes after retries |
| Dependency not ready | N/A | Yes | No (wait) |
| Parsing error | No | No | Yes |
| Test failure | No | No | Yes (unless can_fail) |

---

# PART 4: IMPLEMENTATION ROADMAP (PHASE 7D)

## Step-by-Step Build

### Step 1: Define Interfaces (1 hour)
```
src/core/executor/
├── __init__.py
├── interfaces.py        ← StepExecutor, ContextManager, etc.
└── results.py           ← ExecutionResult dataclass
```

**Task:** Write abstract base classes following ISP
**Tests:** None yet (interfaces don't execute)

---

### Step 2: Implement Step Executors (2 hours)
```
src/core/executor/
├── step_executor.py
│   ├── ToolStepExecutor
│   ├── ThinkStepExecutor
│   ├── SkillStepExecutor
│   └── VerifyStepExecutor
```

**Task:** Concrete implementations
**Tests:** Unit tests for each executor (mock tool_runtime, model, etc.)

---

### Step 3: Implement Context Manager (30 min)
```
src/core/executor/
├── context_manager.py
│   └── ContextManager (thread-safe dict)
```

**Task:** Simple, thread-safe context storage
**Tests:** Thread safety tests

---

### Step 4: Main Executor Orchestrator (2 hours)
```
src/core/executor/
├── executor.py
│   └── Executor (main orchestration)
```

**Task:** Orchestration logic, dependency resolution, step execution
**Tests:** Integration tests (mock steps)

---

### Step 5: Configuration & Builder (1 hour)
```
src/core/executor/
├── config.py
│   ├── ExecutorBuilder
│   └── StepExecutorFactory
```

**Task:** Wiring, configuration
**Tests:** Builder tests

---

### Step 6: Integration Tests (2 hours)
```
tests/
├── test_executor.py
│   ├── Test dependency resolution
│   ├── Test execution order
│   ├── Test context passing
│   ├── Test tool invocation
│   ├── Test think steps
│   ├── Test skill workflow steps
│   └── Test error handling
```

**Task:** End-to-end tests with mock components
**Tests:** 20+ tests covering all paths

---

### Step 7: Wire into Orchestrator (1 hour)
```
src/orchestrator/orchestrator.py
├── Add executor_builder
├── Add execute_plan() method
└── Add planning gate to gateway
```

**Task:** Integration, decide when to plan vs. when to skip
**Tests:** CLI end-to-end test

---

## Estimated Effort

| Phase | Hours | Status |
|-------|-------|--------|
| 7d.1: Interfaces | 1 | Not started |
| 7d.2: Step Executors | 2 | Not started |
| 7d.3: Context Manager | 0.5 | Not started |
| 7d.4: Main Executor | 2 | Not started |
| 7d.5: Config | 1 | Not started |
| 7d.6: Integration Tests | 2 | Not started |
| 7d.7: Wire into Orchestrator | 1 | Not started |
| **Total** | **9.5 hours** | |

---

# PART 5: DECISION POINTS & OPEN QUESTIONS

## Question 1: When to Plan?

Currently, gateway routes directly to skills. Should we:

**Option A:** Always plan complex tasks
```
gateway receives request
IF task_complexity >= HIGH:
   → Planner.plan() → Executor.execute()
ELSE:
   → Skill directly (old path)
```

**Option B:** Plan only when explicitly requested
```
gateway receives request
IF user said "plan first":
   → Planner.plan() → Executor.execute()
ELSE:
   → Skill directly
```

**Option C:** Planner decides (per-request)
```
gateway receives request
→ Planner.plan() (returns quick "is this complex?")
→ If plan has many steps, execute it
   Else, extract key step and run directly
```

**Recommendation:** Option A (smart routing based on complexity)

---

## Question 2: What Calls the Executor?

Should it be:

**Option A:** Orchestrator.execute_plan() (explicit)
```python
planner_response = orchestrator.plan_task(request)
execution_result = orchestrator.execute_plan(planner_response.plan)
```

**Option B:** Automatic within plan_task()
```python
planner_response = orchestrator.plan_task(request)
# Returns both plan AND execution result
```

**Option C:** Gateway calls it
```python
gateway.handle() knows about Executor
calls it automatically for complex tasks
```

**Recommendation:** Option A (explicit, gives user visibility into plan before execution)

---

## Question 3: How to Handle Skill Workflows in Plans?

When a plan step is `skill_workflow(TDD)`, the executor calls SkillStepExecutor, which calls skill_factory. Should:

**Option A:** Pass gathered context from previous steps
```python
# Executor gathered: file contents, patterns found
# Pass all to TDD skill as input
skill.run(request=description, context=previous_outputs)
```

**Option B:** Let skill ignore executor context, read files itself
```python
# Skill makes its own tool calls
# Executor doesn't pass context
```

**Recommendation:** Option A (executor gathers efficiently, skill uses what's handed)

---

## Question 4: Retry Strategy?

When a tool call fails, should executor:

**Option A:** Retry once automatically
```python
try:
   tool.execute()
except ToolError:
   retry tool.execute()  # One automatic retry
```

**Option B:** Never retry (fail fast)
```python
try:
   tool.execute()
except ToolError:
   raise → Abort plan
```

**Option C:** Configurable per step
```python
step.max_retries = 2  # Plan says how many
```

**Recommendation:** Option C (configurable, some steps transient, others deterministic)

---

## Question 5: Logging Strategy?

Should executor log:

**Option A:** Only step boundaries
```
Step 0: Started
Step 0: Completed
Step 1: Started
...
```

**Option B:** Detailed (every tool call, every model call)
```
Step 0: read_file(src/main.py)
  → Tool call successful
  → 450 bytes retrieved
Step 0: Completed
Step 1: search_code(pattern="def handle")
  → Found 3 matches
  → Pattern in gateway.py:47
Step 1: Completed
```

**Recommendation:** Option B (detailed logging to SQLite audit log in Phase 7e)

---

# PART 6: DESIGN PRINCIPLES CHECKLIST

For Phase 7d (Executor), follow:

- ✅ **SOLID**
  - S: Executor only orchestrates; step execution is delegated
  - O: New step types added without modifying Executor
  - L: All StepExecutors honor the interface contract
  - I: Executor depends on minimal interfaces
  - D: Executor depends on interfaces, not concretions

- ✅ **DRY**
  - Prompts centralized in prompts.py
  - Tool calling centralized in ToolStepExecutor
  - Context passing centralized in ContextManager

- ✅ **KISS**
  - Executor is simple orchestrator
  - No magic, no implicit behavior
  - Explicit dependencies

- ✅ **YAGNI**
  - No distributed execution (not needed yet)
  - No complex retry policies (keep simple)
  - No caching (add if needed later)

- ✅ **Composition over Inheritance**
  - Executor composed of: StepExecutor + ContextManager + Logger
  - Not: Executor inherits from Agent → Planner

- ✅ **LoK (Law of Demeter)**
  - Executor only talks to: StepExecutor, ContextManager, Logger
  - Not: Executor reaches into Plan internals
  - StepExecutor only talks to: tool_runtime or model_provider
  - Not: StepExecutor reaches into step details

---

# PART 7: TESTING STRATEGY (PHASE 7D)

## Unit Tests
- `test_step_executor.py` — Each executor in isolation (tool, think, skill)
- `test_context_manager.py` — Thread safety, output storage
- `test_dependency_resolution.py` — Topological sorting

## Integration Tests
- `test_executor.py` — Full execution with mock components
  - Test simple linear plan (no deps)
  - Test complex plan (with deps)
  - Test failure handling
  - Test timeout
  - Test context passing between steps

## End-to-End Tests
- `test_orchestrator_with_executor.py` — Real orchestrator, plan, executor
  - Test: modify → plan → execute → results

## Coverage Target
- **Unit tests:** 85%+ coverage
- **Integration tests:** All paths
- **E2E tests:** Happy path + error path

---

# PART 8: NEXT ACTIONS

## To Start Phase 7d:

1. **Read this document** — Understand the full context
2. **Review existing code:**
   - `src/core/task_plan.py` — TaskPlan schema
   - `src/core/planner_v2/` — How planner is designed
   - `src/core/tool_runtime.py` — Tool registry
3. **Create interfaces** (`src/core/executor/interfaces.py`) — 1 hour
4. **Implement step executors** — 2 hours
5. **Implement executor** — 2 hours
6. **Write tests** — 2 hours
7. **Integrate into orchestrator** — 1 hour

## Testing During Development:

```bash
# After each step:
pytest tests/test_executor.py -v

# Before committing:
pytest tests/test_task_plan.py tests/test_planner_v2.py tests/test_executor.py -v
```

---

# PART 9: OPEN DECISIONS FOR NEXT CONVERSATION

When you start Phase 7d, clarify:

1. **Planning Gate:** Should gateway always plan, or only on demand? (see Question 1)
2. **Skill Context:** Should executor gather context for skills? (see Question 3)
3. **Retry Strategy:** Configurable retries or fail-fast? (see Question 4)
4. **Logging Detail:** What level? (see Question 5)
5. **Model for Thinking:** Use qwen3-4b-thinking for THINK steps, or faster model? (qwen3-4b is proven but slower)

---

# PART 10: SUCCESS CRITERIA

Phase 7d is complete when:

- ✅ `Executor` class exists, 500–700 lines, loosely coupled
- ✅ `StepExecutor` implementations for all `ActionType` variants
- ✅ `ContextManager` with thread-safe context passing
- ✅ 20+ integration tests, all passing
- ✅ Can execute a complex multi-step plan with dependencies
- ✅ Can handle tool failures gracefully
- ✅ Can pass context between steps (step N uses outputs from steps N-1, N-2, etc.)
- ✅ Integrated into orchestrator; CLI can do: `plan-task` → `execute-plan`
- ✅ Audit logging implemented (Phase 7e) or at least stubs ready

---

# APPENDIX A: FILE CHECKLIST

Files created/updated up to end of Phase 7c:

```
✅ src/core/task_plan.py                 — TaskPlan schema
✅ src/core/tool_runtime.py              — ToolRegistry
✅ src/tools/schemas.py                  — Tool base classes
✅ src/tools/file_tools.py               — read_file, list_files
✅ src/tools/search_tools.py             — search_code
✅ src/core/planner_v2/interfaces.py     — LLMProvider, etc.
✅ src/core/planner_v2/providers.py      — LMStudio, Mock
✅ src/core/planner_v2/parsers.py        — JSON, YAML
✅ src/core/planner_v2/validators.py     — Plan validation
✅ src/core/planner_v2/prompts.py        — Prompt builders
✅ src/core/planner_v2/planner.py        — Main orchestrator
✅ src/core/planner_v2/config.py         — PlannerBuilder

⏳ src/core/executor/interfaces.py       — To create Phase 7d
⏳ src/core/executor/step_executor.py    — To create Phase 7d
⏳ src/core/executor/context_manager.py  — To create Phase 7d
⏳ src/core/executor/executor.py         — To create Phase 7d
⏳ src/core/executor/config.py           — To create Phase 7d
⏳ tests/test_executor.py                — To create Phase 7d
```

---

# APPENDIX B: Architecture Diagram (Complete)

```
LAYERS:

L0: User
    │ CLI input: "modify project, plan, execute"
    └─────────────────────────────────────────────────┐
                                                      ↓
L1: Orchestrator (main workflow engine)
    │ run() / modify() / plan_task() / execute_plan()
    │
    ├─→ Grilling (interview for CONTEXT.md)
    ├─→ Context Store (persist CONTEXT.md)
    ├─→ LLM Gateway (classify + route)
    │
    └─→ [NEW in Phase 7d] Executor branch:
        │
        ├─→ Planner (generate TaskPlan)
        │   └─→ qwen3-4b-thinking (reasoning model)
        │
        └─→ Executor (execute TaskPlan)
            ├─→ StepExecutor (dispatch by ActionType)
            │   ├─→ ToolStepExecutor (call tools)
            │   ├─→ ThinkStepExecutor (call model to reason)
            │   ├─→ SkillStepExecutor (run skills like TDD)
            │   └─→ VerifyStepExecutor (run tests)
            │
            ├─→ ContextManager (pass outputs between steps)
            │
            └─→ Tool Runtime (actual execution)
                ├─→ read_file, list_files, search_code
                ├─→ [Future] write_file, edit_file
                ├─→ [Future] run_tests, run_terminal
                └─→ [Future] git_*, analyze_image, web_search

L2: LLM Models (local, via LM Studio)
    │
    ├─→ qwen3-4b-thinking (planner, debugger, reasoning)
    ├─→ nemotron-3-nano-4b (fast executor)
    ├─→ essentialai/rnj-1 (complex executor)
    └─→ [Future] qwen3-vl-4b (vision)
```

---

# APPENDIX C: Links to Reference Documents

Inside this repository:

- `PHASE_6_COMPLETION_REPORT.md` — Phase 6 delivery details
- Code comments in `src/core/planner_v2/*.py` — Detailed explanations
- Test files (`tests/test_task_plan.py`, `tests/test_planner_v2.py`) — Usage examples

---

**END OF TASK PLAN**

**Next Conversation Starter:**

Copy this entire file and paste into a new chat with Claude, prefaced by:

```
You are continuing work on a personal local AI coding assistant 
(Phases 0-7c complete). Read the attached TASK PLAN to understand context.

Then implement Phase 7d: Executor.
```

Good luck! 🚀
