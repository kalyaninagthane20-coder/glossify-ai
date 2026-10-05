"""Runtime settings, read from environment variables when a Settings object is created."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./glossify.db"))
    # LLM: if no key is set, the offline translator is used (no real translation, for testing the workflow).
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    # Pinecone is optional. Without it, the in-process TF-IDF index is used.
    pinecone_api_key: str | None = field(default_factory=lambda: os.getenv("PINECONE_API_KEY") or None)
    pinecone_index: str | None = field(default_factory=lambda: os.getenv("PINECONE_INDEX") or None)
    # Minimum similarity (0-1) for a fuzzy translation-memory match to be reused as a suggestion.
    fuzzy_threshold: float = field(default_factory=lambda: float(os.getenv("FUZZY_THRESHOLD", "0.75")))
    # How many similar past translations to show the LLM as examples.
    retrieval_k: int = field(default_factory=lambda: int(os.getenv("RETRIEVAL_K", "3")))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024)
