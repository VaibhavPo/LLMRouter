import os
import re

# Mapping of old module names/paths to new module paths
# e.g., 'from llm_router.router import ...' -> 'from src.core.router import ...'
replacements = [
    (r'from llm_router\.router import', r'from src.core.router import'),
    (r'import llm_router\.router', r'import src.core.router'),
    (r'from llm_router\.models import', r'from src.core.models import'),
    (r'import llm_router\.models', r'import src.core.models'),
    (r'from llm_gateway\.gateway import', r'from src.core.gateway import'),
    (r'import llm_gateway\.gateway', r'import src.core.gateway'),
    (r'from context_store import', r'from src.context.context_store import'),
    (r'import context_store', r'import src.context.context_store'),
    (r'from orchestrator import', r'from src.orchestrator.orchestrator import'),
    (r'import orchestrator', r'import src.orchestrator.orchestrator'),
    (r'from skills\.grilling_runner import', r'from src.orchestrator.grilling import'),
    (r'import skills\.grilling_runner', r'import src.orchestrator.grilling'),
    (r'from change_classifier import', r'from src.orchestrator.triviality_judge import'),
    (r'import change_classifier', r'import src.orchestrator.triviality_judge'),
    (r'from context_merge import', r'from src.orchestrator.modify import'),
    (r'import context_merge', r'import src.orchestrator.modify'),
    (r'from codebase_reader import', r'from src.bootstrap.codebase_reader import'),
    (r'import codebase_reader', r'import src.bootstrap.codebase_reader'),
    (r'from bootstrap_runner import', r'from src.bootstrap.bootstrap_runner import'),
    (r'import bootstrap_runner', r'import src.bootstrap.bootstrap_runner'),
    (r'from bootstrap_interviewer import', r'from src.bootstrap.bootstrap_interviewer import'),
    (r'import bootstrap_interviewer', r'import src.bootstrap.bootstrap_interviewer'),
    (r'from skills\.skill_runner import', r'from src.skills.skill_loader import'),
    (r'import skills\.skill_runner', r'import src.skills.skill_loader'),
    # Generic module references
    (r'from llm_router import', r'from src.core import'),
    (r'from llm_gateway import', r'from src.core import'),
]

directories = ['src', 'tests']

for directory in directories:
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                original_content = content
                for old, new in replacements:
                    content = re.sub(old, new, content)
                
                # Check for "import X" forms that might be missed
                # Replace top-level imports that might have been absolute
                # Note: this requires care, let's keep it simple first
                
                if content != original_content:
                    print(f"Updated {path}")
                    with open(path, 'w', encoding='utf-8') as file:
                        file.write(content)
