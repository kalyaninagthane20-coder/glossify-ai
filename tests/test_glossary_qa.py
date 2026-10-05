from app.glossary.glossary import Glossary, check_translation, contains_term


def test_term_rule_flags_missing_preferred_translation(session):
    glossary = Glossary(session)
    glossary.add("en", "fr", "term", "invoice", "facture")
    rules = glossary.applicable("Please send the invoice.", "en", "fr")
    issues = check_translation("Please send the invoice.", "Veuillez envoyer la note.", rules)
    assert any("should be translated as 'facture'" in issue for issue in issues)


def test_term_rule_passes_when_preferred_translation_is_used(session):
    glossary = Glossary(session)
    glossary.add("en", "fr", "term", "invoice", "facture")
    rules = glossary.applicable("Please send the invoice.", "en", "fr")
    assert check_translation("Please send the invoice.", "Veuillez envoyer la facture.", rules) == []


def test_avoid_rule_flags_forbidden_wording(session):
    glossary = Glossary(session)
    glossary.add("en", "fr", "avoid", "customer", "client", note="use 'utilisateur' in product UI")
    rules = glossary.applicable("The customer logged in.", "en", "fr")
    issues = check_translation("The customer logged in.", "Le client s'est connecté.", rules)
    assert any(issue.startswith("Style:") for issue in issues)


def test_missing_numbers_are_flagged():
    issues = check_translation("Pay 250 euros by 12/05.", "Payez des euros avant le 12/05.", [])
    assert issues == ["Number '250' from the source is missing from the translation."]


def test_whole_word_matching_avoids_partial_hits():
    assert contains_term("The cat sat.", "cat")
    assert not contains_term("Category list", "cat")
    assert contains_term("INVOICE #4", "invoice")  # case-insensitive


def test_adding_the_same_rule_twice_updates_it(session):
    glossary = Glossary(session)
    first = glossary.add("en", "fr", "term", "invoice", "facture")
    second = glossary.add("en", "fr", "term", "invoice", "note de frais")
    assert first.id == second.id
    assert second.target_term == "note de frais"


def test_invalid_rule_kind_is_rejected(session):
    try:
        Glossary(session).add("en", "fr", "banana", "x", "y")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown kind")
