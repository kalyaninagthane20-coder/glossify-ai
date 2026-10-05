"""Translation memory (TM): every approved source/target pair, for reuse.

Lookup order:
  1. exact match (normalised source text + language pair, hashed)
  2. fuzzy match (difflib similarity ratio >= threshold), returned as a suggestion

Approved translations are written back here, so the system gets better with use.
The fuzzy scan is linear, which is fine for thousands of entries. For larger
memories, the vector index in app/rag is the place to add an approximate search.
"""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TMEntry


def normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def source_hash(text: str, source_lang: str, target_lang: str) -> str:
    key = f"{source_lang}|{target_lang}|{normalize(text)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TMMatch:
    entry_id: int
    source_text: str
    target_text: str
    score: float
    kind: str  # "exact" | "fuzzy"


class TranslationMemory:
    def __init__(self, session: Session, fuzzy_threshold: float = 0.75):
        self.session = session
        self.fuzzy_threshold = fuzzy_threshold

    def find(self, text: str, source_lang: str, target_lang: str) -> TMMatch | None:
        exact = self.session.scalar(
            select(TMEntry).where(TMEntry.source_hash == source_hash(text, source_lang, target_lang))
        )
        if exact is not None:
            return TMMatch(exact.id, exact.source_text, exact.target_text, 1.0, "exact")

        best: TMMatch | None = None
        needle = normalize(text)
        for entry in self._pair_entries(source_lang, target_lang):
            score = difflib.SequenceMatcher(None, needle, normalize(entry.source_text)).ratio()
            if score >= self.fuzzy_threshold and (best is None or score > best.score):
                best = TMMatch(entry.id, entry.source_text, entry.target_text, round(score, 3), "fuzzy")
        return best

    def search(self, query: str, source_lang: str, target_lang: str, limit: int = 5) -> list[TMMatch]:
        needle = normalize(query)
        scored = []
        for entry in self._pair_entries(source_lang, target_lang):
            score = difflib.SequenceMatcher(None, needle, normalize(entry.source_text)).ratio()
            kind = "exact" if normalize(entry.source_text) == needle else "fuzzy"
            scored.append(TMMatch(entry.id, entry.source_text, entry.target_text, round(score, 3), kind))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:limit]

    def learn(self, source_text: str, target_text: str, source_lang: str, target_lang: str,
              origin: str = "approved") -> TMEntry:
        """Store or update a pair. Called when a reviewer approves a segment."""
        digest = source_hash(source_text, source_lang, target_lang)
        entry = self.session.scalar(select(TMEntry).where(TMEntry.source_hash == digest))
        if entry is None:
            entry = TMEntry(source_lang=source_lang, target_lang=target_lang, source_text=source_text,
                            source_hash=digest, target_text=target_text, origin=origin)
            self.session.add(entry)
        else:
            entry.target_text = target_text
            entry.origin = origin
        self.session.flush()
        return entry

    def _pair_entries(self, source_lang: str, target_lang: str) -> list[TMEntry]:
        return list(self.session.scalars(
            select(TMEntry).where(TMEntry.source_lang == source_lang, TMEntry.target_lang == target_lang)
        ))
