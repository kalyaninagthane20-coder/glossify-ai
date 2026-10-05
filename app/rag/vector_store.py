"""Vector indexes used for retrieval-augmented prompting.

Both classes implement the same two methods (index / query), so the pipeline
does not depend on which one is in use.

* TfidfVectorStore: local, no API keys. Character n-grams make it robust to
  small wording changes, similar to fuzzy matching.
* PineconeVectorStore: production adapter. Embeddings come from a callable
  (e.g. OpenAI embeddings). It needs API keys, so the test suite does not exercise it.
"""
from __future__ import annotations

from typing import Callable, Protocol, Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class VectorStore(Protocol):
    def index(self, items: Sequence[tuple[str, str]]) -> None: ...

    def query(self, text: str, k: int) -> list[tuple[str, float]]: ...


class TfidfVectorStore:
    def __init__(self):
        self._ids: list[str] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None

    def index(self, items: Sequence[tuple[str, str]]) -> None:
        self._ids = [item_id for item_id, _ in items]
        texts = [text for _, text in items]
        if not texts:
            self._vectorizer, self._matrix = None, None
            return
        self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self._matrix = self._vectorizer.fit_transform(texts)

    def query(self, text: str, k: int) -> list[tuple[str, float]]:
        if self._matrix is None or self._vectorizer is None:
            return []
        scores = cosine_similarity(self._vectorizer.transform([text]), self._matrix).ravel()
        ranked = scores.argsort()[::-1][:k]
        return [(self._ids[i], float(scores[i])) for i in ranked if scores[i] > 0]


class PineconeVectorStore:
    """Adapter. Requires `pip install pinecone` and a valid API key."""

    def __init__(self, api_key: str, index_name: str, embed: Callable[[list[str]], list[list[float]]]):
        from pinecone import Pinecone  # imported lazily, so the rest of the app works without it

        self._index = Pinecone(api_key=api_key).Index(index_name)
        self._embed = embed

    def index(self, items: Sequence[tuple[str, str]]) -> None:
        if not items:
            return
        vectors = self._embed([text for _, text in items])
        self._index.upsert(vectors=[
            {"id": item_id, "values": vector, "metadata": {"text": text}}
            for (item_id, text), vector in zip(items, vectors)
        ])

    def query(self, text: str, k: int) -> list[tuple[str, float]]:
        vector = self._embed([text])[0]
        response = self._index.query(vector=vector, top_k=k, include_metadata=True)
        return [(match.id, float(match.score)) for match in response.matches]
