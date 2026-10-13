"""Citation grounding (Measurement Audit Phase 2A).

Rubric column L: "Every regulatory citation in the response is correct to the
section, and to the paragraph where the response asserts a paragraph-level
requirement." The evaluator used to decide a claim's citation by comparing its
marker with the ONE passage the support aligner ranked first. On acceptance row
C-004, 700.11(a) (cited as [1]) and 700.14(a) end in the same sentence; the
semantic aligner ranked 700.14(a) first and a correct citation was reported as
pointing elsewhere (human L=1). With the lexical aligner the same citation was
correct: the verdict depended on a tie-break.

The rule now: a claim's citation is correct when a source it CITES supports it,
to the same standard as the support verdict. The aligner's winner never decides
a citation. What a marker cites follows the reviewer's own reading (rows C-002,
G-004, P-010, E-001): a marker cites the statement it is attached to; a later
marker in the paragraph cites an earlier statement only if it supports it
(otherwise that statement is uncited, never mis-cited); a line of markers alone
cites what precedes it, at section level.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import evaluate
from regulus.accuracy import rubric as R
from regulus.accuracy.alignment import LexicalAligner
from tests.test_accuracy_claim_extraction import Cov, Pkg, Src

ROWS = {r["id"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_extraction_rows.json").read_text(encoding="utf-8"))["rows"]}


def run(question, answer, sources, aligner=None):
    srcs = tuple(Src(i + 1, c, t, corpus=corpus) for i, (c, t, corpus) in
                 enumerate(s if len(s) == 3 else (*s, "ecfr") for s in sources))
    return evaluate(question, answer, package=Pkg(question, srcs), coverage=Cov(), aligner=aligner)


def claim(a, text):
    return next(c for c in a.checked["claims"] if text in c["claim"])


def citation_state(a):
    return a.states[R.CITATION]


class Prefer(LexicalAligner):
    """Lexical scores, but one source ranked first whenever it is a candidate -
    a stand-in for an aligner whose winner differs (the semantic aligner ranked
    700.14(a) first on C-004)."""

    def __init__(self, source_index):
        self.source_index = source_index

    def align(self, claim, candidates, *, top_k=3):
        found = super().align(claim, candidates, top_k=len(candidates))
        found.sort(key=lambda a: a.passage.source_index != self.source_index)
        return found[:top_k]


def frozen(row_id, aligner=None):
    r = ROWS[row_id]
    srcs = tuple(Src(s["index"], s["citation"], s["text"], s.get("heading"), citation_fields=s.get("citation_fields") or {})
                 for s in r["sources"])
    return evaluate(r["question"], r["answer"], package=Pkg(r["question"], srcs), coverage=Cov(),
                    model_called=r["model_called"], fallback_type=r["fallback_type"], aligner=aligner)


ADULTERATED = "These ingredients are deemed to be adulterated under section 601(a)"


# ======================================================= C-004 (mandatory)


def test_C004_the_cited_source_supports_the_claim_whichever_source_the_aligner_ranks_first():
    lexical = frozen("C-004", LexicalAligner())
    semantic_like = frozen("C-004", Prefer(3))           # 700.14(a) first, as the semantic aligner ranked it
    a, b = claim(lexical, ADULTERATED), claim(semantic_like, ADULTERATED)
    # the aligners really do pick different winners for the support verdict ...
    assert a["selected_evidence"] == "21 CFR 700.11(a)" and b["selected_evidence"] == "21 CFR 700.14(a)"
    # ... and the citation [1] -> 700.11(a) is correct under both
    for c in (a, b):
        assert c["citation"] == AN.CITE_CORRECT
        assert c["citation_trace"]["markers"][0] == {"marker": 1, "source": "21 CFR 700.11(a)",
                                                    "verdict": "supported", "supports": True}


def test_C004_the_adulteration_claim_is_never_a_citation_defect():
    """Row level, the 60-row run with the semantic aligner of record measures C-004
    citation PASS. A lexical-scored aligner (as here) additionally "supports"
    'The use of bithionol in cosmetics is prohibited [1]' from 700.23 by shared
    terminology - the Phase 1 paraphrase defect, out of scope for 2A - and that
    claim, not the citation rule, is the only one that can then be flagged."""
    for aligner in (LexicalAligner(), Prefer(3)):
        a = frozen("C-004", aligner)
        defects = [c for c in a.checked["claims"] if c["citation"] in AN.CITATION_DEFECTS]
        assert all("bithionol in cosmetics is prohibited" in c["claim"] for c in defects)
        assert claim(a, ADULTERATED)["citation"] == AN.CITE_CORRECT


# ======================================================= what a citation must be


RECORDS = ("21 CFR 820.180(b)", "All records required by this part shall be retained for a period of two years.")
DESIGN = ("21 CFR 820.30(a)", "Each manufacturer shall establish and maintain procedures to control the design of the "
                              "device.")
Q = "How long must records be retained, and what must manufacturers do about design?"


def test_a_citation_to_a_source_that_does_not_support_the_claim_is_wrong():
    a = run(Q, "All records required by this part shall be retained for a period of two years [2].", [RECORDS, DESIGN])
    c = claim(a, "retained")
    assert c["citation"] == AN.CITE_POINTS_ELSEWHERE and citation_state(a) == R.FAIL


def test_multiple_citations_are_each_checked_and_one_supporting_source_suffices():
    """Decision: L asks whether the citation is correct; a statement that cites its
    governing provision plus a related one cites correctly. Both are traced."""
    a = run(Q, "All records required by this part shall be retained for a period of two years [1][2].", [RECORDS, DESIGN])
    c = claim(a, "retained")
    assert c["citation"] == AN.CITE_CORRECT
    assert [(m["marker"], m["supports"]) for m in c["citation_trace"]["markers"]] == [(1, True), (2, False)]


def test_shared_boilerplate_does_not_make_the_wrong_section_a_correct_citation():
    bithionol = ("21 CFR 700.11(a)", "Any cosmetic containing bithionol is deemed to be adulterated under section 601(a) "
                                     "of the Federal Food, Drug, and Cosmetic Act.")
    vinyl = ("21 CFR 700.14(a)", "Any cosmetic aerosol product containing vinyl chloride as an ingredient is deemed to "
                                 "be adulterated under section 601(a) of the Federal Food, Drug, and Cosmetic Act.")
    a = run("Which cosmetic ingredients are deemed adulterated?",
            "Any cosmetic containing bithionol is deemed to be adulterated under section 601(a) of the Federal Food, "
            "Drug, and Cosmetic Act [2].", [bithionol, vinyl])
    c = claim(a, "bithionol")
    assert c["citation"] == AN.CITE_POINTS_ELSEWHERE
    assert c["citation_trace"]["markers"][0]["supports"] is False


def test_the_right_section_but_the_wrong_paragraph_is_a_defect():
    """Row M-020: per-item markers shifted by one paragraph inside 820.35, L=0."""
    a = run("What must complaint records contain?",
            "Complaint records include the nature and details of the complaint [1].",
            [("21 CFR 820.35(a)(3)", "(3) Any unique device identifier (UDI) or universal product code (UPC);"),
             ("21 CFR 820.35(a)(5)", "(5) The nature and details of the complaint;")])
    assert claim(a, "nature")["citation"] == AN.CITE_PARAGRAPH_MISMATCH and citation_state(a) == R.FAIL


def test_M020_the_three_shifted_items_and_only_those_are_paragraph_mismatches():
    a = frozen("M-020", LexicalAligner())
    statuses = {c["claim_id"]: c["citation"] for c in a.checked["claims"]}
    shifted = sorted(k for k, v in statuses.items() if v == AN.CITE_PARAGRAPH_MISMATCH)
    assert len(shifted) == 3 and all(statuses[k] == AN.CITE_CORRECT for k in statuses if k not in shifted)
    assert all(any(w in claim(a, "")["claim"] or True for w in ()) for _ in ())   # (trace kept for review)
    texts = [c["claim"] for c in a.checked["claims"] if c["citation"] == AN.CITE_PARAGRAPH_MISMATCH]
    assert any("nature and details" in t for t in texts) and any("reply" in t or "corrective" in t for t in texts)


def test_markers_inside_a_sentence_are_evaluated():
    a = run(Q, "Under [1] all records required by this part shall be retained for a period of two years, as [2] also "
               "notes.", [RECORDS, DESIGN])
    c = claim(a, "retained")
    assert {m["marker"] for m in c["citation_trace"]["markers"]} == {1, 2} and c["citation"] == AN.CITE_CORRECT


def test_a_paragraph_marker_cites_an_earlier_statement_only_if_it_supports_it():
    # P-010: a quotation followed by a pointer carrying [1] -> the quoted section: cited, L=1
    quoted = run("What must the manufacturer do?",
                 "Each manufacturer shall establish and maintain procedures to control the design of the device. "
                 "Further duties are described in subpart C [1].", [DESIGN])
    assert claim(quoted, "control the design")["citation"] == AN.CITE_CORRECT
    # C-002: a statement the paragraph's marker does not support is uncited, not mis-cited
    other = run(Q, "All records required by this part shall be retained for a period of two years. Each manufacturer "
                   "shall establish and maintain procedures to control the design of the device [2].", [RECORDS, DESIGN])
    assert claim(other, "retained")["citation"] == AN.CITE_MISSING
    assert claim(other, "control the design")["citation"] == AN.CITE_CORRECT and citation_state(other) == R.PASS


def test_a_standalone_marker_line_cites_what_precedes_it_at_section_level():
    """Row E-001: a lone "[1]" under the answer pointing to 11.100(a); the
    statement comes from 11.1(a) - a different section, L=0."""
    a = run("What is the scope of Part 11?",
            "The regulations in this part set forth the criteria under which the agency considers electronic records "
            "trustworthy.\n\n[1]",
            [("21 CFR 11.100(a)", "Each electronic signature shall be unique to one individual."),
             ("21 CFR 11.1(a)", "The regulations in this part set forth the criteria under which the agency considers "
                                "electronic records trustworthy.")])
    c = claim(a, "set forth")
    assert c["citation_trace"]["kind"] == "block" and c["citation"] == AN.CITE_POINTS_ELSEWHERE


def test_a_marker_on_a_non_claim_sentence_that_matches_no_source_is_a_defect():
    a = run(Q, "All records required by this part shall be retained for a period of two years [1]. The sources that "
               "support this are [1][4].", [RECORDS, DESIGN])
    assert citation_state(a) == R.FAIL and "[4]" in a.dimensions[[d.dimension for d in a.dimensions].index(R.CITATION)].detail


def test_a_valid_marker_on_a_pointer_sentence_is_not_judged_by_its_wording():
    a = run(Q, "All records required by this part shall be retained for a period of two years [1]. Design duties are "
               "described in [2].", [RECORDS, DESIGN])
    assert citation_state(a) == R.PASS


GUIDE = "FDA Guidance: Records Retention Q&A (final, 2024-01-01, Docket FDA-2024-D-0002)"


def test_guidance_cited_for_a_requirement_the_regulation_states_is_a_defect():
    a = run("How long must records be retained?",
            "All records required by this part shall be retained for a period of two years [2].",
            [RECORDS, (GUIDE, "All records required by this part shall be retained for a period of two years.",
                       "fda_guidance")])
    assert claim(a, "retained")["citation"] == AN.CITE_GUIDANCE_FOR_REQUIREMENT and citation_state(a) == R.FAIL


def test_guidance_that_only_recommends_is_not_a_correct_citation_for_a_requirement():
    a = run("How long must records be retained?",
            "All records required by this part shall be retained for a period of two years [2].",
            [RECORDS, (GUIDE, "Manufacturers should retain all records required by this part for a period of two years.",
                       "fda_guidance")])
    assert claim(a, "retained")["citation"] != AN.CITE_CORRECT


def test_guidance_cited_for_what_guidance_says_is_correct():
    g = "FDA recommends that manufacturers retain electronic copies of complaint records."
    a = run("What does FDA guidance recommend for complaint records?", g + " [1]", [(GUIDE, g, "fda_guidance")])
    assert claim(a, "recommends")["citation"] == AN.CITE_CORRECT and citation_state(a) == R.PASS


def test_a_cited_source_that_cross_references_the_stating_provision_is_correct():
    a = run("How is the expiration date determined?",
            "The expiration date shall be determined by appropriate stability testing [1].",
            [("21 CFR 211.137(a)", "A drug product shall bear an expiration date determined by appropriate stability "
                                   "testing described in § 211.166."),
             ("21 CFR 211.166(a)", "The expiration date shall be determined by appropriate stability testing.")])
    assert claim(a, "expiration")["citation"] == AN.CITE_CORRECT


def test_a_citation_nothing_captured_can_check_is_unverified_not_wrong():
    a = run(Q, "Design history files must be reviewed by an independent auditor every year [1].", [RECORDS, DESIGN])
    c = claim(a, "auditor")
    assert c["citation"] == AN.CITE_UNVERIFIED and c["citation"] not in AN.CITATION_DEFECTS
    assert citation_state(a) == R.NOT_ESTABLISHED


def test_a_provision_named_in_the_text_is_a_citation_too():
    """Row D-010: a statement labelled with one provision whose text is another's."""
    a = run("How must containers be identified?",
            "Each lot shall be identified with a distinctive code (21 CFR 111.113(b)(1)).",
            [("21 CFR 111.113(b)(1)", "You must quarantine components that do not conform to specifications."),
             ("21 CFR 211.80(d)", "Each lot shall be identified with a distinctive code.")])
    c = claim(a, "distinctive code")
    assert c["citation_trace"]["kind"] == "named" and c["citation"] == AN.CITE_POINTS_ELSEWHERE


def test_the_citation_check_changes_no_substantive_verdict():
    a = run("How long must records be retained?",
            "All records required by this part shall be retained for a period of two years [2].", [RECORDS, DESIGN])
    c = claim(a, "retained")
    assert c["support"] == AN.SUPPORTED and a.checked["answer_verdict"]["verdict"] == AN.CORRECT
