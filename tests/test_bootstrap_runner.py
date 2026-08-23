"""
Test suite for BootstrapRunner.

Tests:
  1. Inference: mock inference produces CONTEXT.md with [UNKNOWN] markers
  2. Unknown parsing: [UNKNOWN: ...] entries are extracted correctly
  3. Finalization: interview answers replace [UNKNOWN] entries
  4. Validation: missing sections and unresolved [UNKNOWN] are caught
  5. Change Log: entries are appended correctly
"""

import tempfile
from pathlib import Path
from src.bootstrap.codebase_reader import CodebaseReader, BootstrapPayload
from src.bootstrap.bootstrap_runner import BootstrapRunner


# Helper: create a minimal BootstrapPayload for testing
def create_minimal_payload() -> BootstrapPayload:
    """Create a minimal test payload."""
    return BootstrapPayload(
        file_tree="project/\n├── README.md\n└── main.py",
        file_contents={
            "README.md": "# My Service\nA payment service.",
            "main.py": "print('hello')",
        },
        detected_stack=["python", "fastapi"],
        detected_patterns=["pytest"],
        total_tokens_used=500,
        files_skipped=[],
    )


def test_infer_with_mock():
    """Inference with mock response produces CONTEXT.md with [UNKNOWN] entries."""
    runner = BootstrapRunner()
    payload = create_minimal_payload()
    
    result = runner.infer(
        payload,
        change_request="Add idempotency keys to charge endpoint",
        use_mock=True,
    )
    
    # Check we got a result
    assert result.draft_context_md is not None
    assert len(result.draft_context_md) > 0
    
    # Check required sections are present
    assert "# Problem Statement" in result.draft_context_md
    assert "# Business Context" in result.draft_context_md
    assert "# Functional Requirements" in result.draft_context_md
    
    # Check [UNKNOWN] markers are present
    assert len(result.unknown_entries) > 0
    assert any("business priority" in u.lower() for u in result.unknown_entries)
    
    print("✓ test_infer_with_mock")


def test_parse_unknown_entries():
    """[UNKNOWN: ...] entries are parsed correctly."""
    runner = BootstrapRunner()
    
    context_md = """
# Problem Statement
This is a service.

# Shared Vocabulary
[UNKNOWN: Business domain terms]

# Architecture
[UNKNOWN: Multi-region failover strategy]
Some architecture details.

# Non-Functional Requirements
[UNKNOWN: SLA and performance targets]
[UNKNOWN: Compliance requirements (GDPR, PCI-DSS)]
"""
    
    unknowns = runner._parse_unknown_entries(context_md)
    
    assert len(unknowns) == 4
    assert "Business domain terms" in unknowns
    assert "Multi-region failover strategy" in unknowns
    assert "SLA and performance targets" in unknowns
    print("✓ test_parse_unknown_entries")


def test_finalise_replaces_unknowns():
    """Finalise replaces [UNKNOWN] entries with interview answers."""
    runner = BootstrapRunner()
    
    draft = """# Problem Statement
Payment service.

# Business Context / Objectives
[UNKNOWN: Business priority and SLA]

# Functional Requirements
- Process charges
- [UNKNOWN: Idempotency strategy]

# Non-Functional Requirements
[UNKNOWN: Performance targets]

# Tech Stack
Python, FastAPI

# Architecture
Monolithic service

# Shared Vocabulary
[UNKNOWN: Domain terminology]

# Assumptions
Database is PostgreSQL
"""
    
    answers = {
        "Business priority and SLA": "Critical service, 99.95% uptime SLA",
        "Idempotency strategy": "Use idempotency keys for charge endpoint",
        "Performance targets": "Sub-100ms latency p95, 1000 RPS capacity",
        "Domain terminology": "Gateway = payment processor, Settlement = fund transfer",
    }
    
    final = runner.finalise(draft, answers)
    
    # Check unknowns are replaced
    assert "99.95% uptime SLA" in final
    assert "idempotency keys" in final.lower()
    assert "1000 RPS" in final
    assert "payment processor" in final
    
    # Check [UNKNOWN] tags are gone
    assert "[UNKNOWN:" not in final
    
    # Check Change Log was added
    assert "# Change Log" in final or "## Change Log" in final
    
    print("✓ test_finalise_replaces_unknowns")


def test_finalise_rejects_partial_answers():
    """Finalise rejects CONTEXT.md with unresolved [UNKNOWN] entries."""
    runner = BootstrapRunner()
    
    draft = """# Problem Statement
Service.

# Business Context / Objectives
[UNKNOWN: SLA]
[UNKNOWN: Availability targets]

# Functional Requirements
Features

# Non-Functional Requirements
None

# Tech Stack
Python

# Architecture
Modular

# Shared Vocabulary
None

# Assumptions
PostgreSQL
"""
    
    # Only answer one of two questions
    answers = {
        "SLA": "99.95% uptime",
    }
    
    try:
        runner.finalise(draft, answers)
        assert False, "Should have raised ValueError for unresolved [UNKNOWN] entries"
    except ValueError as e:
        assert "[UNKNOWN:" in str(e)
        print("✓ test_finalise_rejects_partial_answers")


