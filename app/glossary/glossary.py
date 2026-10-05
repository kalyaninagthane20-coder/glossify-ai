"""Terminology and style enforcement (glossary + quality checks).

Glossary matching is deterministic: whole-word, case-insensitive regex. Terminology
must be exact, so semantic search is not used here. The vector index is only used
to find similar past sentences as examples for the LLM.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GlossaryTerm

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def contains_term(text: str, term: str) -> bool:
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


class Glossary:
    def __init__(self, session: Session):
        self.session = session

    def add(self, source_lang: str, target_lang: str, kind: str, source_term: str,
            target_term: str | None, note: str | None = None) -> GlossaryTerm:
        if kind not in ("term", "avoid"):
            raise ValueError("kind must be 'term' or 'avoid'")
        existing = self.session.scalar(select(GlossaryTerm).where(
            GlossaryTerm.source_lang == source_lang, GlossaryTerm.target_lang == target_lang,
            GlossaryTerm.kind == kind, GlossaryTerm.source_term == source_term))
        if existing is not None:
            existing.target_term, existing.note = target_term, note
            self.session.flush()
            return existing
        row = GlossaryTerm(source_lang=source_lang, target_lang=target_lang, kind=kind,
                           source_term=source_term, target_term=target_term, note=note)
        self.session.add(row)
        self.session.flush()
        return row

    def list(self, source_lang: str | None = None, target_lang: str | None = None) -> list[GlossaryTerm]:
        query = select(GlossaryTerm).order_by(GlossaryTerm.source_term)
        if source_lang:
            query = query.where(GlossaryTerm.source_lang == source_lang)
        if target_lang:
            query = query.where(GlossaryTerm.target_lang == target_lang)
        return list(self.session.scalars(query))

    def delete(self, term_id: int) -> bool:
        row = self.session.get(GlossaryTerm, term_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def applicable(self, source_text: str, source_lang: str, target_lang: str) -> list[GlossaryTerm]:
        """Rules whose source term occurs in this segment."""
        rules = self.session.scalars(select(GlossaryTerm).where(
            GlossaryTerm.source_lang == source_lang, GlossaryTerm.target_lang == target_lang))
        return [rule for rule in rules if contains_term(source_text, rule.source_term)]


def check_translation(source_text: str, target_text: str, rules: list[GlossaryTerm]) -> list[str]:
    """Return human-readable QA issues. An empty list means no problems were found."""
    issues: list[str] = []
    for rule in rules:
        if not rule.target_term:
            continue
        if rule.kind == "term" and not contains_term(target_text, rule.target_term):
            issues.append(f"Glossary: '{rule.source_term}' should be translated as '{rule.target_term}'.")
        if rule.kind == "avoid" and contains_term(target_text, rule.target_term):
            issues.append(f"Style: avoid '{rule.target_term}' when the source says '{rule.source_term}'.")
    for number in sorted(set(NUMBER.findall(source_text))):
        if number not in target_text:
            issues.append(f"Number '{number}' from the source is missing from the translation.")
    return issues
