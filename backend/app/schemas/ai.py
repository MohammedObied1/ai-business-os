from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AskRequest(BaseModel):
    question: str
    history: list[dict] = []
    lang: str | None = None  # "ar" / "en"; detected from the question when omitted


class AskResponse(BaseModel):
    answer: str
    tools_used: list[str]
    data: dict | None = None
    grounded_on_documents: list[str] = []


class InsightItem(BaseModel):
    kind: str  # risk / positive / info
    title: str
    detail: str
    metric: float | None = None
    action: str | None = None


class CommandCenterOut(BaseModel):
    summary: str
    health: str  # healthy / attention / critical
    signals: list[InsightItem]
    recommended_actions: list[str]
    generated_at: datetime


class DocumentOut(ORMModel):
    id: int
    title: str
    doc_type: str
    filename: str | None = None
    status: str
    chunk_count: int
    created_at: datetime


class DocumentTextIn(BaseModel):
    title: str
    doc_type: str = "policy"
    content: str


class SearchHit(BaseModel):
    document_id: int
    document_title: str
    content: str
    score: float
