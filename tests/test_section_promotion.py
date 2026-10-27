"""Section promotion, the answer-first format, the statute corpus and the refusal retry (22 Oct 2026)."""
from dataclasses import replace

from regulus.planning import plan_query
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.answer_plan import APPLY_FORMAT
from regulus.rag.generation import render_package
from regulus.rag.pipeline import REFUSAL_RETRY_NOTE, _without_part_requirements
import pytest

from regulus.rag import section_promotion as SP
from regulus.inference.types import GenerationResult
from regulus.rag.section_promotion import Promotion, SectionPromoter, parse_picks, picker_prompt
from regulus.rag.validation import UNSUPPORTED_FIGURE, validate_answer
from regulus.retrieval import LexicalRetriever
from regulus.retrieval.section_index import SectionIndex, cosmetic_question
from tests.test_answer_validation import TWO, ScriptedGenerator, gen
from tests.test_generation_contract import package_for
from tests.test_retrieval_plan import TableDatabase


# ------------------------------------------------------------ picker reply parsing


def test_picker_reply_bracket_numbers_and_section_numbers():
    secs = ["71.1", "70.25", "73.2550"]
    assert parse_picks("[2], [1]", 20, secs) == [2, 1]
    # a reply naming a section is the candidate carrying that number, not candidates 70 and 25
    assert parse_picks("70.25", 20, secs) == [2]
    assert parse_picks("NONE", 20, secs) == []
    assert parse_picks("[99]", 3, secs) == []


def test_picker_prompt_lists_cfr_and_statute_candidates():
    p = picker_prompt("Q?", [
        {"section": "74.2203", "heading": "FD&C Green No. 3.", "part": "74", "part_title": "Listing", "subpart": "Subpart C - Cosmetics",
         "snippet": "may be safely used"},
        {"statute": True, "section": "605", "usc": "364a", "heading": "Adverse events", "snippet": "shall submit"}])
    assert "[1] 21 CFR 74.2203 FD&C Green No. 3." in p and "[2] FD&C Act § 605 [21 U.S.C. 364a] Adverse events" in p
    assert p.rstrip().endswith("Reply NONE if no candidate answers it.")


# ------------------------------------------------------------ siblings and part-only plans


def _cand(section, part, heading, subpart):
    return {"section": section, "part": part, "heading": heading, "subpart": subpart}


def test_color_listing_siblings_keep_cosmetics_and_part_82_not_drug_listing():
    pr = SectionPromoter(db=None, mode="lexical", index=object())
    cands = [_cand("82.1254", "82", "D&C Orange No. 4.", "Subpart D - Externally Applied Drugs and Cosmetics"),
             _cand("74.1254", "74", "D&C Orange No. 4.", "Subpart B - Drugs"),
             _cand("74.2254", "74", "D&C Orange No. 4.", "Subpart C - Cosmetics"),
             _cand("70.5", "70", "General restrictions on use of color additives.", "")]
    assert pr.siblings(cands[0], cands, ["toothpast", "orang"]) == ["82.1254", "74.2254"]
    # a drug question keeps the drug listing instead
    assert "74.1254" in pr.siblings(cands[1], cands, ["tablet", "orang"])


def test_part_only_question_loses_the_part_requirement_once_sections_are_resolved():
    p = plan_query("Under Part 82, what specifications must a batch of FD&C Green No. 3 meet? (21 CFR 82.203, 82.50)")
    out = _without_part_requirements(p)
    assert [(r.id, r.canonical) for r in out.requirements] == [("r1", "21 CFR 82.203"), ("r2", "21 CFR 82.50")]


def test_promotion_suffix_names_sections_then_companions():
    pr = Promotion(sections=("74.2203",), companions=("70.5(a)",), method="picker")
    assert pr.suffix == " (21 CFR 74.2203, 70.5(a))"
    assert Promotion(sections=(), companions=(), method="named_statute", statute=("605",)).suffix == ""


