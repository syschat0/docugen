from typing import List

from fastapi import APIRouter, HTTPException, Query

from app.db.repositories import (
    QuestionAlreadyAnsweredError,
    UnknownSectionError,
    add_section_feedback,
    answer_pending_question,
    create_pending_question,
    delete_question_answer,
    get_pending_question,
    get_project,
    list_pending_questions,
    list_section_feedback,
    update_question_answer,
)
from app.schemas.questions import (
    PendingQuestionCreate,
    PendingQuestionRead,
    QuestionAnswerCreate,
    SectionFeedbackCreate,
    SectionFeedbackRead,
    UserDecisionRead,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["questions"])


def _ensure_project(project_id: str) -> None:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/questions", response_model=PendingQuestionRead, status_code=201)
def create_pending_question_endpoint(
    project_id: str, payload: PendingQuestionCreate
) -> PendingQuestionRead:
    _ensure_project(project_id)
    return create_pending_question(project_id, payload)


@router.get("/questions", response_model=List[PendingQuestionRead])
def list_pending_questions_endpoint(
    project_id: str, status: str | None = Query(default=None)
) -> List[PendingQuestionRead]:
    _ensure_project(project_id)
    return list_pending_questions(project_id, status=status)


@router.get("/questions/{question_id}", response_model=PendingQuestionRead)
def get_pending_question_endpoint(project_id: str, question_id: str) -> PendingQuestionRead:
    _ensure_project(project_id)
    question = get_pending_question(project_id, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


@router.post("/questions/{question_id}/answer", response_model=UserDecisionRead)
def answer_pending_question_endpoint(
    project_id: str, question_id: str, payload: QuestionAnswerCreate
) -> UserDecisionRead:
    _ensure_project(project_id)
    try:
        decision = answer_pending_question(project_id, question_id, payload)
    except QuestionAlreadyAnsweredError:
        raise HTTPException(status_code=409, detail="Question already answered")

    if decision is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return decision


@router.put("/questions/{question_id}/answer", response_model=UserDecisionRead)
def update_question_answer_endpoint(
    project_id: str, question_id: str, payload: QuestionAnswerCreate
) -> UserDecisionRead:
    _ensure_project(project_id)
    decision = update_question_answer(project_id, question_id, payload)
    if decision is None:
        raise HTTPException(status_code=404, detail="Answered question not found")
    return decision


@router.post(
    "/sections/{section_id}/feedback",
    response_model=UserDecisionRead,
    status_code=201,
)
def add_section_feedback_endpoint(
    project_id: str, section_id: str, payload: SectionFeedbackCreate
) -> UserDecisionRead:
    _ensure_project(project_id)
    try:
        decision = add_section_feedback(project_id, section_id, payload.comment)
    except UnknownSectionError:
        raise HTTPException(
            status_code=404,
            detail="No section draft exists for this section id yet",
        )
    if decision is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return decision


@router.get(
    "/sections/{section_id}/feedback",
    response_model=List[SectionFeedbackRead],
)
def list_section_feedback_endpoint(
    project_id: str, section_id: str
) -> List[SectionFeedbackRead]:
    _ensure_project(project_id)
    return list_section_feedback(project_id, section_id) or []


@router.delete("/questions/{question_id}/answer", status_code=204)
def delete_question_answer_endpoint(project_id: str, question_id: str):
    _ensure_project(project_id)
    if not delete_question_answer(project_id, question_id):
        raise HTTPException(status_code=404, detail="Answered question not found")
    return None
