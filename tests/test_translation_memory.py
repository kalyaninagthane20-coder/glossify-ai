from app.memory.translation_memory import TranslationMemory, normalize, source_hash


def test_exact_match_ignores_case_and_extra_spaces(session):
    memory = TranslationMemory(session)
    memory.learn("Good morning", "Bonjour", "en", "fr")
    match = memory.find("  good    MORNING ", "en", "fr")
    assert match is not None
    assert match.kind == "exact"
    assert match.target_text == "Bonjour"
    assert match.score == 1.0


def test_fuzzy_match_above_threshold_is_returned_as_suggestion(session):
    memory = TranslationMemory(session, fuzzy_threshold=0.75)
    memory.learn("The meeting starts at nine o'clock.", "La réunion commence à neuf heures.", "en", "fr")
    match = memory.find("The meeting starts at nine oclock.", "en", "fr")
    assert match is not None
    assert match.kind == "fuzzy"
    assert 0.75 <= match.score < 1.0


def test_unrelated_text_has_no_match(session):
    memory = TranslationMemory(session)
    memory.learn("Good morning", "Bonjour", "en", "fr")
    assert memory.find("Quarterly revenue grew by twelve percent", "en", "fr") is None


def test_language_pairs_are_isolated(session):
    memory = TranslationMemory(session)
    memory.learn("Good morning", "Bonjour", "en", "fr")
    assert memory.find("Good morning", "en", "de") is None


def test_learning_the_same_source_updates_the_entry(session):
    memory = TranslationMemory(session)
    first = memory.learn("Save changes", "Enregistrer", "en", "fr")
    second = memory.learn("save changes", "Sauvegarder", "en", "fr")
    assert first.id == second.id
    assert memory.find("Save changes", "en", "fr").target_text == "Sauvegarder"


def test_search_orders_results_by_similarity(session):
    memory = TranslationMemory(session)
    memory.learn("Pay the invoice today", "Payez la facture aujourd'hui", "en", "fr")
    memory.learn("Weather is nice", "Il fait beau", "en", "fr")
    results = memory.search("Pay the invoice", "en", "fr", limit=2)
    assert results[0].source_text == "Pay the invoice today"
    assert results[0].score >= results[1].score


def test_normalisation_and_hash_are_stable():
    assert normalize("  Hello   World ") == "hello world"
    assert source_hash("Hello", "en", "fr") == source_hash("hello  ", "en", "fr")
    assert source_hash("Hello", "en", "fr") != source_hash("Hello", "en", "de")