# ------------------------------------------------------------ section ranking


def _rows():
    def r(sec, part, ordinal, heading, body, head, subpart=""):
        return {"section_number": sec, "part_number": part, "ordinal": ordinal, "subpart": subpart,
                "section_heading": heading, "body": body, "head": head}
    return [r("71.2", "71", 0, "Notice of filing of petition.", ["petit", "file", "notic", "publish", "feder", "regist"], ["notic", "file", "petit"]),
            r("71.1", "71", 0, "Petitions.", ["petit", "color", "addit", "submit"], ["petit"]),
            r("74.2203", "74", 0, "FD&C Green No. 3.", ["green", "3", "cosmet", "safe", "use"], ["fd", "c", "green", "3"], "Subpart C - Cosmetics"),
            r("74.1203", "74", 0, "FD&C Green No. 3.", ["green", "3", "drug", "safe", "use"], ["fd", "c", "green", "3"], "Subpart B - Drugs"),
            r("101.1", "101", 0, "Principal display panel.", ["label", "panel", "food"], ["princip", "display", "panel"])]


def test_section_index_prefers_the_cosmetics_listing_for_a_cosmetics_question():
    ix = SectionIndex.from_rows(_rows())
    ranked = [r.section for r in ix.rank(["lipstick", "green", "3", "fd", "c"])]
    assert ranked[0] == "74.2203" and ranked.index("74.2203") < ranked.index("74.1203")
    assert cosmetic_question(["lipstick"]) and not cosmetic_question(["tablet"])


def test_section_index_ranks_the_specific_heading_first():
    ix = SectionIndex.from_rows(_rows())
    assert ix.rank(["notic", "file", "petit", "public"])[0].section == "71.2"


# ------------------------------------------------------------ answer-first format and validation


def test_apply_style_replaces_the_answer_format_line():
    pkg = package_for(TWO)
    assert APPLY_FORMAT not in render_package(pkg)
    assert render_package(replace(pkg, answer_style="apply")).rstrip().endswith(APPLY_FORMAT)


def test_apply_style_accepts_figures_the_question_states():
    pkg = replace(package_for("For our 12 fl oz bottle, what do 820.10(b)(2) and 820.10(b)(4) require?"), answer_style="apply")
    text = ("For the 12 fl oz bottle, 21 CFR 820.10(b)(2) requires traceability procedures [1]. "
            "21 CFR 820.10(b)(4) requires advisory notices [2].")
    assert UNSUPPORTED_FIGURE not in validate_answer(text, pkg, gen("x")).codes()
    assert UNSUPPORTED_FIGURE in validate_answer(text, replace(pkg, answer_style="restate"), gen("x")).codes()


def test_statute_resolution_is_rendered_as_the_requested_provision():
    pkg = replace(package_for("What does the law say?"), resolved=("FD&C Act § 605 [21 U.S.C. 364a] Adverse events",))
    assert "FD&C Act § 605 [21 U.S.C. 364a] Adverse events (the statute section this question is about" in render_package(pkg)


# ------------------------------------------------------------ refusal retry


class TwoAnswers(ScriptedGenerator):
    def __init__(self, first, second):
        super().__init__(first); self.answers = [first, second]

    def generate(self, messages, max_new_tokens=None, on_text=None):
        self.response = self.answers[min(len(self.calls), 1)]
        return super().generate(messages, max_new_tokens)


def test_a_bare_decline_with_the_requested_provision_supplied_is_asked_once_more():
    g = TwoAnswers("The available regulatory sources do not provide enough information to answer this.",
                   "21 CFR 820.10(b)(2) requires traceability procedures [1]. 21 CFR 820.10(b)(4) requires advisory notices [2].")
    out = RagPipeline(LexicalRetriever(TableDatabase()), g, RagConfig(answer_style="apply")).answer(TWO)
    assert len(g.calls) == 2 and g.calls[1]["messages"][-1]["content"].endswith(REFUSAL_RETRY_NOTE)
    assert out.metadata["generation"]["refusal_retry"] is True and "traceability" in out.answer


