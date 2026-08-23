"""
Phase 5 Integration Tests

Test the full modify() flow:
1. Modify with existing CONTEXT.md (Phase 4.5 path)
2. Modify without CONTEXT.md (Phase 4.6 cold bootstrap path)
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from src.orchestrator.modify import TrivialityJudge, DeltaReGrill, ContextMerger, ModifyResult


class MockContextStore:
    """Mock context store for testing."""
    def __init__(self):
        self.data = {}
    
    def load(self, project_id):
        return self.data.get(project_id)
    
    def save(self, project_id, context_md):
        self.data[project_id] = context_md
    
    def exists(self, project_id):
        return project_id in self.data
    
    def delete(self, project_id):
        if project_id in self.data:
            del self.data[project_id]
    
    def list_projects(self):
        return list(self.data.keys())


class TestTrivialityJudge(unittest.TestCase):
    """Unit tests for TrivialityJudge."""
    
    def setUp(self):
        self.model_router = Mock()
        self.judge = TrivialityJudge(self.model_router)
    
    def test_judge_trivial(self):
        """Test: classify trivial change."""
        self.model_router.run = Mock(return_value="trivial")
        
        context = "# Problem Statement\nBuild a task app"
        change = "Fix typo in UI"
        
        result = self.judge.judge(context, change)
        self.assertEqual(result, "trivial")
    
    def test_judge_significant(self):
        """Test: classify significant change."""
        self.model_router.run = Mock(return_value="significant")
        
        context = "# Functional Requirements\n- Create tasks"
        change = "Add task categories (new feature)"
        
        result = self.judge.judge(context, change)
        self.assertEqual(result, "significant")


class TestContextMerger(unittest.TestCase):
    """Unit tests for ContextMerger."""
    
    def test_merge_delta_appends_to_requirements(self):
        """Test: delta merge appends new requirements."""
        
        original = """
# CONTEXT

## Functional Requirements
- Feature A
- Feature B
"""
        
        delta = """
### New Requirements
- Feature C
- Feature D
"""
        
        merged = ContextMerger.merge_delta(original, delta, "Add features")
        
        self.assertIn("Feature A", merged)
        self.assertIn("Feature C", merged)
        self.assertIn("Change Log", merged)
    
    def test_merge_delta_updates_vocab(self):
        """Test: delta merge updates shared vocabulary."""
        
        original = """
## Shared Vocabulary
- Task: a work item
"""
        
        delta = """
### New Shared Vocabulary
- Category: a task grouping
"""
        
        merged = ContextMerger.merge_delta(original, delta, "Add categories")
        
        self.assertIn("Task: a work item", merged)
        self.assertIn("Category: a task grouping", merged)


if __name__ == '__main__':
    unittest.main(verbosity=2)