"""Follow-up questions (regulus.rag.conversation): how a question is read against its conversation (26 Oct 2026)."""
from dataclasses import replace

from regulus.planning import plan_query
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.conversation import (Anchor, ConversationContext, FollowUp, PriorTurn, cues, resolve, subject_words,
                                      turn_anchor, write_out_pointers)
from regulus.rag.generation import EARLIER_QUESTION_LEAD, render_package
from regulus.rag.section_promotion import Promotion
from regulus.retrieval import LexicalRetriever
from tests.test_answer_validation import ScriptedGenerator
from tests.test_generation_contract import package_for
from tests.test_retrieval_plan import TableDatabase

PARENT = "We're formulating a tinted body lotion with D&C Yellow No. 8. Can we use it, and is there a use limit?"


def ctx(question=PARENT, cfr=("74.2708",), statute=()):
    return ConversationContext((PriorTurn(question, Anchor(cfr=cfr, statute=statute)),))


def read(question, context=None, **kw):
    kw = {"names_provision": False, "other_entity": False, **kw}
    return resolve(question, ctx() if context is None else context, **kw)


# ------------------------------------------------------------ reading a follow-up


def test_no_context_reads_nothing():
    assert resolve("Can we use it in an eye shadow?", None, names_provision=False, other_entity=False) is None
    assert resolve("Can we use it in an eye shadow?", ConversationContext(), names_provision=False, other_entity=False) is None


def test_a_short_question_pointing_back_is_anchored():
    fu = read("Can we use it in an eye shadow?")
    assert fu.anchored and fu.anchor.cfr == ("74.2708",) and "pronoun" in fu.cues
    assert fu.earlier_question == PARENT and fu.question == "Can we use it in an eye shadow?"


def test_a_paragraph_pointer_is_written_out_as_the_anchored_section():
    fu = read("What does paragraph (b)(1) say about the amount?")
    assert fu.anchored and fu.question == "What does 21 CFR 74.2708(b)(1) say about the amount?"
    assert write_out_pointers("Does this section cover lip products?", "74.2708") == "Does 21 CFR 74.2708 cover lip products?"


def test_a_pointer_names_the_primary_section_or_act_section():
    two = ConversationContext((PriorTurn(PARENT, Anchor(cfr=("74.2708", "82.1708"))),))
    assert read("What records does this section require us to keep?", context=two).question == \
        "What records does 21 CFR 74.2708 require us to keep?"
    act = ConversationContext((PriorTurn("What does 607 require?", Anchor(statute=("607",))),))
    assert read("What does subsection (b) of this section add?", context=act).question.startswith("What does FD&C Act § 607(b)")


def test_a_tag_question_about_the_conversation_is_anchored():
    fu = read("The limit is 5 percent, right?")
    assert fu.anchored and "tag_question" in fu.cues


def test_a_question_naming_its_own_provision_or_another_color_is_answered_on_its_own():
    assert read("What does 70.5(a) say?", names_provision=True).reason == "names_own_provision"
    fu = read("And D&C Red No. 6?", other_entity=True)
    assert not fu.anchored and fu.reason == "names_other_color"
    # the earlier question is still shown: "it" may need it
    assert fu.earlier_question == PARENT


def test_a_self_contained_new_topic_is_not_anchored_and_gets_no_earlier_question():
    fu = read("We're launching an aerosol dry shampoo in the U.S. What warning statement must the can carry under FDA rules?")
    assert not fu.anchored and fu.reason == "new_topic" and fu.earlier_question is None and not fu.anchor


def test_one_shared_generic_word_does_not_anchor_a_long_new_question():
    # shares "lotion" with the parent, but it is one word of many: a new scenario
    q = ("Our sunscreen lotion with oxybenzone is marketed with an SPF claim and sold through pharmacies; "
         "which monograph and labeling and registration obligations attach to the drug side?")
    assert not read(q).anchored


def test_a_shared_subject_anchors_a_question_without_cues():
    fu = read("Is there a use limit for D&C Yellow No. 8 in body lotion?")
    assert fu.anchored and "shared_subject" in fu.reason


def test_own_ranking_anchors_only_a_question_that_is_not_self_contained():
    assert read("Where does the certification requirement come from?", anchor_ranked=True).anchored
    long_q = ("Our contract filler asks how often scales, pH meters and thermometers must be calibrated, "
              "who signs calibration certificates, and how long calibration records are retained for audits")
    assert not read(long_q, anchor_ranked=True).anchored