def test_validation_missing_sections():
    """Validation catches missing required sections."""
    runner = BootstrapRunner()
    
    incomplete = """# Problem Statement
Service.

# Tech Stack
Python

# Architecture
Modular

# Assumptions
PostgreSQL
"""
    
    try:
        runner._validate_context_md(incomplete)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "missing required sections" in str(e).lower()
        print("✓ test_validation_missing_sections")


def test_validation_unresolved_unknowns():
    """Validation catches unresolved [UNKNOWN] entries."""
    runner = BootstrapRunner()
    
    unresolved = """# Problem Statement
Service.

# Business Context / Objectives
[UNKNOWN: SLA requirements]

# Functional Requirements
Features

# Non-Functional Requirements
None

# Tech Stack
Python

# Architecture
Modular

# Shared Vocabulary
None

# Assumptions
PostgreSQL
"""
    
    try:
        runner._validate_context_md(unresolved)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "[UNKNOWN:" in str(e)
        print("✓ test_validation_unresolved_unknowns")


def test_change_log_creation():
    """Change Log section is created if it doesn't exist."""
    runner = BootstrapRunner()
    
    draft = """# Problem Statement
Service.

# Business Context / Objectives
Context

# Functional Requirements
Features

# Non-Functional Requirements
None

# Tech Stack
Python

# Architecture
Modular

# Shared Vocabulary
None

# Assumptions
PostgreSQL
"""
    
    final = runner._append_change_log_entry(draft, "Cold bootstrap completed")
    
    assert "# Change Log" in final or "## Change Log" in final
    assert "Cold bootstrap completed" in final
    assert "UTC" in final  # timestamp
    
    print("✓ test_change_log_creation")


def test_change_log_append():
    """Change Log entries are appended to existing section."""
    runner = BootstrapRunner()
    
    draft = """# Problem Statement
Service.

# Change Log
- 2024-01-01 10:00 UTC: Initial bootstrap
"""
    
    final = runner._append_change_log_entry(draft, "Added idempotency")
    
    # Both entries should be present
    assert "Initial bootstrap" in final
    assert "Added idempotency" in final
    
    print("✓ test_change_log_append")


def test_extract_context_md():
    """Extract CONTEXT.md from response that may have preamble."""
    runner = BootstrapRunner()
    
    response = """I'll now produce the CONTEXT.md for your project:

# Problem Statement
This service...

# Business Context / Objectives
It exists...

# Functional Requirements
Features include...
"""
    
    extracted = runner._extract_context_md(response)
    
    assert extracted.startswith("# Problem Statement")
    assert "Business Context" in extracted
    print("✓ test_extract_context_md")


def test_full_inference_finalize_cycle():
    """Full cycle: infer → parse unknowns → finalize → validate."""
    runner = BootstrapRunner()
    payload = create_minimal_payload()
    
    # Step 1: Infer
    result = runner.infer(
        payload,
        change_request="Add audit logging",
        use_mock=True,
    )
    
    assert len(result.unknown_entries) > 0
    draft = result.draft_context_md
    
    # Step 2: Collect answers for unknowns
    answers = {}
    for unknown in result.unknown_entries:
        if "business" in unknown.lower():
            answers[unknown] = "Internal payment processing for merchants"
        elif "sla" in unknown.lower() or "performance" in unknown.lower():
            answers[unknown] = "99.9% uptime, sub-50ms latency"
        elif "compliance" in unknown.lower():
            answers[unknown] = "PCI-DSS compliant"
        elif "domain" in unknown.lower():
            answers[unknown] = "Merchant = customer business, Gateway = payment processor"
        else:
            answers[unknown] = f"Answer to: {unknown}"
    
    # Step 3: Finalize
    final = runner.finalise(draft, answers)
    
    # Step 4: Validate
    runner._validate_context_md(final)  # Should not raise
    
    print("✓ test_full_inference_finalize_cycle")


if __name__ == "__main__":
    print("Running BootstrapRunner tests...\n")
    
    try:
        test_infer_with_mock()
        test_parse_unknown_entries()
        test_finalise_replaces_unknowns()
        test_finalise_rejects_partial_answers()
        test_validation_missing_sections()
        test_validation_unresolved_unknowns()
        test_change_log_creation()
        test_change_log_append()
        test_extract_context_md()
        test_full_inference_finalize_cycle()
        
        print("\n✅ All tests passed!")
    
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
