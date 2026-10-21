"""Offline tests for the retrieval-only baseline harness (regulus.evaluation.retrieval_baseline). No DB, no model."""

import json

from regulus.evaluation import retrieval_baseline as RB
from regulus.retrieval.models import Citation, RetrievalResult


def _ecfr(section: str, paragraph: str = "") -> RetrievalResult:
    label = f"21 CFR {section}{paragraph}"
    return RetrievalResult(corpus="ecfr", text="x", heading=None, relevance_score=1.0, retrieval_method="full_text",
                           source_url=None, citation=Citation(corpus="ecfr", label=label, part=section.split(".")[0],
                                                              section=section, paragraph=paragraph or None),
                           key=f"ecfr:{section}:{paragraph}:0")


def _guidance(docket: str) -> RetrievalResult:
    return RetrievalResult(corpus="fda_guidance", text="x", heading=None, relevance_score=1.0, retrieval_method="full_text",
                           source_url="u", citation=Citation(corpus="fda_guidance", label="G", docket_number=docket),
                           key=f"fda_guidance:u#{docket}")


def _write_sources(tmp_path):
    v2 = tmp_path / "v2.jsonl"
    v2.write_text("\n".join(json.dumps(r) for r in [
        {"id": "retrieval-027", "category": "vocabulary_mismatch", "query": "design controls", "expected": ["21 CFR 820.10(c)"]},
        {"id": "retrieval-008", "category": "neg_invalid_reference", "query": "21 CFR 820.30(b)(1)", "expected": [],
         "identifier_exists_in_snapshot": False},
        {"id": "retrieval-022", "category": "cross_corpus", "query": "recall policy",
         "expected": ["21 CFR 7.40", "docket:FDA-2018-D-2074"]},
    ]) + "\n", encoding="utf-8")
    bench = tmp_path / "baseline.json"
    q = lambda qid, text, key, nc=False: {"question_id": qid, "question": text, "question_type": "Direct Lookup",  # noqa: E731
                                          "expected_citation_draft": key, "is_negative_control": nc, "key_is_verified": False}
    bench.write_text(json.dumps({"questions": [
        q("NC-001", "Summarize the requirements of 21 CFR 111.900.", "NO SUCH SECTION — 21 CFR 111.900 does not exist", True),
        q("D-016", "What are the requirements for labeling issuance and control?", "21 CFR 211.122; 211.125"),
        q("Z-004", "What applies to radiation-emitting products?", "21 CFR Part 1003; 21 CFR Part 1004"),
        q("C-001", "What does MoCRA require?", "FD&C Act 607 (MoCRA)"),
        q("S-007", "What are the water supply requirements for a dietary supplement facility?", "21 CFR 111.16"),
    ]}), encoding="utf-8")
    return v2, bench


def test_build_dataset_keeps_keys_unverified_and_never_parses_negative_controls(tmp_path):
    rows = {r["id"]: r for r in RB.build_dataset(*_write_sources(tmp_path))}
    assert all(r["sme_verified"] is False for r in rows.values())
    assert rows["NC-001"]["expected"] == [] and rows["NC-001"]["is_negative_control"]   # 111.900 is what must NOT be found
    assert rows["NC-001"]["key_status"] == RB.KEY_DRAFT
    assert rows["retrieval-008"]["is_negative_control"] and rows["retrieval-008"]["key_status"] == RB.KEY_DEVELOPER
    assert rows["D-016"]["expected"] == ["21 CFR 211.122", "21 CFR 211.125"] and rows["D-016"]["audit_failure_case"]
    assert rows["Z-004"]["expected_kinds"] == ["part"]
    assert rows["C-001"]["expected"] == [] and rows["C-001"]["key_status"] == RB.KEY_NONE and not rows["C-001"]["is_negative_control"]
    assert rows["S-007"]["expected"] == ["21 CFR 111.16"]                                 # the draft key is kept as the key
    assert rows["S-007"]["alternative_expected"] == ["21 CFR 111.15"]
    assert rows["S-007"]["alternative_key_status"] == RB.KEY_AUDIT
    assert rows["retrieval-022"]["expected_kinds"] == ["docket", "section"]


def test_target_kinds_and_matching_levels():
    assert [RB.target_kind(t) for t in ("21 CFR 812.3(m)", "21 CFR 812.3", "21 CFR part 1003", "docket:FDA-2018-D-2074")] == \
        ["paragraph", "section", "part", "docket"]
    sibling = _ecfr("812.3", "(n)")
    assert not RB.covers("21 CFR 812.3(m)", sibling)                     # provision level: (n) is not (m)
    assert RB.covers("21 CFR 812.3(m)", sibling, level="section")        # section level: any row of 812.3
    assert RB.covers("21 CFR 812.3(m)", _ecfr("812.3", "(m)(1)"))        # a subparagraph satisfies its parent
    assert RB.covers("21 CFR part 1003", _ecfr("1003.10"))
    assert RB.covers("docket:fda-2018-d-2074", _guidance("FDA-2018-D-2074"))
    assert not RB.covers("21 CFR 812.3", _guidance("FDA-2018-D-2074"))