def test_a_pronoun_after_the_questions_own_subject_is_not_a_cue():
    assert "pronoun" not in cues("We've been notified that our batch is certified. What must we do with it next?")
    assert "pronoun" in cues("Can it go in a body lotion?")
    assert "pronoun" in cues("Can we use this exemption for a consumer panel?")


def test_a_fragment_is_anchored_and_a_definition_question_is_not():
    assert read("Is there an exemption?").reason == "fragment"
    assert read("What is the deadline?").anchored
    assert not read("What is a cosmetic?").anchored and not read("What does adulterated mean?").anchored


def test_a_whole_part_anchor_asks_the_follow_up_about_that_part():
    c = ConversationContext((PriorTurn("What does Part 11 cover?", Anchor(parts=("11",))),))
    fu = read("Does it apply to spreadsheets?", context=c)
    assert fu.anchored and fu.question == "Does it apply to spreadsheets? (21 CFR part 11)"
    assert turn_anchor(plan_query("What does 21 CFR Part 11 cover?"), None, None) == Anchor(parts=("11",))
    assert Anchor.from_dict({"parts": ["11", "x", "12345"]}) == Anchor(parts=("11",))


def test_no_anchor_means_nothing_to_resolve_to():
    fu = read("Can we use it in an eye shadow?", context=ConversationContext((PriorTurn(PARENT, Anchor()),)))
    assert not fu.anchored and fu.reason == "no_anchor"


def test_subject_words_drop_function_and_generic_regulatory_words():
    assert subject_words("Does FDA require the cosmetic product label to list it?") == {"label", "list"}


# ------------------------------------------------------------ anchors and context


def test_a_stored_anchor_is_sanitized():
    a = Anchor.from_dict({"cfr": ["74.2708", "../../etc/passwd", 7, "74.2708", "70.5"], "statute": ["607", "6070", "x"]})
    assert a == Anchor(cfr=("74.2708", "70.5"), statute=("607",))
    assert Anchor.from_dict("74.2708") == Anchor() and Anchor.from_dict(None) == Anchor()


def test_context_keeps_recent_turns_and_the_topic_opening_question():
    turns = [PriorTurn(f"q{i}", Anchor(cfr=("1.1",))) for i in range(6)]
    c = ConversationContext(tuple(turns))
    assert len(c.turns) == 4 and c.anchor == Anchor(cfr=("1.1",))
    assert c.earlier_question == "q2"   # the earliest kept turn on the current anchor
    c2 = ConversationContext.from_records([("first", {"cfr": ["74.2708"]}), ("second", None), ("", {"cfr": ["1.1"]})])
    assert [t.question for t in c2.turns] == ["first", "second"] and c2.anchor.cfr == ("74.2708",)


def test_turn_anchor_is_what_the_turn_resolved_to():
    pr = Promotion(sections=("74.2708",), companions=("70.5(a)",), method="picker")
    assert turn_anchor(plan_query("Can we use it?"), pr, None) == Anchor(cfr=("74.2708",))   # companions are not kept
    assert turn_anchor(plan_query("What does 21 CFR 720.8(b) require?"), None, None) == Anchor(cfr=("720.8",))
    st = Promotion(sections=(), companions=(), method="named_statute", statute=("607",))
    assert turn_anchor(plan_query("What does FD&C Act 607 say?"), st, None) == Anchor(statute=("607",))
    inherited = FollowUp(True, "pronoun", "Is it allowed?", Anchor(cfr=("74.2708",)))
    assert turn_anchor(plan_query("Is it allowed?"), None, inherited) == Anchor(cfr=("74.2708",))
    named = FollowUp(False, "names_own_provision", "Does 70.5(a) change that?", Anchor(cfr=("74.2708",)))
    assert turn_anchor(plan_query("Does 70.5(a) change that?"), None, named) == Anchor(cfr=("70.5", "74.2708"))
    new = FollowUp(False, "new_topic", "q", Anchor())
    assert turn_anchor(plan_query("What is a cosmetic?"), None, new) == Anchor()


# ------------------------------------------------------------ prompt


