# Restructure Summary

This document outlines the file movements and updates made to reorganize the codebase into a clean, maintainable structure.

## Directory Structure Created

The following main directories were established to house the source code and tests:
- `src/core/` (Routing, Gateway, and Model logic)
- `src/context/` (Context Store logic)
- `src/orchestrator/` (Main orchestration logic, grilling, triviality checks)
- `src/bootstrap/` (Cold bootstrap pipeline)
- `src/skills/` (Skill runners)
- `src/skills/procedures/` (Skill definitions as `.txt` files)
- `src/cli/` (Command-line interface entry points)
- `tests/` (Unit and integration tests)
- `configs/`

## File Movements

### Core (`src/core/`)
- `llm_router/router.py` ➔ `src/core/router.py`
- `llm_gateway/gateway.py` ➔ `src/core/gateway.py`
- `llm_router/models.py` ➔ `src/core/models.py`
- `llm_router/classifier.py` ➔ `src/core/classifier.py`
- `llm_router/schema.py` ➔ `src/core/schema.py`
- `llm_router/client.py` ➔ `src/core/client.py`

### Context (`src/context/`)
- `context_store.py` ➔ `src/context/context_store.py`

### Orchestrator (`src/orchestrator/`)
- `orchestrator.py` ➔ `src/orchestrator/orchestrator.py`
- `skills/grilling_runner.py` ➔ `src/orchestrator/grilling.py`
- `change_classifier.py` ➔ `src/orchestrator/triviality_judge.py`
- `context_merge.py` ➔ `src/orchestrator/modify.py`

### Bootstrap (`src/bootstrap/`)
- `codebase_reader.py` ➔ `src/bootstrap/codebase_reader.py`
- `bootstrap_runner.py` ➔ `src/bootstrap/bootstrap_runner.py`
- `bootstrap_interviewer.py` ➔ `src/bootstrap/bootstrap_interviewer.py`

### Skills (`src/skills/`)
- `skills/skill_runner.py` ➔ `src/skills/skill_loader.py`
- `skills/diagnosis_runner.py` ➔ `src/skills/diagnosis_runner.py`
- All markdown (`.md`) procedures in `skills/` were moved to `src/skills/procedures/` and renamed to `.txt`.

### CLI (`src/cli/`)
- `main.py` ➔ `src/cli/main.py`
- `llm_router/run_manual.py` ➔ `src/cli/run_manual.py`

### Tests (`tests/`)
All `test_*.py` files scattered across the root, `skills/`, `llm_router/`, and `llm_gateway/` were consolidated into the single `tests/` directory. 

## Code Updates
- `__init__.py` files were created for each package under `src/`.
- All imports in the `.py` files (both inside `src/` and `tests/`) were successfully updated to use absolute imports from the new `src.*` modules. 
- The `src/cli/main.py` file was modified to use `def cli():` instead of `def main():` and received an updated shebang and execution block: `if __name__ == "__main__": import sys; from src.cli.main import cli; cli()`.
- Successfully verified using `python -m pytest tests/ --collect-only` (70 tests collected cleanly with zero import errors).