def test_no_retry_in_restate_style():
    g = TwoAnswers("The available regulatory sources do not provide enough information to answer this.", "unused")
    RagPipeline(LexicalRetriever(TableDatabase()), g, RagConfig()).answer(TWO)
    assert len(g.calls) == 1


# ------------------------------------------------------------ correction pass


def test_a_rejected_draft_is_corrected_once_and_used_only_if_it_validates():
    g = TwoAnswers("21 CFR 820.10(b)(2) requires traceability procedures [9]. 21 CFR 820.10(b)(4) requires advisory notices [2].",
                   "21 CFR 820.10(b)(2) requires traceability procedures [1]. 21 CFR 820.10(b)(4) requires advisory notices [2].")
    out = RagPipeline(LexicalRetriever(TableDatabase()), g, RagConfig(answer_style="apply")).answer(TWO)
    second = g.calls[1]["messages"]
    assert second[0]["content"].startswith("You write answers") and "9. The EVIDENCE contains the provision" in second[0]["content"]
    assert "PROBLEMS FOUND IN THE DRAFT:" in second[-1]["content"] and "[9]" in second[-1]["content"]
    info = out.metadata["generation"]["correction_pass"]
    assert info["accepted"] is True and out.answer.startswith("21 CFR 820.10(b)(2) requires traceability procedures [1]")


def test_a_correction_that_still_fails_leaves_the_normal_repair_path():
    bad = "21 CFR 820.10(b)(2) requires traceability procedures [9]."
    g = TwoAnswers(bad, bad)
    out = RagPipeline(LexicalRetriever(TableDatabase()), g, RagConfig(answer_style="apply")).answer(TWO)
    assert out.metadata["generation"]["correction_pass"]["accepted"] is False and "[9]" not in out.answer


# ------------------------------------------------------------ code review 22 Oct: apply-style validation stays strict


def test_a_false_number_taken_from_the_question_is_still_unsupported():
    from regulus.rag.validation import _question_figures
    assert _question_figures("may it contain lead up to 10 percent?", ["not more than 0.6 percent"]) == set()
    assert "12" in _question_figures("our 12 fl oz bottle", ["the declaration of net quantity"])


def test_question_words_do_not_count_as_support_for_what_a_sentence_adds():
    from regulus.rag.claim_validation import check_claims
    pkg = replace(package_for(TWO), answer_style="apply")
    q = "Our company received a consumer complaint of a mild rash from our shampoo; what must we do?"
    restates = "Your company received a consumer complaint of a mild rash from your shampoo [1]."
    invents = "Your company must notify every distributor and recall the shampoo batch [1]."
    codes = lambda s: {f.code for f in check_claims([s], pkg, question=q)}
    assert "unsupported_claim" not in codes(restates)
    assert "unsupported_claim" in codes(invents)


def test_promotion_never_runs_where_a_refusal_is_decided_from_the_question(monkeypatch):
    # without PO2: with it, a part outside the cosmetics programme may be promoted into, and "What does 21 CFR Part 11
    # require?" is refused as a whole-part question by SectionPromoter.prepare instead
    from regulus.rag import validator_switches
    from regulus.rag.pipeline import may_promote
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", validator_switches.VALIDATOR_PRECISION - {"PO2"})
    for q in ("Under the EU Cosmetics Regulation, what must a lipstick label list?",
              "What does paragraph (b) require for lipstick colors?",
              "Under 16 CFR Part 500, what must a label state?",
              "What does 21 CFR Part 11 require?",
              "Which FDA guidance covers cosmetic labeling?"):
        assert not may_promote(q, plan_query(q)), q
    for q in ("Is FD&C Green No. 3 permitted in eye shadow?", "Under Part 82, what specifications must a batch meet?",
              "What does FD&C Act § 607 require of a cosmetics facility?"):
        assert may_promote(q, plan_query(q)), q


