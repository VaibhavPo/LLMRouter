# Role

Act as my **Senior AI Systems Architect, Local LLM Engineer, and hands-on mentor**.

I am building my own **personal AI coding assistant** that runs primarily on my local machine and uses LM Studio with multiple local LLMs instead of relying on expensive cloud LLM APIs.

I am a CSE graduate and comfortable with programming and software concepts, but I want you to teach me the architecture and implementation properly rather than assuming I already know how production-grade AI agents and model orchestration work.

Do NOT simply give me a large amount of code at once.

I want to understand the system deeply and build it incrementally.

**This is v3 of this prompt.** v1 assumed a role architecture based on model names/sizes before any benchmarking. v2 replaced those assumptions with real Phase 1 benchmark evidence. v3 adds a new architectural axis on top of both: a **Skill Layer**, adapted from the open-source `mattpocock/skills` repo, which separates "which model handles this" (already solved by the router) from "what disciplined procedure should the model follow" (a gap neither v1 nor v2 addressed). Treat the "Current Evidence" and "Skill Layer" sections below as the source of truth going forward.

---

# Current Evidence (unchanged from v2, still authoritative)

## Actual model inventory (from LM Studio, ground truth)

| Path | Arch | Params | Publisher | Quant | Size |
|---|---|---|---|---|---|
| `qwen.qwen3.5-9b@q2_k` / `@q3_k_s` | qwen35 | 9B | DevQuasar | Q2_K / Q3_K_S | 4.6–5.2GB |
| `qwen_qwen3.5-9b` | qwen35 (MTP) | 9B | bartowski | IQ2_M | 4.9GB |
| `essentialai/rnj-1` | gemma3 | 8.3B | lmstudio-community | Q4_K_M | 5.1GB |
| `google/gemma-4-e2b` | gemma4 | 4.6B | lmstudio-community | Q4_K_M | 4.4GB |
| `nvidia/nemotron-3-nano-4b` | nemotron_h | 4.0B | lmstudio-community | Q4_K_M | 2.8GB |
| `qwen/qwen3-vl-4b` | qwen3vl | 4B | lmstudio-community | Q4_K_M | 3.3GB |
| `deepseek/deepseek-r1-0528-qwen3-8b` | qwen3 | 8B | lmstudio-community | Q3_K_L | 4.4GB |
| `qwen/qwen3-4b-thinking-2507` | qwen3 | 4B | lmstudio-community | Q3_K_L | 2.2GB |
| `qwen/qwen3-1.7b` | qwen3 | 1.7B | lmstudio-community | Q3_K_L | 1.1GB |

`essentialai/rnj-1` = Gemma 3 8.3B (confirmed via model card, not an unknown model). `google/gemma-4-e2b` is natively multimodal (text + image) despite being benchmarked so far only as a text coder.

## Benchmark results summary

| Model | Role | Status |
|---|---|---|
| `nemotron-3-nano-4b` | Primary fast coder | ✅ proven — 6/6 tests, ~5s |
| `essentialai/rnj-1` (gemma3 8.3B) | Coder, larger context headroom | ✅ proven — 6/6 tests, ~7s |
| `gemma-4-e2b` | Secondary coder / reviewer, untested vision candidate | ✅ proven as coder (6/6, ~11s); vision unproven |
| `qwen3-4b-thinking` | Reasoning / planning / debugging | ✅ proven — 3/3 correct diagnoses, 10–49s |
| `deepseek-r1-8b` | — | ❌ excluded — 130–230s+ per case, runaway generation (one case still running past 10min/4,700+ tokens before being killed) |
| `qwen3.5-9b` | — | ❌ excluded — no usable quant at current resource budget (only Q2_K/Q3_K_S/IQ2_M available); real-quant test also produced syntax error, 94–120s+ |
| `qwen3-1.7b` | Classifier (`task_type`/`complexity` only) | ⚠️ usable with caveats — 6/7 structurally valid JSON, but 3 of those 6 had a wrong `requires_vision` field, including inverting the one case that actually needed vision. `requires_vision` needs a deterministic override, not LLM judgment. |
| `qwen3-vl-4b` | Vision (candidate) | 🔲 not yet benchmarked on an actual vision task |

**Immediately pending from v2:** a real vision benchmark (`qwen3-vl-4b` vs `gemma-4-e2b`, head-to-head) before the vision branch of the router is enabled.

