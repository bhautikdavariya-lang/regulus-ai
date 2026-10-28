from types import SimpleNamespace

from regulus.rag import validator_switches
from regulus.rag.fallback import focused_quote
from regulus.retrieval.evidence import TIER_EXACT


def _package(n):
    sources = [SimpleNamespace(is_docket=False, tier=TIER_EXACT, requirement_ids=("r1",), corpus="ecfr", index=i,
                               citation=f"21 CFR 201.1({chr(96 + i)})",
                               text=f"({chr(96 + i)}) The label must bear the name and place of business of the distributor {i}.")
               for i in range(1, n + 1)]
    return SimpleNamespace(sources=sources)


def test_the_focused_quote_keeps_three_paragraphs_by_default(monkeypatch):
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", validator_switches.VALIDATOR_PRECISION - {"FQ1"})
    text = focused_quote(_package(6), "What must the label's name and place of business statement include?")
    assert text.count("verbatim):") == 3


def test_fq1_quotes_more_of_the_requested_provision(monkeypatch):
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", validator_switches.VALIDATOR_PRECISION | {"FQ1"})
    text = focused_quote(_package(6), "What must the label's name and place of business statement include?")
    assert text.count("verbatim):") == 6   # G-001 (27 Oct): 201.1(a), (h)(1), (j) quoted, (b)-(g) scored as omitted
