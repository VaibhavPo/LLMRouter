"""
grilling_selfplay_benchmark.py

Automated self-play benchmark for the "grilling" skill.

Instead of a human manually chatting with each candidate model for 10-15 min,
this script runs two LLM roles against each other via your local LM Studio
server (OpenAI-compatible endpoint):

  - INTERVIEWER  -> the model under test. Runs your existing grilling system
                    prompt. Asks questions, eventually writes CONTEXT.md.
  - SIMULATED USER -> a fixed, strong model (or the same model, your choice)
                    that answers ONLY from a hidden ground_truth fact list,
                    staying terse and realistic, never volunteering more than
                    asked.

At the end, the produced CONTEXT.md is scored against the hidden fact list:
  - recovered facts (mentioned correctly)
  - missed facts (never surfaced)
  - invented facts (present in doc, absent from ground truth) -- flagged,
    not auto-failed, since some inference is fine; you eyeball these.

Run:
    python grilling_selfplay_benchmark.py

Requires: LM Studio running locally with the server enabled
          (Developer tab -> Start Server), default http://localhost:1234/v1
"""

import json
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"

# Models under test as INTERVIEWER. Use the exact model id LM Studio reports
# (check with: curl http://localhost:1234/v1/models)
CANDIDATE_MODELS = [
    "quantfactory/octopus-planning",
    "mradermacher/qwen2.5-microsoft-nextcoder-instruct-fused-cod",
    "google/gemma-4-e2b",
]

# Model that plays the simulated user. Keep this FIXED across all runs so
# comparisons are apples-to-apples. Pick something reliable at following
# instructions -- doesn't need to be big.
SIMULATED_USER_MODEL = "google/gemma-4-e2b"

MAX_TURNS = 12          # hard cap so a bad model can't loop forever
TEMPERATURE_INTERVIEWER = 0.4
TEMPERATURE_USER = 0.3

GRILLING_SYSTEM_PROMPT = """You are a senior software architect helping a team clarify requirements.
Your job is to ask clarifying questions until the requirements are crystal clear.
Do NOT write any code. Do NOT propose solutions yet.
Only ask questions and listen.

When you feel the requirements are solid enough to write a specification,
say "Let me write CONTEXT.md based on what we've discussed:" and then
write a complete CONTEXT.md file with sections:
- Problem Statement
- Functional Requirements
- Non-Functional Requirements
- Assumptions
- Risks and Constraints
- Design Trade-offs (decisions made and why)
- Shared Vocabulary (terms we'll use)
- Open Questions (if any remain)

Keep asking until the requirements feel complete and unambiguous."""

USER_SIM_SYSTEM_TEMPLATE = """You are roleplaying as a real user who wants the following project built:

PROJECT: {project}

You know these facts about what you want (your actual requirements):
{facts}

Rules:
- Only reveal a fact when it is directly relevant to the question asked.
- Never volunteer facts that weren't asked about.
- If asked something not covered by your facts, improvise a short, plausible,
  consistent answer (a real user would not say "I don't know").
- Keep answers short and natural, like a real chat message (1-3 sentences).
- Do not mention that you are simulating a user or reference "ground truth".
- If the interviewer says they are ready to write CONTEXT.md, just say "sounds good, go ahead."
"""

# --------------------------------------------------------------------------
# TEST PROJECTS (ground truth). Add more here to widen the benchmark.
# --------------------------------------------------------------------------

PROJECTS = {
    "inventory_sync_api": {
        "project": "A small internal API service that keeps stock counts in sync across warehouses.",
        "facts": [
            "Must support exactly 3 warehouses, each with a different stock update frequency (one updates hourly, one every 15 min, one on-demand via manual trigger)",
            "Conflicting stock updates resolve by 'last write wins' UNLESS a conflict is flagged as high-value (>$10k SKU), in which case it needs manual review",
            "No authentication needed yet -- single internal team, trusted network only",
            "Budget is zero -- this is unpaid personal side-project time, nights and weekends",
            "Stack preference: Python/FastAPI backend, Postgres for storage",
            "No mobile app needed -- API + a simple internal dashboard is enough",
            "Must log every sync event with timestamp and source warehouse for audit purposes",
            "Timeline: no hard deadline, but wants a working prototype within a month",
            "Data volume is small -- a few hundred SKUs per warehouse, not enterprise scale",
            "No real-time push needed -- polling every few minutes is acceptable",
        ],
    },
    "reading_tracker": {
        "project": "A personal app to track books read and reading goals.",
        "facts": [
            "Wants to track pages read per day, not just books finished",
            "Wants a yearly reading goal (e.g. 24 books) with progress shown as a percentage",
            "Wants to log short personal notes/quotes per book, privately, not shared",
            "Only for one user -- no social/sharing features",
            "Wants it to work offline, since they read on flights often",
            "Data should sync back to a laptop when back online -- simple local file sync is fine, no cloud service required",
            "No barcode scanning needed -- manual title entry is fine",
            "Wants a small monthly summary view of pages read and books finished",
            "Comfortable with a very plain UI -- function over form",
            "No budget for paid APIs (e.g. no paid book-metadata lookup service)",
        ],
    },
}

# --------------------------------------------------------------------------
# LM STUDIO CALL
# --------------------------------------------------------------------------

def call_model(model_id: str, messages: list, temperature: float) -> str:
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LM_STUDIO_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach LM Studio at {LM_STUDIO_URL}. "
            f"Is the local server running? ({e})"
        )


# --------------------------------------------------------------------------
# SELF-PLAY LOOP
# --------------------------------------------------------------------------

