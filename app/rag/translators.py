"""Translator adapters: the component that produces a draft translation.

The pipeline depends only on the `translate` method, so tests use a fake, and the
OpenAI model can be replaced without touching the pipeline.
"""
from __future__ import annotations

from typing import Protocol, Sequence


class Translator(Protocol):
    name: str

    def translate(self, text: str, source_lang: str, target_lang: str,
                  glossary_hints: Sequence[tuple[str, str]],
                  examples: Sequence[tuple[str, str]]) -> str: ...


def build_messages(text: str, source_lang: str, target_lang: str,
                   glossary_hints: Sequence[tuple[str, str]],
                   examples: Sequence[tuple[str, str]]) -> list[dict]:
    """Prompt with the rules (system), the retrieved context, and the text to translate."""
    system = (
        f"You are a professional translator from {source_lang} to {target_lang}. "
        "Keep numbers, placeholders, and punctuation unchanged. "
        "Use the glossary terms exactly as given. Return only the translation, with no commentary."
    )
    parts = []
    if glossary_hints:
        parts.append("Glossary (must be used):\n" + "\n".join(f"- {s} -> {t}" for s, t in glossary_hints))
    if examples:
        parts.append("Previously approved translations for similar text:\n" +
                     "\n".join(f"{s}\n=> {t}" for s, t in examples))
    parts.append(f"Translate this text:\n{text}")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


class OpenAITranslator:
    name = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI  # lazy import

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def translate(self, text, source_lang, target_lang, glossary_hints, examples) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=build_messages(text, source_lang, target_lang, glossary_hints, examples),
        )
        return (response.choices[0].message.content or "").strip()


class OfflineTranslator:
    """No model is called and the text is copied unchanged.

    Used when no API key is configured and in tests. The output is NOT a translation.
    It exists so the rest of the workflow (matching, QA, review, export) can run end to end.
    """
    name = "offline"

    def translate(self, text, source_lang, target_lang, glossary_hints, examples) -> str:
        return text
