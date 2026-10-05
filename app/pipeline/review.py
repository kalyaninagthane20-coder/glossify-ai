"""Human review workflow and continuous learning.

Segment states:
    draft / needs_review  --edit-->  in_review
    any state             --approve-->  approved   (the pair is written to translation memory)
    any state             --reject-->   rejected   (with a comment, for the translator)

Approval is what feeds the translation memory, so each reviewed document makes
future translations of similar text better.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.glossary.glossary import Glossary, check_translation
from app.memory.translation_memory import TranslationMemory
from app.models import Segment


class ReviewError(ValueError):
    pass


class ReviewService:
    def __init__(self, session: Session):
        self.session = session

    def edit(self, segment: Segment, target_text: str, comment: str | None = None) -> Segment:
        document = segment.document
        rules = Glossary(self.session).applicable(segment.source_text, document.source_lang, document.target_lang)
        segment.target_text = target_text.strip()
        segment.method = "manual"
        segment.score = None
        segment.qa_issues = json.dumps(
            check_translation(segment.source_text, segment.target_text, rules), ensure_ascii=False)
        segment.status = "in_review"
        if comment is not None:
            segment.reviewer_comment = comment
        self.session.commit()
        return segment

    def approve(self, segment: Segment) -> Segment:
        target = segment.target_text.strip()
        if not target:
            raise ReviewError("An empty translation cannot be approved.")
        document = segment.document
        # A copied source (e.g. offline mode) is not a translation, so it is not learned.
        if target != segment.source_text.strip():
            TranslationMemory(self.session, fuzzy_threshold=1.0).learn(
                segment.source_text, target, document.source_lang, document.target_lang, origin="approved")
        segment.status = "approved"
        self.session.commit()
        return segment

    def reject(self, segment: Segment, comment: str | None) -> Segment:
        segment.status = "rejected"
        segment.reviewer_comment = comment
        self.session.commit()
        return segment
