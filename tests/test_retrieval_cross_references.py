"""P3 cross-reference expansion (LexicalRetriever cross_references, OFF by default): for a question that names no
provision, the provisions that the first eCFR candidates explicitly cite (cfr_cross_references, one hop) are added
after every other candidate as DISCOVERY evidence, at most XREF_MAX_ROWS, each recording which provision cites it and
the reference text. Never for a question that names a provision; never recursive; nothing is promoted."""

import pytest

from regulus.planning import plan_query
from regulus.retrieval import LexicalRetriever
from regulus.retrieval import sql as sql_module
from regulus.retrieval.evidence import TIER_DISCOVERY
from regulus.retrieval.lexical import XREF_MAX_ROWS, XREF_SEEDS
from regulus.retrieval.models import METHOD_CROSS_REFERENCE
from tests.test_retrieval_plan import TableDatabase, row

Q = "What must the labeling of a nutrient content claim include?"
SEEDS = [row("101.13", "(b)", 1, rank=0.9), row("101.13", "(c)", 2, rank=0.8)]
LINKS = {("101.13", "(b)"): [("§ 101.54", row("101.54", "", 10)), ("§ 101.13(c)", row("101.13", "(c)", 2)),
                             ("§ 101.60", row("101.60", "", 11)), ("§ 101.61", row("101.61", "", 12)),
                             ("§ 101.62", row("101.62", "", 13))],
         ("101.13", "(c)"): [("§ 101.9", row("101.9", "", 14))]}


class XrefDatabase(TableDatabase):
    """Answers ECFR_CROSS_REFERENCED from LINKS: the cited rows of each seed, in seed order, other sections only."""

    def query(self, statement, params=None):
        if statement == sql_module.ECFR_CROSS_REFERENCED:
            self.calls.append(("ECFR_CROSS_REFERENCED", dict(params)))
            out = []
            for n, seed in enumerate(zip(params["section_number"], params["paragraph"]), start=1):
                for text, target in LINKS.get(seed, ()):
                    if target["section_number"] != seed[0]:
                        out.append(dict(target, xref_text=text, seed_rank=n, xref_from_section=seed[0], xref_from_paragraph=seed[1]))
            return out[: params["limit"]]
        return super().query(statement, params)


def run(question, *, cross_references=True):
    db = XrefDatabase([], full_text=SEEDS)
    out = LexicalRetriever(db, cross_references=cross_references, defined_terms=False).run_plan(plan_query(question), top_k=8)
    return out, db


def linked(out):
    return [e for e in out.registry.evidence if e.result.retrieval_method == METHOD_CROSS_REFERENCE]


def test_the_cited_provisions_follow_every_other_candidate_with_their_provenance():
    out, db = run(Q)
    links = linked(out)
    assert [e.result.citation.label for e in links] == ["21 CFR 101.54", "21 CFR 101.60", "21 CFR 101.61"][:XREF_MAX_ROWS]
    assert all(e.tier == TIER_DISCOVERY for e in links)
    assert links[0].result.metadata["xref_from"] == "21 CFR 101.13(b)" and links[0].result.metadata["xref_text"] == "§ 101.54"
    keys = [e.key for e in out.registry.evidence]
    assert keys[-len(links):] == [e.key for e in links]          # appended, nothing promoted
    params = dict(db.calls)["ECFR_CROSS_REFERENCED"]
    assert len(params["section_number"]) <= XREF_SEEDS and params["section_number"][0] == "101.13"


def test_off_by_default_and_never_for_a_question_that_names_a_provision():
    off, db_off = run(Q, cross_references=False)
    assert not linked(off) and "ECFR_CROSS_REFERENCED" not in db_off.names()
    assert LexicalRetriever(XrefDatabase()).describe()["cross_references"] is False
    named, db_named = run("What does 21 CFR 101.13(b) require?")
    assert "ECFR_CROSS_REFERENCED" not in db_named.names()


def test_one_hop_only_a_linked_provision_is_never_a_seed():
    out, db = run(Q)
    assert db.names().count("ECFR_CROSS_REFERENCED") == 1
    seeds = dict(db.calls)["ECFR_CROSS_REFERENCED"]["section_number"]
    assert not set(seeds) & {"101.54", "101.60", "101.61", "101.62", "101.9"}


def test_the_statement_is_read_only_and_registered():
    stmt = sql_module.ALL_STATEMENTS["ECFR_CROSS_REFERENCED"]
    assert stmt.lstrip().upper().startswith("SELECT") and "cfr_cross_references" in stmt and "%(limit)s" in stmt