---

# Skill Layer (new in v3)

## Concept

A **skill** (borrowed from `github.com/mattpocock/skills`) is not a model and not a new architectural component competing with the router — it is a **procedure file** (Markdown) injected into whichever model the router already selected, telling it *how* to work rather than *what* to work on. The router answers "which model," a skill answers "what discipline." These are orthogonal and both are needed:

```
TASK ANALYZER → picks skill/procedure   (NEW — Skill Layer)
MODEL ROUTER  → picks model/worker      (EXISTING — v2)
        \                /
         both feed the agent call
```

## Two invocation types (borrowed directly, keep this distinction)

- **User-invoked** — I explicitly ask for a workflow (equivalent of their `/tdd`, `/diagnosing-bugs`). Deliberate, orchestration-level.
- **Model-invoked** — the agent reaches for a skill automatically when the task fits. This is one layer deeper than my existing classifier: not just "what kind of task is this" but "what disciplined procedure should this task follow."

## Mapping their skills onto my architecture

| Their skill | What it does | Where it fits |
|---|---|---|
| `tdd` (red-green-refactor) | Forces failing-test-first before implementation | **Directly slots into my existing Verification Loop (Phase 8)** — this is the missing discipline inside that loop, not a new component. **Adopt first.** |
| `diagnosing-bugs` | Gated phase-by-phase debugging (minimize → hypothesize → instrument → fix → regression-test) | Becomes the actual procedure my **Debugger** role (`qwen3-4b-thinking`) follows, instead of freeform "find the bug" |
| `code-review` | Two-axis review (Standards + Spec) as **parallel sub-agents** so neither pollutes the other | Becomes the procedure for my **Reviewer** role. Given my proven models are all small (4–8B), running two reviewer calls concurrently (e.g. `gemma-4-e2b` + `rnj-1`, or `gemma-4-e2b` prompted twice on each axis) may now be feasible on my hardware — worth testing VRAM headroom for this specifically |
| `grilling` / `grill-with-docs` | Interview loop that resolves ambiguity before building; writes a shared-vocabulary `CONTEXT.md` | **New component**, sits *before* my Planner. Directly addresses "no one knows exactly what they want." Output feeds my Context Manager (Phase 9) |
| `to-spec` / `to-tickets` | Converts a conversation into a written spec, then tracer-bullet tickets with blocking edges | **New component** — formalizes the handoff between planning and implementation for larger multi-file tasks |
| `handoff` | Compacts a session into a resumable document for another agent | Solves my Phase 10 (Memory) short-term execution state problem directly |
| `domain-modeling` / `CONTEXT.md` | Living shared-vocabulary doc so agents don't use 20 words where the project uses 1 | Belongs in my Context Manager, alongside repo tree/embeddings. No model call needed once written — cheap to reuse every session |

## Critical caveat — do not adopt wholesale without testing

Their skills are built and tuned against Claude Code / Codex-class models with strong instruction-following. My own evidence (Benchmark 2 above) already shows `qwen3-1.7b` struggling to reliably hold a *simple* JSON schema. A multi-phase gated skill like `diagnosing-bugs` demands much more sustained procedural discipline than a JSON object.

**Rule: no skill gets adopted into the live workflow without first testing whether my actual proven models (`nemotron-3-nano-4b`, `rnj-1`, `qwen3-4b-thinking`) can follow its phase-gating reliably.** Treat each adapted skill the same way v2 treated each model role — as a hypothesis to benchmark, not an assumption to inherit.

## Adoption order (smallest, most directly useful first)

1. **`tdd`** — adapt into my Verification Loop (Phase 8), test against `nemotron-3-nano-4b` or `rnj-1` first, since this phase is already planned and this skill is a direct fit, not a new component.
2. **`diagnosing-bugs`** — adapt into my Debugger role, test against `qwen3-4b-thinking` specifically, since it's my only proven reasoning-tier model and this is exactly its job.
3. **`grilling`** — adapt as a pre-Planner step, since ambiguity resolution has been a real gap (see "Design with other models" turn earlier where I had to explicitly redirect away from carried-forward assumptions).
4. Everything else (`code-review` parallel sub-agents, `to-spec`/`to-tickets`, `handoff`, `domain-modeling`) — revisit after 1–3 are proven, and after the vision benchmark closes out Phase 1.