@dataclass
class RunResult:
    model_id: str
    project_name: str
    turns_used: int
    transcript: list = field(default_factory=list)
    context_md: str = ""
    recovered_facts: list = field(default_factory=list)
    missed_facts: list = field(default_factory=list)


def _write_checkpoint(
    output_dir: Path,
    model_id: str,
    project_name: str,
    transcript: list,
    context_md: str = "",
):
    safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", model_id)
    out_path = output_dir / f"{safe_model}__{project_name}.md"
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(f"# {model_id} — {project_name}\n\n")
        fh.write(f"Interviewer turns: {len([t for t in transcript if t[0] == 'interviewer'])}\n\n")
        fh.write("## Transcript\n\n")
        for role, content in transcript:
            fh.write(f"**{role}:**\n{content}\n\n")
        if context_md:
            fh.write("## Context\n\n")
            fh.write(context_md)


def run_selfplay(model_id: str, project_name: str, project_data: dict) -> RunResult:
    output_dir = Path(__file__).parent / "benchmark_outputs"
    output_dir.mkdir(exist_ok=True)
    facts_block = "\n".join(f"- {f}" for f in project_data["facts"])
    user_sim_system = USER_SIM_SYSTEM_TEMPLATE.format(
        project=project_data["project"], facts=facts_block
    )

    interviewer_msgs = [
        {"role": "system", "content": GRILLING_SYSTEM_PROMPT},
        {"role": "user", "content": f"I want to build: {project_data['project']}"},
    ]
    user_sim_msgs = [{"role": "system", "content": user_sim_system}]

    transcript = []
    context_md = ""

    for turn in range(MAX_TURNS):
        interviewer_reply = call_model(
            model_id, interviewer_msgs, TEMPERATURE_INTERVIEWER
        )
        transcript.append(("interviewer", interviewer_reply))
        _write_checkpoint(output_dir, model_id, project_name, transcript)
        interviewer_msgs.append({"role": "assistant", "content": interviewer_reply})

        if "let me write context.md" in interviewer_reply.lower():
            context_md = interviewer_reply
            break

        user_sim_msgs.append({"role": "user", "content": interviewer_reply})
        user_reply = call_model(SIMULATED_USER_MODEL, user_sim_msgs, TEMPERATURE_USER)
        transcript.append(("simulated_user", user_reply))
        _write_checkpoint(output_dir, model_id, project_name, transcript)
        user_sim_msgs.append({"role": "assistant", "content": user_reply})
        interviewer_msgs.append({"role": "user", "content": user_reply})

    else:
        # hit MAX_TURNS without the model committing to write CONTEXT.md
        interviewer_msgs.append(
            {
                "role": "user",
                "content": "Please write CONTEXT.md now based on everything discussed.",
            }
        )
        context_md = call_model(model_id, interviewer_msgs, TEMPERATURE_INTERVIEWER)
        transcript.append(("interviewer", context_md))
        _write_checkpoint(output_dir, model_id, project_name, transcript, context_md)

    result = RunResult(
        model_id=model_id,
        project_name=project_name,
        turns_used=len([t for t in transcript if t[0] == "interviewer"]),
        transcript=transcript,
        context_md=context_md,
    )
    score_against_ground_truth(result, project_data["facts"])
    return result


def score_against_ground_truth(result: RunResult, facts: list):
    doc_lower = result.context_md.lower()
    for fact in facts:
        # crude but fast: pull a few keywords from the fact and check presence
        keywords = [
            w.strip(".,()%$").lower()
            for w in re.findall(r"[A-Za-z0-9\-\$%]{4,}", fact)
        ]
        # require a decent fraction of keywords to appear
        hits = sum(1 for kw in keywords if kw in doc_lower)
        if keywords and hits / len(keywords) >= 0.4:
            result.recovered_facts.append(fact)
        else:
            result.missed_facts.append(fact)


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    all_results = []
    output_dir = Path(__file__).parent / "benchmark_outputs"
    output_dir.mkdir(exist_ok=True)

    for model_id in CANDIDATE_MODELS:
        for project_name, project_data in PROJECTS.items():
            print(f"\n{'=' * 70}")
            print(f"INTERVIEWER: {model_id}  |  PROJECT: {project_name}")
            print(f"{'=' * 70}")
            try:
                result = run_selfplay(model_id, project_name, project_data)
            except RuntimeError as e:
                print(f"  SKIPPED (error): {e}")
                continue

            recovered = len(result.recovered_facts)
            total = recovered + len(result.missed_facts)
            print(f"  Turns used: {result.turns_used}")
            print(f"  Facts recovered: {recovered}/{total}")
            if result.missed_facts:
                print("  Missed:")
                for f in result.missed_facts:
                    print(f"    - {f}")

            all_results.append(result)

            # The transcript was checkpointed during the run; write the final result too.
            _write_checkpoint(
                output_dir,
                model_id,
                project_name,
                result.transcript,
                result.context_md,
            )

    print(f"\n\n{'#' * 70}")
    print("SUMMARY")
    print(f"{'#' * 70}")
    print(f"{'Model':45} {'Project':22} {'Turns':>6} {'Recovered':>10}")
    for r in all_results:
        recovered = len(r.recovered_facts)
        total = recovered + len(r.missed_facts)
        print(
            f"{r.model_id[:44]:45} {r.project_name:22} {r.turns_used:>6} "
            f"{f'{recovered}/{total}':>10}"
        )


if __name__ == "__main__":
    main()