def test_attribute_names_the_first_stage_a_target_fails():
    gold, other = _ecfr("211.125", "(a)"), _ecfr("107.50")
    common = dict(candidates=[other, gold], topk=[other, gold], model_called=True)
    assert RB.attribute("21 CFR 820.30", exists=False, selected=[], dropped=[], **common)["stage"] == RB.STAGE_CORPUS_GAP
    assert RB.attribute("21 CFR 312.20", exists=True, selected=[], dropped=[], **common)["stage"] == RB.STAGE_NOT_RETRIEVED
    d = RB.attribute("21 CFR 211.125", exists=True, selected=[(1, other)], dropped=[(gold, "soft_budget")], **common)
    assert (d["stage"], d["candidate_rank"], d["topk_rank"], d["drop_reasons"]) == (RB.STAGE_DROPPED, 2, 2, ["soft_budget"])
    p = RB.attribute("21 CFR 211.125", exists=True, selected=[(1, other), (2, gold)], dropped=[], **common)
    assert (p["stage"], p["prompt_indices"], p["reaches_prompt"]) == (RB.STAGE_IN_PROMPT, [2], True)
    blocked = RB.attribute("21 CFR 211.125", exists=True, selected=[(2, gold)], dropped=[],
                           candidates=[gold], topk=[gold], model_called=False)
    assert blocked["stage"] == RB.STAGE_CONTEXT_BLOCKED and not blocked["reaches_prompt"]
    lost = RB.attribute("21 CFR 211.125", exists=True, selected=[], dropped=[], **common)
    assert lost["stage"] == RB.STAGE_UNATTRIBUTED


def _record(rid, cls, source, *, stage_target=None, negative=False, total=3600, guidance=2400):
    targets = [] if stage_target is None else [stage_target]
    return {"id": rid, "source": source, "question": "q", "category": "c", "key_status": RB.KEY_DRAFT, "sme_verified": False,
            "is_negative_control": negative, "audit_failure_case": False, "expected": [t["target"] for t in targets],
            "alternative_expected": [], "alternative_key_status": None, "key_text": "", "question_class": cls,
            "plan": {"named": []}, "targets": targets, "alternative_targets": [], "named_identifiers": [],
            "retrieval": {"exact_cfr_in_topk": 1 if negative else 0, "exact_cfr_in_topk_excluding_parent_rows": 0},
            "context": {"sources": 4, "total_chars": total, "ecfr_chars": total - guidance, "guidance_chars": guidance,
                        "soft_budget_chars": 3600},
            "gate": {"state": "UNKNOWN", "blocked": False, "scope": "in_scope", "pre_generation_fallback": None},
            "model_would_be_called": True, "timings": {"wall_ms": 12.3}}


def test_summary_splits_identifier_from_plain_language_and_excludes_negatives():
    hit = RB.attribute("21 CFR 11.10", exists=True, candidates=[_ecfr("11.10")], topk=[_ecfr("11.10")],
                       selected=[(1, _ecfr("11.10"))], dropped=[], model_called=True)
    miss = RB.attribute("21 CFR 312.20", exists=True, candidates=[], topk=[], selected=[], dropped=[], model_called=True)
    recs = [_record("a", RB.CLASS_IDENTIFIER, RB.SOURCE_V2, stage_target=hit),
            _record("b", RB.CLASS_PLAIN, RB.SOURCE_BENCHMARK, stage_target=miss),
            _record("c", RB.CLASS_PLAIN, RB.SOURCE_BENCHMARK, stage_target=hit),
            _record("nc", RB.CLASS_IDENTIFIER, RB.SOURCE_BENCHMARK, negative=True)]
    summary = RB.summarise(recs)
    m = summary["metrics"]
    ident, plain = m["identifier"]["section_level"], m["plain_language"]["section_level"]
    (nc,) = summary["negative_controls"]["rows"]                               # a parent row alone fails the old rule only
    assert (nc["retrieval_eval_rule_passed"], nc["rule_passed_excluding_parent_rows"]) == (False, True)
    assert ident["n"] == 1 and ident["any_reaches_prompt"]["count"] == 1        # the negative control is not scored
    assert plain["n"] == 2 and plain["any_in_candidates"]["count"] == 1 and plain["any_in_context"]["rate"] == 0.5
    assert plain["context_budget"]["guidance_share_of_context_chars"] == round(4800 / 7200, 4)
    assert m["plain_language"]["targets_section_level"]["stages"][RB.STAGE_NOT_RETRIEVED] == 1


def test_canonical_hash_ignores_timings_only():
    a = _record("a", RB.CLASS_PLAIN, RB.SOURCE_V2)
    b = {**a, "timings": {"wall_ms": 999.0}}
    assert RB.canonical_sha256([a]) == RB.canonical_sha256([b])
    assert RB.canonical_sha256([a]) != RB.canonical_sha256([{**a, "question_class": RB.CLASS_IDENTIFIER}])