# ------------------------------------------------------------ code review round 2


def test_reasoning_block_check_accepts_the_1_7b_empty_think_and_refuses_an_open_one():
    from regulus.rag.mlx_models import opens_reasoning
    assert not opens_reasoning("")                              # Qwen3-4B-Instruct-2507's own template
    assert not opens_reasoning("<think>\n\n</think>\n\n")       # Qwen3-1.7B, thinking off
    assert opens_reasoning("<think>\n")                         # a thinking model


def test_ambiguous_questions_may_resolve_only_a_named_statute_section():
    from regulus.rag.pipeline import may_promote
    assert may_promote("What does paragraph (b) of the FD&C Act require for lipstick colors?",
                       plan_query("What does paragraph (b) of the FD&C Act require for lipstick colors?")) == "named_statute"
    assert may_promote("What does 40 CFR require for pesticide residues on cosmetics?",
                       plan_query("What does 40 CFR require for pesticide residues on cosmetics?")) is None
    q = "Which section of 21 CFR lists iron oxides for use in cosmetics?"
    assert may_promote(q, plan_query(q)) == "any"


def test_a_question_without_regulatory_vocabulary_is_never_promoted():
    class Vocab:
        def domain_terms(self, q):
            return ()

    class Policy:
        vocabulary = Vocab()

        def decide(self, *a, **k):
            from regulus.retrieval.domain import GENERAL_KNOWLEDGE, ScopeDecision
            return ScopeDecision(GENERAL_KNOWLEDGE, "uses no word of the regulatory vocabulary", ())

    calls = []

    class Promoter:
        mode = "picker"
        generator = None

        def resolve(self, *a, **k):
            calls.append(a)

    pipe = RagPipeline(LexicalRetriever(TableDatabase()), ScriptedGenerator("x"), RagConfig(section_promotion="picker"),
                       scope_policy=Policy())
    pipe._promoter = Promoter()
    pipe.section_promoter = lambda: pipe._promoter
    pipe.answer("What is the capital of France?")
    assert calls == []


def test_mlx_request_carries_the_repetition_penalty_only_when_set():
    import types
    from regulus.rag.mlx_generator import MlxGenerator
    g = object.__new__(MlxGenerator)
    g.eos_ids = [1]
    g.gen = types.SimpleNamespace(repetition_penalty=1.1)
    assert g.generate_request([5, 6], 8)["repetition_penalty"] == 1.1
    g.gen = types.SimpleNamespace(repetition_penalty=1.0)
    assert "repetition_penalty" not in g.generate_request([5, 6], 8)


class _PickRecorder:
    def __init__(self, thinking):
        self.thinking, self.calls = thinking, []

    def generate(self, messages, max_new_tokens=None, on_text=None, **kw):
        self.calls.append({"max_new_tokens": max_new_tokens, **kw})
        return GenerationResult(prompt="", response="", prompt_tokens=0, generated_tokens=0, seconds=0.0, finished=True)


@pytest.mark.parametrize("thinking,expected", [(True, {"max_new_tokens": SP.PICKER_MAX_TOKENS, "think_budget": 0}),
                                               (False, {"max_new_tokens": SP.PICKER_MAX_TOKENS})])
def test_the_picker_closes_a_thinking_models_reasoning_block(monkeypatch, thinking, expected):
    gen = _PickRecorder(thinking)
    pr = SectionPromoter(db=None, generator=gen, mode="picker", index=object())
    monkeypatch.setattr(SectionPromoter, "statute", property(lambda self: None))
    monkeypatch.setattr(SP.SectionIndex, "question_lexemes", staticmethod(lambda db, q: {"lash", "adhes"}))
    monkeypatch.setattr(pr, "named_statute", lambda q, lex: [])
    monkeypatch.setattr(pr, "candidates", lambda q, parts=None: ({"lash", "adhes"}, [
        {"section": "700.3", "part": "700", "heading": "Definitions.", "subpart": "", "snippet": "x"}]))
    assert pr.resolve("Which rules apply to our lash adhesive?") is None   # an empty reply picks nothing
    assert gen.calls == [expected]


