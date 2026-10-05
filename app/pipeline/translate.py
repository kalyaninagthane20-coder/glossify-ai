"""The translation pipeline: decides how each segment gets its draft translation.

For every segment, in order:
  1. Translation memory, exact match      -> reuse (score 1.0)
  2. Translation memory, fuzzy match      -> reuse as a suggestion (score = similarity)
  3. Otherwise: RAG. Retrieve similar approved pairs from the vector index, add the
     glossary terms that occur in the segment, and ask the translator (LLM).
Then, for every path, the glossary and style QA checks run. Any issue sends the
segment to "needs_review"; otherwise it becomes "draft". A human still approves.

Segments a reviewer has already approved are never overwritten.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.glossary.glossary import Glossary, check_translation
from app.memory.translation_memory import TranslationMemory
from app.models import Document, TMEntry
from app.rag.translators import Translator
from app.rag.vector_store import TfidfVectorStore


@dataclass
class TranslationReport:
    document_id: int
    translated: int = 0
    skipped_approved: int = 0
    flagged: int = 0
    by_method: dict[str, int] = field(default_factory=dict)


class TranslationPipeline:
    def __init__(self, session: Session, translator: Translator, *, fuzzy_threshold: float = 0.75,
                 retrieval_k: int = 3, vector_store_factory=TfidfVectorStore):
        self.session = session
        self.translator = translator
        self.fuzzy_threshold = fuzzy_threshold
        self.retrieval_k = retrieval_k
        self.vector_store_factory = vector_store_factory

    def run(self, document: Document) -> TranslationReport:
        src, tgt = document.source_lang, document.target_lang
        memory = TranslationMemory(self.session, self.fuzzy_threshold)
        glossary = Glossary(self.session)

        entries = list(self.session.scalars(
            select(TMEntry).where(TMEntry.source_lang == src, TMEntry.target_lang == tgt)))
        entries_by_key = {f"tm:{entry.id}": entry for entry in entries}
        store = self.vector_store_factory()
        store.index([(key, entry.source_text) for key, entry in entries_by_key.items()])

        report = TranslationReport(document_id=document.id)
        for segment in document.segments:
            if segment.status == "approved":
                report.skipped_approved += 1
                continue

            rules = glossary.applicable(segment.source_text, src, tgt)
            hit = memory.find(segment.source_text, src, tgt)
            if hit is not None:
                target = hit.target_text
                method = "tm_exact" if hit.kind == "exact" else "tm_fuzzy"
                score = hit.score
            else:
                examples = [
                    (entries_by_key[key].source_text, entries_by_key[key].target_text)
                    for key, _ in store.query(segment.source_text, self.retrieval_k)
                    if key in entries_by_key
                ]
                hints = [(r.source_term, r.target_term) for r in rules if r.kind == "term" and r.target_term]
                target = self.translator.translate(segment.source_text, src, tgt, hints, examples)
                method, score = self.translator.name, None

            issues = check_translation(segment.source_text, target, rules)
            segment.target_text = target
            segment.method = method
            segment.score = score
            segment.qa_issues = json.dumps(issues, ensure_ascii=False)
            segment.status = "needs_review" if issues else "draft"

            report.translated += 1
            report.by_method[method] = report.by_method.get(method, 0) + 1
            if issues:
                report.flagged += 1

        self.session.commit()
        return report
