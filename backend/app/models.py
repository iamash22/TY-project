from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class CreateSessionResponse(BaseModel):
    id: str


class ChatMessage(BaseModel):
    id: str
    session_id: str
    user_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ListMessagesResponse(BaseModel):
    messages: list[ChatMessage]


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class PostMessageResponse(BaseModel):
    assistant_message: ChatMessage
    matched_service_ids: list[str] = Field(default_factory=list)


class SubmitSurveyRequest(BaseModel):
    answers: dict[str, Any]


class RecommendationRow(BaseModel):
    service_id: str
    score: float
    reason: str


class SubmitSurveyResponse(BaseModel):
    recommendations: list[RecommendationRow]


class ParsedIntent(BaseModel):
    query: str
    city: Optional[str] = None
    category: Optional[str] = None
    budget: Optional[str] = None
    urgency: Optional[str] = None
    constraints: list[str] = Field(default_factory=list)