# per-section relevance order (22 Oct 2026): a promoted section with a companion lost 701.3(m) and (r) to document order
def _two_section_required(question):
    from regulus.rag.selection import is_required
    from tests.test_retrieval_plan import row
    table = [row("701.3", "(a)", 0, text="(a) The label shall bear a declaration of the name of each ingredient in descending order."),
             row("701.3", "(b)", 1, text="(b) The declaration shall appear on an information panel in letters not less than 1/16 inch."),
             row("701.3", "(r)", 2, text="(r) A cosmetic sold solely by direct mail order may bear the declaration in a catalog or brochure."),
             row("701.30", "", 3, text="The Commissioner establishes the following names for cosmetic ingredient labeling.")]
    reg = LexicalRetriever(TableDatabase(table)).run_plan(plan_query(question)).registry
    return [e for e in reg.evidence if is_required(e)]


def test_each_section_is_ordered_by_relevance_and_sections_keep_their_order():
    from regulus.rag.selection import _required_order
    required = _two_section_required("We sell by direct mail order. Where does the declaration go under 21 CFR 701.3 and 701.30?")
    assert [e.citation for e in required][:3] == ["21 CFR 701.3(a)", "21 CFR 701.3(b)", "21 CFR 701.3(r)"]
    order = [e.citation for e in _required_order(required, "We sell by direct mail order. Where does the declaration go?")]
    assert order[0] == "21 CFR 701.3(r)"                       # the paragraph the question is about, first
    assert order[-1] == "21 CFR 701.30"                        # the companion section still follows the promoted one
    assert sorted(order) == sorted(e.citation for e in required)


def _statute_row(sec, path, text, heading="", top_caption=""):
    return {"fdca_section": sec, "usc_section": {"604": "364", "605": "364a"}[sec], "paragraph_path": path, "ordinal": 0,
            "heading": "Definitions" if sec == "604" else "Adverse events", "paragraph_heading": heading,
            "body_text": text, "top_caption": top_caption, "source_url": "https://uscode.house.gov"}


def test_a_promoted_subchapter_section_brings_the_604_definitions_it_uses(monkeypatch):
    from regulus.retrieval.statute import StatuteIndex
    rows = [_statute_row("604", "", "In this subchapter:"),
            _statute_row("604", "(1)", 'The term "adverse event" means any health-related event that is adverse.', "Adverse event"),
            _statute_row("604", "(3)(A)", '(A) In general.—The term "facility" includes any establishment.', top_caption="Facility"),
            _statute_row("604", "(5)", 'The term "serious adverse event" means an adverse event that—', "Serious adverse event"),
            _statute_row("604", "(5)(A)", "(A) results in death;"),
            _statute_row("605", "(a)", "(a) The responsible person shall submit each serious adverse event report.")]
    st = StatuteIndex(rows, [set() for _ in rows])
    monkeypatch.setattr(SectionPromoter, "statute", property(lambda self: st))
    pr = SectionPromoter(db=None, mode="picker", index=object())
    pro = pr._statute_promotion([("605", "")], set(), "picker", 0.0)
    blocks = [[rows[i]["paragraph_path"] for i in g] for g in pro.statute_blocks]
    assert blocks[0] == ["(a)"]                                    # the section's own text first
    assert ["(5)", "(5)(A)"] in blocks and ["(1)"] in blocks     # the terms 605(a) uses, a definition kept whole
    assert ["(3)(A)"] not in blocks                               # "facility" is not used by the kept text
    assert pro.statute == ("605",)                                # 604 is supporting text, not the resolved section
    # only the sections 604 governs get its definitions (601 adulteration, 201 definitions and 604 itself do not)
    assert SP.SUBCHAPTER_DEFINED == frozenset(str(n) for n in range(605, 615))



