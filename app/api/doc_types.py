from fastapi import APIRouter

from app.services.doc_types import doc_type_choices

router = APIRouter(prefix="/doc-types", tags=["doc-types"])


@router.get("")
def list_doc_types() -> list[dict[str, str]]:
    return doc_type_choices()
