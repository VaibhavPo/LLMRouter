# ------ start of schema.py
from enum import Enum
from pydantic import BaseModel
from .router import TaskType  # wherever TaskType actually lives

class SkillType(str, Enum):
    TDD = "tdd"
    DIAGNOSIS = "diagnosis"
    PLANNING = "planning"
    CODE_REVIEW = "code_review"
    DOMAIN_MODELING = "domain_modeling"
    UNKNOWN = "unknown"

class Classification(BaseModel):
    task_type: TaskType
    skill_name: SkillType = SkillType.UNKNOWN
    complexity: str
    requires_vision: bool
    requires_reasoning: bool