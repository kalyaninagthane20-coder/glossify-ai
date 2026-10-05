from app.glossary.glossary import Glossary
from app.memory.translation_memory import TranslationMemory
from app.models import Document, Segment
from app.pipeline.review import ReviewError, ReviewService
from app.pipeline.translate import TranslationPipeline


class RecordingTranslator:
    name = "fake-llm"

    def __init__(self):
        self.calls = []

    def translate(self, text, source_lang, target_lang, glossary_hints, examples):
        self.calls.append({"text": text, "hints": list(glossary_hints), "examples": list(examples)})
        return f"[FR] {text}"


def make_document(session, sentences, source="en", target="fr"):
    document = Document(filename="contract.txt", source_lang=source, target_lang=target)
    document.segments = [Segment(position=i, block_type="paragraph", source_text=s, target_text="",
                                 status="pending") for i, s in enumerate(sentences)]
    session.add(document)
    session.commit()
    return document


def test_pipeline_uses_memory_then_llm_and_flags_glossary_violations(session):
    TranslationMemory(session).learn("Good morning", "Bonjour", "en", "fr")
    Glossary(session).add("en", "fr", "term", "invoice", "facture")
    document = make_document(session, ["Good morning", "Please send the invoice 42", "Thank you"])
    translator = RecordingTranslator()

    report = TranslationPipeline(session, translator).run(document)

    by_position = {s.position: s for s in document.segments}
    assert by_position[0].method == "tm_exact" and by_position[0].target_text == "Bonjour"
    assert by_position[0].status == "draft"

    flagged = by_position[1]
    assert flagged.method == "fake-llm"
    assert flagged.status == "needs_review"
    assert "facture" in flagged.qa_issues

    assert by_position[2].status == "draft"
    assert report.translated == 3
    assert report.flagged == 1
    assert report.by_method == {"tm_exact": 1, "fake-llm": 2}

    # the LLM was told the glossary term it must use
    assert len(translator.calls) == 2
    assert ("invoice", "facture") in translator.calls[0]["hints"]


def test_retrieved_memory_examples_are_passed_to_the_llm(session):
    TranslationMemory(session).learn("Send the invoice tomorrow", "Envoyez la facture demain", "en", "fr")
    document = make_document(session, ["Send the invoice today"])
    translator = RecordingTranslator()

    # threshold 0.99 so the near-match is not reused directly and the RAG path runs
    TranslationPipeline(session, translator, fuzzy_threshold=0.99).run(document)

    examples = translator.calls[0]["examples"]
    assert ("Send the invoice tomorrow", "Envoyez la facture demain") in examples


def test_approved_segments_are_never_overwritten(session):
    document = make_document(session, ["Keep me", "Translate me"])
    document.segments[0].status = "approved"
    document.segments[0].target_text = "Gardez-moi"
    session.commit()

    report = TranslationPipeline(session, RecordingTranslator()).run(document)

    assert document.segments[0].target_text == "Gardez-moi"
    assert report.skipped_approved == 1
    assert report.translated == 1


def test_review_edit_clears_issues_and_approval_teaches_the_memory(session):
    Glossary(session).add("en", "fr", "term", "invoice", "facture")
    document = make_document(session, ["Please send the invoice 42"])
    TranslationPipeline(session, RecordingTranslator()).run(document)
    segment = document.segments[0]
    assert segment.status == "needs_review"

    review = ReviewService(session)
    review.edit(segment, "Veuillez envoyer la facture 42", comment="fixed terminology")
    assert segment.status == "in_review"
    assert segment.qa_issues == "[]"
    assert segment.method == "manual"

    review.approve(segment)
    assert segment.status == "approved"
    learned = TranslationMemory(session).find("Please send the invoice 42", "en", "fr")
    assert learned is not None and learned.target_text == "Veuillez envoyer la facture 42"


def test_copied_source_is_not_learned_as_a_translation(session):
    document = make_document(session, ["Same text"])
    segment = document.segments[0]
    segment.target_text = "Same text"
    session.commit()

    ReviewService(session).approve(segment)

    assert TranslationMemory(session).find("Same text", "en", "fr") is None


def test_empty_translation_cannot_be_approved(session):
    document = make_document(session, ["Something"])
    segment = document.segments[0]
    segment.target_text = "   "
    session.commit()
    try:
        ReviewService(session).approve(segment)
    except ReviewError:
        return
    raise AssertionError("expected ReviewError")
