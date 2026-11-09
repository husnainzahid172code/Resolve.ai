"""Request/response schemas for the HTTP API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ComplaintCreate(BaseModel):
    message: str = Field(min_length=2, max_length=4000)


class MessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class LoginRequest(BaseModel):
    username: str
    password: str


class ApproveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000, description="Internal administrator note")
    customer_response: str | None = Field(default=None, max_length=4000,
                                          description="Optional edited final response to the customer")


class RejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000, description="Required rejection reason (shown to customer)")
    note: str | None = Field(default=None, max_length=2000)


class RequestInfoRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class CustomerCaseView(BaseModel):
    case_id: str
    status: str
    messages: list[dict[str, Any]]
    awaiting: str | None
    final_response: str | None
    evidence_count: int
    runtime: dict[str, Any]