# ------------------------------------------------------------ DV1 paragraph-level retrieval (27 Oct)


class _PartRows:
    def __init__(self, rows):
        self.rows = rows

    def query(self, sql, params):
        return [dict(s=s, p=p, h=h, t=t) for s, p, h, t in self.rows]


class _FlatReranker:
    def __init__(self, scores):
        self.scores = scores

    def score(self, question, texts):
        return [max([v for k, v in self.scores.items() if k in t] or [0.0]) for t in texts]


def _part_promoter(monkeypatch, rows, scores):
    import regulus.retrieval.rerank as RR
    monkeypatch.setattr(SP, "RERANKER", "fake")
    monkeypatch.setattr(RR, "reranker", lambda name: _FlatReranker(scores))
    pr = SectionPromoter.__new__(SectionPromoter)
    pr.db = _PartRows(rows)
    return pr


def test_every_row_of_a_definitions_paragraph_is_scored(monkeypatch):
    rows = [("820.3", "(b)", "Definitions.", "All definitions in section 201 of the act shall apply."),
            ("820.3", "(b)", "Definitions.", "Safety and Performance shall have the meaning of safety and effectiveness."),
            ("820.1", "(a)", "Scope.", "Finished devices will be safe and effective.")]
    pr = _part_promoter(monkeypatch, rows, {"Safety and P": 0.9, "Finished dev": 0.1})
    assert pr.part_paragraphs("What meaning does Part 820 give to 'safety and performance'?", "820")[0] == "820.3"   # short: whole


def test_the_paragraph_sharing_the_most_phrases_is_kept_under_the_score_floor(monkeypatch):
    rows = [("820.7", "(b)", "Incorporation by reference.", "ISO 13485 is incorporated by reference."),
            ("820.10", "(c)", "Requirements.", "Design and development. Manufacturers of class II devices must comply."),
            ("820.45", "(a)", "Labeling.", "Labeling must be examined.")]
    pr = _part_promoter(monkeypatch, rows, {"ISO 13485 is": 0.6, "Design and d": 0.05})
    got = pr.part_paragraphs("Which devices must apply the design and development requirements?", "820")
    assert got == ["820.10", "820.7"]   # phrase rank 1 and cross-encoder rank 2 fuse ahead; short sections whole


def test_a_paragraph_of_a_long_section_brings_its_top_level_family():
    items = [("820.1(a)", "x" * 900), ("820.1(a)(1)", "x" * 300), ("820.1(a)(4)", "x" * 300), ("820.1(b)", "x" * 400),
             ("820.7", "y" * 200), ("820.7(a)", "y" * 300), ("820.7(b)", "y" * 300)]
    assert SectionPromoter.paragraph_families(["820.1(a)(4)", "820.7(b)"], items) == \
        ["820.1(a)", "820.1(a)(1)", "820.1(a)(4)", "820.7"]


def test_hc1_coordinated_topics_split_across_sibling_headings():
    from regulus.rag.section_promotion import _coordinated, _topic_stems
    pairs = _coordinated("What are the drug product inspection and expiration dating requirements?")
    assert any("inspec" in left and {"expira", "dating"} <= right for left, right in pairs)
    assert _coordinated("What are the general laboratory control requirements under Part 211?") == []
    assert _topic_stems("Drug product salvaging.") & _topic_stems("returned and salvaged drug products")


def test_ht1_generic_headings_are_never_twins():
    from regulus.rag.section_promotion import _GENERIC_HEADING
    assert _GENERIC_HEADING.match("Scope.") and _GENERIC_HEADING.match("Definitions.")
    assert not _GENERIC_HEADING.match("Production record review.")