---

# Everything below is unchanged from v2 and still applies

## Important Architectural Decision

I do NOT want to fine-tune models initially.

I want to first explore:

**Model Router + Agent Orchestrator + Tool Runtime + Context Management + Verification Loop + Skill Layer**

The system should use the models as specialized workers rather than expecting one model to do everything, and should use skills as specialized procedures rather than expecting the model to infer discipline on its own.

Explain the difference between:

1. Model
2. Model router
3. Agent
4. Agent orchestrator
5. Tool runtime
6. Context manager
7. Memory
8. Planner
9. Executor/Coder
10. Reviewer
11. Debugger
12. Explainer
13. **Skill (new)** — a procedure file, not a model or agent; injected into whichever model the router selects

Explain why each exists, which parts actually need an LLM, and which parts (like a skill file, or a deterministic override) are just structured text/logic requiring no inference at all.

---

## Revised Target Architecture

```text
                    VS CODE
                       |
                       v
              AI CODING INTERFACE
                       |
                       v
              +------------------+
              |   ORCHESTRATOR   |
              +------------------+
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
   TASK ANALYZER   CONTEXT MANAGER  SKILL LAYER
  (qwen3-1.7b        (CONTEXT.md,   (tdd, diagnosing-bugs,
   classify +        repo tree,      grilling — procedure
   deterministic      embeddings)    files, not models)
   override for
   requires_vision)
        |
        v
    MODEL ROUTER  (deterministic policy engine, Version 3)
        |
+-------+-------+-------+
|       |       |       |
v       v       v       v
SIMPLE LARGER  REASON  VISION
CODE   CONTEXT /PLAN   (disabled until
 |      CODE     |      benchmarked)
 v       v       v
nemotron rnj-1  qwen3-4b
-nano-4b(gemma3 -thinking
        8.3B)
   |
   v
 TOOLS
+---+---+
|   |   |
Files Git Terminal
   |
   v
 TESTS  <-- governed by `tdd` skill procedure once adopted
   |
+--+--+
|     |
PASS  FAIL
|     |
v     v
REVIEWER   DEBUGGER
(gemma-4-e2b, (qwen3-4b-thinking,
governed by    governed by
`code-review`  `diagnosing-bugs`
skill once     skill once
adopted)       adopted)
|     |
+--+--+
   |
   v
 DONE
```

---

## LM Studio

I want LM Studio to act primarily as my **local model serving layer**.

I want to understand:

* LM Studio server
* OpenAI-compatible API
* model identifiers
* JIT model loading
* Auto-Evict
* model unloading
* simultaneous models
* VRAM/RAM considerations
* context length
* quantization
* how model switching works
* how my Python application communicates with LM Studio
* whether the orchestrator should explicitly load/unload models or simply request them

Given the confirmed model sizes (nothing above ~8.3B, several under 5B), also address whether it's feasible to keep more than one model resident in VRAM simultaneously — this now matters more, since the `code-review` skill wants two reviewer calls run in parallel.

---

## VS Code

Eventually I want this to work naturally inside VS Code.

I want to understand the available approaches:

1. Build my own VS Code extension
2. Use Continue
3. Use Cline
4. Use another existing coding-agent framework
5. Put my own router behind an existing VS Code AI coding interface

Compare these approaches and recommend the best one for my project. I prefer reusing existing infrastructure where possible instead of reinventing file editing, terminal execution, diffs, codebase context, etc.

Also address: does adopting a Skill Layer change this recommendation at all — e.g. does Continue or Cline already have a concept of injectable procedure files that I could reuse instead of building my own?

---

## The Core Agent Workflow

Teach me how to implement a workflow such as:

```text
User request
    ↓
Skill selection (which procedure applies?)     <- NEW
    ↓
Task classification
    ↓
Context retrieval
    ↓
Planning (optionally gated by `grilling`)       <- NEW
    ↓
Implementation
    ↓
Run tests (governed by `tdd` if adopted)        <- NEW
    ↓
Review (governed by `code-review` if adopted)   <- NEW
    ↓
    ├── PASS → Final response
    │
    └── FAIL
          ↓
       Debugging (governed by `diagnosing-bugs` if adopted)  <- NEW
          ↓
       Implementation
          ↓
        Testing
```

Explain:

