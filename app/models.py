"""ORM models.

Document -> Segment: a document is split into ordered blocks (headings, paragraphs,
list items, table cells). Each block is translated, reviewed and exported on its own.

TMEntry: translation memory, every approved source/target pair.
GlossaryTerm: terminology rules ("term") and style rules ("avoid").
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    segments: Mapped[list["Segment"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Segment.position"
    )


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)

    # structure, kept so the export can rebuild headings, lists and tables
    block_type: Mapped[str] = mapped_column(String(20))  # heading | paragraph | list_item | table_cell
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_text: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text, default="")
    # pending | draft | needs_review | in_review | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # tm_exact | tm_fuzzy | <translator name> | manual
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qa_issues: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of strings
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[Document] = relationship(back_populates="segments")


class TMEntry(Base):
    __tablename__ = "tm_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_lang: Mapped[str] = mapped_column(String(16), index=True)
    target_lang: Mapped[str] = mapped_column(String(16), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64), unique=True)
    target_text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(20), default="approved")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_lang: Mapped[str] = mapped_column(String(16), index=True)
    target_lang: Mapped[str] = mapped_column(String(16), index=True)
    # "term": when source_term appears, target_term must appear.
    # "avoid": when source_term appears, target_term must NOT appear (style rule).
    kind: Mapped[str] = mapped_column(String(10), default="term")
    source_term: Mapped[str] = mapped_column(String(200))
    target_term: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
