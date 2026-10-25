from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AssessmentRecord:
    turn: int
    topic: str
    score: float
    note: str


@dataclass
class InterviewState:
    recruiter_history: list[dict] = field(default_factory=list)
    candidate_history: list[dict] = field(default_factory=list)
    full_trajectory: list[dict] = field(default_factory=list)
    assessment_log: list[AssessmentRecord] = field(default_factory=list)
    turn_count: int = 0
    terminated: bool = False
    termination_reason: str = ""