* what information is passed between agents
* what should NOT be passed
* how to preserve context
* how to prevent context windows from becoming huge
* how agents know what previous agents did
* how file changes are tracked
* how errors are passed to the debugger
* how to prevent infinite loops
* how to decide when to stop
* **how skill files get loaded/injected without bloating the context window on every call**

---

## Structured Communication

Do not make agents communicate only through natural-language paragraphs.

Teach me how to use structured outputs such as:

```json
{
  "task_type": "debugging",
  "complexity": "high",
  "requires_vision": false,
  "requires_reasoning": true,
  "skill": "diagnosing-bugs"
}
```

and:

```json
{
  "status": "FAIL",
  "issues": [
    {
      "file": "auth.py",
      "line": 42,
      "severity": "high",
      "description": "..."
    }
  ]
}
```

Explain why structured outputs are important for reliable orchestration. Note: real classifier output has already shown a systematic weakness on the `requires_vision` field (Benchmark 2) — factor this into how much the router trusts LLM-generated structured fields (including a future `skill` field) vs. deterministic overrides.

---

## Routing

Teach me how to progressively improve the router.

### Version 1 — Simple deterministic routing
### Version 2 — Small LLM classifies the task
### Version 3 — LLM classification + deterministic policy engine *(current — in progress)*
### Version 4 — Model capabilities + benchmark data
### Version 5 — Performance-aware routing based on historical success rate, latency, and resource usage

Explain the advantages and disadvantages of each. Also explain whether skill selection should follow the same version progression (deterministic → LLM-classified → hybrid) or whether it's simpler than model routing since skills are lower-stakes to guess wrong (a bad skill choice degrades quality; a bad model choice can outright fail the task).

---

## Model Benchmarking

Continue building out the benchmark suite. Completed: simple code generation, classifier JSON output, reasoning/diagnosis. Pending: vision, tool-calling, repository-understanding, a harder coding task to differentiate `nemotron-3-nano-4b` from `rnj-1`, and now — **skill-following benchmarks**: can `nemotron-3-nano-4b`/`rnj-1` reliably follow the `tdd` procedure end to end, and can `qwen3-4b-thinking` reliably follow `diagnosing-bugs` end to end, without dropping phases or skipping gates?

---

## Context Management

Teach this very carefully.

I want to understand how a coding agent decides which files to send to the model. Explain and eventually implement: repository tree, relevant file selection, symbol extraction, grep/search, embeddings, vector search, semantic retrieval, dependency relationships, recently modified files, current editor selection, current open file, git diff, error traceback, test results — **plus now: where `CONTEXT.md` (shared-vocabulary doc from `grilling`) fits alongside these, and whether it should always be included or only retrieved when relevant.**

I already have experience with Qdrant, so explain whether Qdrant is useful here and where it fits.

---

## Tool Runtime

Eventually the agents should be able to use tools such as:

```text
read_file
write_file
edit_file
search_code
list_files
run_terminal
run_tests
git_diff
git_status
git_log
```

Teach me why tools should be controlled by the orchestrator/runtime rather than allowing a model to execute arbitrary operations directly. Explain tool schemas, tool calls, validation, permissions, sandboxing, timeouts, command restrictions, approval mechanisms, error handling.

---

## Safety

Explain how to safely handle: destructive commands, `rm`, database migrations, git reset, force push, environment variables, API keys, `.env`, shell commands, arbitrary code execution.

I want a practical safety model rather than unnecessary enterprise complexity.

---

## Memory

Explain the difference between:

* **Short-term execution state** — what happened during the current task
* **Project memory** — important information about the repository (now includes `CONTEXT.md`)
* **Long-term user preferences** — my coding preferences and interaction style
* **Vector memory** — retrievable historical information

Also explain where `handoff`-style session compaction fits — is it the same as short-term execution state, or a distinct mechanism for resuming across sessions?

Explain what should actually be stored and what should not.

---

## Explanation Mode

I want to be able to ask:

> "Why did you change this?" / "Why did you choose the reasoning model over the fast coder?" / "Why did the first implementation fail?" / "What did the reviewer find?" / "Which skill governed this task, and why?" / "Show me the reasoning behind the architecture."

The system should use execution history and structured state to answer these questions, without exposing private chain-of-thought — concise decision records, plans, tool actions, test results, skill selections, and explanations only.

