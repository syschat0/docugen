from typing import Any, Dict

from pydantic import BaseModel, Field


class PendingQuestionCreate(BaseModel):
    phase: str = Field(min_length=1, max_length=100)
    question: Dict[str, Any] = Field(default_factory=dict)


class PendingQuestionRead(BaseModel):
    id: str
    project_id: str
    phase: str
    question: Dict[str, Any]
    status: str
    created_at: str
    answered_at: str | None
    answer: str | None = None
    applies_to: Dict[str, Any] | None = None


class QuestionAnswerCreate(BaseModel):
    answer: str = Field(min_length=1)
    applies_to: Dict[str, Any] | None = None


class SectionFeedbackCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class UserDecisionRead(BaseModel):
    id: str
    project_id: str
    phase: str
    question_id: str | None
    question: str
    answer: str
    applies_to: Dict[str, Any] | None
    created_at: str


class SectionFeedbackRead(UserDecisionRead):
    applied: bool = False