def test_the_earlier_question_is_rendered_before_the_question_only_when_set():
    pkg = package_for("What does 21 CFR 820.10(b)(1) require?")
    plain = render_package(pkg)
    assert EARLIER_QUESTION_LEAD not in plain
    shown = render_package(replace(pkg, earlier_question="What does Part 820 cover?"))
    assert shown == f"{EARLIER_QUESTION_LEAD} What does Part 820 cover?\n\n" + plain


# ------------------------------------------------------------ pipeline


class _Promoter:
    mode = "picker"
    generator = None
    db = None

    def __init__(self):
        self.calls = []

    def resolve(self, question, parts=None, named_only=False):
        self.calls.append(("resolve", question))
        return None

    def anchored(self, question, cfr=(), statute=()):
        self.calls.append(("anchored", question, tuple(cfr)))
        return None


def _pipe(promoter):
    pipe = RagPipeline(LexicalRetriever(TableDatabase()), ScriptedGenerator("The provision says so [1]."),
                       RagConfig(section_promotion="picker"))
    pipe._promoter = promoter
    pipe.section_promoter = lambda: pipe._promoter
    return pipe


def test_without_context_the_answer_is_unchanged():
    q = "What does 21 CFR 820.10(b)(1) require?"
    a, b, c = (_pipe(_Promoter()).answer(q), _pipe(_Promoter()).answer(q, context=None),
               _pipe(_Promoter()).answer(q, context=ConversationContext()))
    assert a.answer == b.answer == c.answer
    assert a.metadata["conversation"]["followup"] is None and c.metadata["conversation"]["followup"] is None
    assert a.metadata["conversation"]["anchor"] == {"cfr": ["820.10"], "statute": [], "parts": []}


def test_an_anchored_follow_up_is_promoted_to_the_anchor_and_keeps_the_users_words():
    pr = _Promoter()
    out = _pipe(pr).answer("Can we use it in an eye shadow?", context=ctx())
    assert ("anchored", "Can we use it in an eye shadow?", ("74.2708",)) in pr.calls
    assert out.question == "Can we use it in an eye shadow?"
    fu = out.metadata["conversation"]["followup"]
    assert fu["anchored"] and fu["anchor"]["cfr"] == ["74.2708"]
    # nothing new was resolved: the conversation's anchor carries to the next question
    assert out.metadata["conversation"]["anchor"] == {"cfr": ["74.2708"], "statute": [], "parts": []}


def test_a_follow_up_naming_its_own_provision_is_resolved_as_on_its_own():
    pr = _Promoter()
    out = _pipe(pr).answer("What does 21 CFR 820.10(b)(1) require?", context=ctx())
    assert not any(c[0] == "anchored" for c in pr.calls)
    assert out.metadata["conversation"]["followup"]["reason"] == "names_own_provision"


# ------------------------------------------------------------ the page's Focus control


def test_a_requests_focus_overrides_the_deployment_scope_and_only_inside_its_block(monkeypatch):
    import threading

    import pytest

    from regulus.retrieval.section_index import deployment_scope, focus

    monkeypatch.setenv("REGULUS_DEPLOYMENT_SCOPE", "cosmetics")
    assert deployment_scope() == "cosmetics"
    with focus("general"):
        assert deployment_scope() is None
        seen = []
        t = threading.Thread(target=lambda: seen.append(deployment_scope()))   # another request's thread
        t.start(); t.join()
        assert seen == ["cosmetics"]
    assert deployment_scope() == "cosmetics"
    monkeypatch.delenv("REGULUS_DEPLOYMENT_SCOPE")
    with focus("cosmetics"):
        assert deployment_scope() == "cosmetics"
    with focus(None):
        assert deployment_scope() is None
    with pytest.raises(ValueError):
        with focus("drugs"):
            pass


def test_a_read_cancelled_by_the_statement_timeout_is_retried_once(monkeypatch):
    import psycopg
    import pytest

    from regulus.retrieval.db import Database

    calls = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params):
            calls.append(sql)
            if len(calls) == 1 or sql == "always":
                raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        def fetchall(self): return [{"ok": 1}]

    class Conn:
        def transaction(self):
            import contextlib
            return contextlib.nullcontext()
        def cursor(self): return Cur()

    db = object.__new__(Database)
    monkeypatch.setattr(Database, "connect", lambda self: Conn())
    assert db.query("SELECT 1") == [{"ok": 1}] and len(calls) == 2
    with pytest.raises(psycopg.errors.QueryCanceled):
        db.query("always")


