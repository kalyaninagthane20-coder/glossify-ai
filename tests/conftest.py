import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import init_db, make_engine, make_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402


class UpperTranslator:
    """Deterministic stand-in for the LLM: upper-cases the text, so tests know the exact output."""
    name = "upper"

    def __init__(self):
        self.calls = []

    def translate(self, text, source_lang, target_lang, glossary_hints, examples):
        self.calls.append({"text": text, "hints": list(glossary_hints), "examples": list(examples)})
        return text.upper()


def make_settings(**overrides) -> Settings:
    base = dict(database_url="sqlite://", openai_api_key=None, pinecone_api_key=None,
                pinecone_index=None, fuzzy_threshold=0.75, retrieval_k=3)
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def translator():
    return UpperTranslator()


@pytest.fixture
def client(translator):
    app = create_app(make_settings(), translator=translator)
    with TestClient(app) as c:
        yield c
