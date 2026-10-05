"""Request and response shapes for the HTTP API (Pydantic v2)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    block_type: str
    heading_level: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    col_index: int | None = None
    page: int | None = None
    source_text: str
    target_text: str
    status: str
    method: str | None = None
    score: float | None = None
    qa_issues: list[str] = []
    reviewer_comment: str | None = None

    @field_validator("qa_issues", mode="before")
    @classmethod
    def _decode_json(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    source_lang: str
    target_lang: str
    created_at: datetime
    segment_count: int


class DocumentOut(DocumentSummary):
    segments: list[SegmentOut]


class SegmentEdit(BaseModel):
    target_text: str = Field(max_length=20000)
    comment: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class GlossaryIn(BaseModel):
    kind: Literal["term", "avoid"] = "term"
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    source_term: str = Field(min_length=1, max_length=200)
    target_term: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class GlossaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    source_lang: str
    target_lang: str
    source_term: str
    target_term: str | None = None
    note: str | None = None


class TMMatchOut(BaseModel):
    entry_id: int
    source_text: str
    target_text: str
    score: float
    kind: str


class TranslationReportOut(BaseModel):
    document_id: int
    translated: int
    skipped_approved: int
    flagged: int
    by_method: dict[str, int]