# ------------------------------------------------------------ FU2 / FU2B (27 Oct)


def test_a_demonstrative_points_back_unless_the_question_introduced_it(monkeypatch):
    from regulus.rag import validator_switches
    from regulus.rag.conversation import cues

    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", frozenset({"FU2"}))
    assert "demonstrative" in cues("Our formula adds silica abrasive. Does that affect use of this color?")
    assert "demonstrative" not in cues("Our eyeliner uses a color additive that is exempt from certification. Can FDA "
                                       "take that exemption away, and how would we find out?")
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", frozenset())
    assert "demonstrative" not in cues("Our formula adds silica abrasive. Does that affect use of this color?")


def test_a_three_word_question_continues_the_conversation(monkeypatch):
    from regulus.rag import validator_switches
    from regulus.rag.conversation import Anchor, ConversationContext, PriorTurn, resolve

    ctx = ConversationContext((PriorTurn("We want a green toothpaste colored with chlorophyllin. Is that allowed?",
                                         Anchor(cfr=("73.2125",))),))
    q = "What date applied at the retail level?"
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", frozenset())
    assert not resolve(q, ctx, names_provision=False, other_entity=False).anchored
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", frozenset({"FU2B"}))
    assert resolve(q, ctx, names_provision=False, other_entity=False).anchored


# ------------------------------------------------------------ CQ1 conversational query rewriting (27 Oct)


def test_a_rewrite_naming_the_anchor_continues_the_conversation():
    from regulus.rag.conversation import Anchor, read_rewrite

    a = Anchor(cfr=("73.2125",))
    q = "Can we use the same color in a mouthwash?"
    text, continues = read_rewrite("Can we use potassium sodium copper chlorophyllin in a mouthwash under 21 CFR 73.2125?", q, a)
    assert continues and text.endswith("under 21 CFR 73.2125?")
    assert read_rewrite(q, q, a) == (q, False)   # repeated exactly: a new subject


def test_an_unusable_rewrite_is_ignored():
    from regulus.rag.conversation import Anchor, read_rewrite

    a = Anchor(cfr=("73.2125",))
    q = "Can we use the same color in a mouthwash?"
    assert read_rewrite("Can we use it in a mouthwash under 21 CFR 73.1125?", q, a) is None     # invented citation
    assert read_rewrite("Yes, it may be used.", q, a) is None                                    # an answer
    assert read_rewrite("Can we?\nUnder 21 CFR 73.2125?", q, a) is None                          # several lines
    assert read_rewrite("", q, a) is None


def test_a_statute_anchor_is_named_by_its_section_sign():
    from regulus.rag.conversation import Anchor, read_rewrite

    a = Anchor(statute=("611",))
    out = read_rewrite("Can an FDA district director sign a mandatory recall order under FD&C Act § 611?",
                       "Can an FDA district director sign the recall order?", a)
    assert out == ("Can an FDA district director sign a mandatory recall order under FD&C Act § 611?", True)


def test_fu2d_a_use_question_about_a_named_color_belongs_to_its_listing():
    from regulus.rag.pipeline import _USE_OF_COLOR

    assert _USE_OF_COLOR.search("Can we use disodium EDTA-copper to tint a body wash and a shampoo?")
    assert _USE_OF_COLOR.search("We want to use pyrophyllite as the colorant. May we?")
    assert not _USE_OF_COLOR.search("How would we name a calcium lake of FD&C Blue No. 1?")


def test_ct1_a_cosmetics_conversation_is_recognised():
    from regulus.rag.conversation import Anchor, ConversationContext, PriorTurn
    from regulus.rag.pipeline import cosmetics_conversation

    ctx = lambda a: ConversationContext((PriorTurn("q", a),))
    assert cosmetics_conversation(ctx(Anchor(cfr=("73.2125",))))
    assert cosmetics_conversation(ctx(Anchor(statute=("610",))))
    assert not cosmetics_conversation(ctx(Anchor(cfr=("211.192",))))
    assert not cosmetics_conversation(ctx(Anchor(cfr=("701.3", "101.4"))))
    assert not cosmetics_conversation(ctx(Anchor()))
