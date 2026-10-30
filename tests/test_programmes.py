"""DR1 (30 Oct): programme routing - regulus.retrieval.programmes and its use in section promotion."""
import pytest

from regulus.retrieval.programmes import programme_for


@pytest.mark.parametrize("question,name", [
    ("What statutory provision governs premarket tobacco product applications?", "tobacco"),                   # T-001
    ("What must a Substantial Equivalence report contain and what is a valid predicate?", "tobacco"),          # T-005
    ("What harmful and potentially harmful constituent data must be submitted?", "tobacco"),                   # PB-002
    ("How must major food allergens be declared on a food label?", "food_labeling"),                           # L-010
    ("When must a food bear a common or usual name established by regulation?", "food_labeling"),              # L-015
    ("When must a 510(k) be submitted for a change to a legally marketed device?", "device_submissions"),      # P-003
    ("How are medical devices classified and what does a 513(g) request accomplish?", "device_submissions"),   # P-008
    ("What must an IDE application contain?", "device_submissions"),
    ("What are the MQSA requirements for mammography equipment?", "radiological_health"),
    ("How is the primary mode of action of a combination product determined?", "combination_products"),
])
def test_a_question_naming_one_programme_is_routed(question, name):
    assert programme_for(question).name == name


@pytest.mark.parametrize("question", [
    "How must net quantity of contents be declared?",                     # L-005: food, drug, device or cosmetic
    "What is the standard for substantial equivalence?",                 # P-002: 510(k) as well as tobacco
    "What must a PMA application contain under Part 814?",               # a named part decides
    "What steps must be taken to prevent allergens from cross-contact during food processing?",   # 117.80, not labeling
    "What is the principal display panel for over-the-counter drugs?",   # 201.60: shared words without "food"
    "Do OTC products claiming to help break a cigarette habit need an approved new drug application?",   # 310.544
    "What labeling requirements apply to human food by-products distributed as animal feed?",           # 507.28
    "Does a mammography facility need a 510(k) for its x-ray unit?",     # two programmes named
])
def test_no_programme_or_another_one_is_not_routed(question):
    assert programme_for(question) is None


def test_ends_and_pma_are_acronyms_only():
    assert programme_for("When the study ends, what records apply?") is None
    assert programme_for("Which tobacco products are ENDS?").name == "tobacco"


def test_routed_programme_is_off_unless_dr1(monkeypatch):
    from regulus.rag import section_promotion as SP
    from regulus.rag import validator_switches as VS

    q = "What must a premarket tobacco product application contain?"
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION - {"DR1"})
    assert SP.routed_programme(q) is None
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"DR1"})
    assert SP.routed_programme(q).name == "tobacco"