---

## Technology Stack

Prefer a simple stack initially. I am comfortable with Python.

Consider: Python, FastAPI, LM Studio API (`lmstudio` python SDK — confirmed working, used in Phase 1 benchmark scripts), OpenAI-compatible Python client, Pydantic, SQLite initially, Qdrant later, VS Code, Continue/Cline if useful, and now: **plain Markdown files for skills** (no new tech needed — a skill is just a text file loaded into a prompt).

Do not introduce unnecessary technologies. If another technology is clearly better, explain why before recommending it.

---

## Development Strategy

## Phase 0 — Understand the architecture ✅ done
## Phase 1 — Connect Python to LM Studio ✅ mostly done — vision benchmark still pending
## Phase 2 — Basic router — next up, using only proven models (nemotron-3-nano-4b, rnj-1, qwen3-4b-thinking); vision branch disabled until benchmarked
## Phase 3 — Intelligent classifier — partially done, needs deterministic `requires_vision` override
## Phase 4 — Model registry
## Phase 5 — Planner — will incorporate `grilling` once tested
## Phase 6 — Coding agent
## Phase 7 — Tool runtime
## Phase 8 — Verification loop — will incorporate `tdd` skill once tested (adoption priority #1)
## Phase 9 — Context manager — will incorporate `CONTEXT.md`/`domain-modeling`
## Phase 10 — Memory — will incorporate `handoff`-style compaction
## Phase 11 — VS Code integration
## Phase 12 — Benchmarking — now includes skill-following tests, not just model tests
## Phase 13 — Intelligent routing
## Phase 14 — Skill Layer rollout *(new)* — adopt `tdd` → `diagnosing-bugs` → `grilling` → others, each gated by its own benchmark against my proven models, per the adoption order above

---

## How I Want You To Teach Me

For every phase:

1. Explain the concept first.
2. Show the architecture.
3. Explain why we need it.
4. Explain alternatives.
5. Tell me what files we will create.
6. Give me the smallest working implementation.
7. Explain the important code line by line.
8. Tell me exactly where to run it.
9. Tell me how to test it.
10. Show expected output.
11. Explain common errors.
12. Only then move to the next phase.

Do not skip foundational concepts. Do not overwhelm me with the entire codebase at once. When something can be done in two ways, compare them and recommend one.

---

## Important Rules

* Prefer local models whenever possible.
* Do not recommend paid APIs unless there is a strong technical reason.
* Do not assume a 70B cloud model is necessary.
* Do not recommend fine-tuning unless we first establish that prompting, routing, context management, tool orchestration, and skill discipline are insufficient.
* Do not assume the strongest/largest model should handle every task — evidence shows the smallest proven coder (nemotron-3-nano-4b) is also the fastest, and the largest available model (qwen3.5-9b) is currently unusable at this hardware budget.
* Optimize for practical usefulness, latency, RAM/VRAM usage, reliability, and privacy.
* Prefer existing open-source infrastructure when it saves substantial development effort — this is exactly why the Skill Layer borrows from `mattpocock/skills` instead of inventing procedures from scratch.
* Do not blindly copy architecture from Cursor or other commercial products.
* Explain what we can realistically reproduce locally.
* Clearly distinguish between what is handled by LM Studio, the orchestrator, VS Code/Continue/Cline, the LLM, and now the Skill Layer (which needs no LLM at all to select a static procedure file, only to follow it).
* Use current documentation when discussing current LM Studio, Continue, Cline, VS Code, or model capabilities.
* Do not assign a model a role in the live router without a benchmark result to back it.
* **New in v3:** do not adopt an external skill/procedure into the live workflow without first testing whether my actual proven local models can follow its phase-gating reliably. A skill designed for frontier cloud models is a hypothesis on small local models, not a given.

---

## Most Important Requirement

Treat this as a **real software project**, not a theoretical discussion. I want to eventually have a working personal coding assistant on my own computer, and I want to understand what I am building instead of blindly copying code.

**Current position:** Phase 1 is nearly complete (vision benchmark pending). Phase 2's router is designed and ready to build using only proven models. The Skill Layer is a new, parallel track — start by adapting and testing the `tdd` skill against my Verification Loop plan, since it's the most direct fit and lowest-risk place to prove out whether my local models can hold external procedural discipline at all.
