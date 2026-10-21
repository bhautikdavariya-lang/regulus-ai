"""Per-required-provision stage attribution (regulus.evaluation.provision_trace) and the run's corpus identity
(regulus.traceability.corpus). The trace reads a measurement record as written by regulus.traceability.measurement."""

from regulus.evaluation.provision_trace import (
    KEY_DRAFT,
    STAGE_CITED,
    STAGE_CORPUS_GAP,
    STAGE_DROPPED,
    STAGE_IN_PROMPT,
    STAGE_NOT_RETRIEVED,
    covers,
    parse_provision,
    summarise,
    trace_record,
)
from regulus.traceability import corpus


def record(selected=(), dropped=(), prompt=(), cited=()):
    """A measurement record reduced to the fields the trace reads."""
    return {"question_id": "Q-1",
            "evidence": {"selection": {"selected": [{"citation": c} for c in selected],
                                       "dropped": [{"citation": c, "reason": r} for c, r in dropped]},
                         "snapshot": {"items": [{"index": i, "citation": c} for i, c in enumerate(prompt, start=1)]}},
            "citations": [{"index": i, "indices": [i], "cited_in_answer": True} for i in cited]}


def test_labels_parse_and_a_provision_is_covered_only_by_itself_or_its_subparagraphs():
    assert parse_provision("21 CFR 70.3(f)") == ("70.3", "(f)") and parse_provision("211.134") == ("211.134", "")
    assert parse_provision("FDA Guidance: Lead in Cosmetic Lip Products") is None
    f = ("70.3", "(f)")
    assert covers(("70.3", "(f)"), f) and covers(("70.3", "(f)(1)"), f)
    assert not covers(("70.3", "(g)"), f) and not covers(("70.3", ""), f) and not covers(("70.30", "(f)"), f)
    assert covers(("211.134", "(a)"), ("211.134", "")) and covers(("211.134", ""), ("211.134", ""))


def test_each_provision_gets_the_first_stage_it_fails_to_pass():
    rec = record(selected=["21 CFR 3.2(e)", "21 CFR 4.1"],
                 dropped=[("21 CFR 4.2", "max_results"), ("21 CFR 4.2", "soft_budget"), ("FDA Guidance: X", "soft_budget")],
                 prompt=["21 CFR 3.2(e)", "21 CFR 4.1"], cited=[1])
    by = {t.provision: t for t in trace_record(rec, ["21 CFR 3.2(e)", "21 CFR 4.1", "21 CFR 4.2", "21 CFR 4.4"])}
    assert by["21 CFR 3.2(e)"].stage == STAGE_CITED and by["21 CFR 3.2(e)"].cited_indices == (1,)
    assert by["21 CFR 4.1"].stage == STAGE_IN_PROMPT and by["21 CFR 4.1"].prompt_indices == (2,)
    assert by["21 CFR 4.2"].stage == STAGE_DROPPED and by["21 CFR 4.2"].drop_reasons == ("max_results", "soft_budget")
    assert by["21 CFR 4.2"].candidate_rank == 3
    assert by["21 CFR 4.4"].stage == STAGE_NOT_RETRIEVED and by["21 CFR 4.4"].key_status == KEY_DRAFT


def test_a_section_missing_from_the_corpus_is_a_corpus_gap_and_the_summary_counts_provisions():
    traces = trace_record(record(), ["21 CFR 70.5(a)", "21 CFR 999.1"], corpus_sections={"70.5"})
    assert [t.stage for t in traces] == [STAGE_NOT_RETRIEVED, STAGE_CORPUS_GAP]
    s = summarise(traces)
    assert s["provisions"] == 2 and s["questions"] == 1 and s["stages"][STAGE_CORPUS_GAP] == 1


class FakeDb:
    def __init__(self):
        self.statements = []

    def query(self, statement, params=None):
        self.statements.append(statement)
        return [{"rows": 3, "sha256": "ab"}]


def test_corpus_identity_is_read_only_and_names_the_semantic_index():
    db = FakeDb()
    ident = corpus.corpus_identity(db)
    assert set(ident) == {"ecfr", "guidance", "semantic_index"} and ident["ecfr"]["sha256"] == "ab"
    assert all(s.lstrip().upper().startswith("SELECT") for s in db.statements)
    assert ident["semantic_index"]["name"] == "semantic_expanded_v1"
