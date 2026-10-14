"""Regulatory content support gate (Measurement Audit Phase 2D).

Invariant: evidence receives support credit only after it has independently
established the core proposition the claim expresses. A condition mismatch is a
DOWNGRADE of an established proposition, never a way of establishing one.

Phase 2C hand-labelled 121 non-exact support decisions on the frozen 60 rows:
38 were false (26 partial verdicts granted by the omission shortcut to passages
that did not state the claim; 12 supports that substituted the claim's object,
dropped its condition, or read a structural label as content) and 83 were safe.
The fixture freezes those rows and labels. The semantic aligner cannot run here
(it needs the embedding model), so its selection is reproduced by a lexical
aligner that ranks the source it chose first: on all 203 labelled aligner
instances this reproduces the full semantic run exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.accuracy import evaluate
from regulus.accuracy import operators as OP
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import LexicalAligner
from tests.test_accuracy_claim_extraction import Cov, Pkg, Src, judge

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "accuracy_content_gate_rows.json").read_text(encoding="utf-8"))
ROWS = {r["id"]: r for r in FIXTURE["rows"]}
DECISIONS = FIXTURE["decisions"]

CREDITED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
SUPPORT_BASES = CREDITED - {"drops_a_condition"}
# Phase 2C's "correct verdict" for these two false SUPPORTS is a partial: E-005's
# item drops "as appropriate"; C-002's conjunction states half of what 701.11 says.
# Either a partial or no credit prevents the false support.
CORRECT_AS_PARTIAL = {"list01", "para11"}
# The one documented conservative loss (Phase 2C report): "21 CFR 117.160(a)
# requires validation of preventive controls" against "You must validate that
# ..." - the noun/verb pair validation/validate is not equated by the stemmer.
DOCUMENTED_CONSERVATIVE = {"drop15"}


class Prefer(LexicalAligner):
    """Lexical scores, one citation ranked first whenever it is a candidate."""

    def __init__(self, citation):
        self.citation = citation

    def align(self, claim, candidates, *, top_k=3):
        found = super().align(claim, candidates, top_k=len(candidates))
        found.sort(key=lambda a: a.passage.citation != self.citation)
        return found[:top_k]


_RUNS: dict = {}


def frozen(row_id, aligner_key="lexical"):
    """The row evaluated as the frozen run did: 'lexical', or a citation the
    (semantic) aligner ranked first."""
    key = (row_id, aligner_key)
    if key not in _RUNS:
        r = ROWS[row_id]
        srcs = tuple(Src(s["index"], s["citation"], s["text"], s.get("heading"),
                         citation_fields=s.get("citation_fields") or {}) for s in r["sources"])
        reqs = tuple(tuple(x) for x in r.get("requirements") or ())
        pkg = Pkg(r["question"], srcs, reqs, tuple(r.get("satisfied_ids") or ()))
        cov = Cov(reqs, tuple(r.get("satisfied_ids") or ()), tuple(r.get("missing_labels") or ()), bool(r.get("explicit")))
        aligner = LexicalAligner() if aligner_key == "lexical" else Prefer(aligner_key)
        _RUNS[key] = evaluate(r["question"], r["answer"], package=pkg, coverage=cov, model_called=r["model_called"],
                              fallback_type=r["fallback_type"], aligner=aligner)
    return _RUNS[key]


def decided(decision):
    """(basis, source, claim record) now, for one labelled decision; None when
    the sentence is no longer a claim."""
    a = frozen(decision["row"], "lexical" if decision["aligner"] == "lexical" else decision["source"])
    c = next((c for c in a.checked["claims"] if c["claim"] == decision["claim"]), None)
    if c is None:
        return None
    return c["support_basis"], ((c.get("evidence") or [{}])[0]).get("citation"), c


def gate_of(c):
    return (c.get("operator_trace") or {}).get("content_gate") or {}


def claim_in(a, text):
    return next(c for c in a.checked["claims"] if text in c["claim"])


def labelled(idx):
    return [d for d in DECISIONS if d["idx"] == idx]


# ============================================== the frozen Phase 2C labels


def test_fixture_is_the_phase_2c_labelled_set():
    unique = {d["idx"]: d["label"] for d in DECISIONS}
    assert len(unique) == 121
    labels = sorted(unique.values())
    assert labels.count("FALSE_PARTIAL") == 26 and labels.count("FALSE_SUPPORT") == 12
    assert labels.count("SAFE_SUPPORT") == 71 and labels.count("SAFE_PARTIAL") == 12


@pytest.mark.parametrize("decision", [d for d in DECISIONS if d["label"].startswith("FALSE")],
                         ids=lambda d: f"{d['idx']}-{d['row']}-{d['aligner']}")
def test_all_38_false_decisions_are_prevented(decision):
    now = decided(decision)
    if now is None:
        return                                            # no longer a claim (D-004's list lead)
    basis, source, _ = now
    if decision["idx"] in CORRECT_AS_PARTIAL:
        assert basis not in SUPPORT_BASES, f"still supported: {basis} from {source}"
        return
    if decision["label"] == "FALSE_PARTIAL":
        assert basis not in CREDITED, f"still credited: {basis} from {source}"
    else:
        assert not (basis in CREDITED and source == decision["source"]), f"same false credit: {basis} from {source}"


@pytest.mark.parametrize("decision", [d for d in DECISIONS if d["label"].startswith("SAFE")],
                         ids=lambda d: f"{d['idx']}-{d['row']}-{d['aligner']}")
def test_the_83_safe_decisions_are_preserved_except_the_documented_one(decision):
    basis, source, _ = decided(decision)
    if decision["idx"] in DOCUMENTED_CONSERVATIVE:
        assert basis not in CREDITED
        return
    if decision["basis"] == "drops_a_condition":
        assert basis == "drops_a_condition"
    else:
        assert basis in SUPPORT_BASES
    assert source == decision["source"]


# ======================================================= named acceptance rows


def test_B003_object_substitution_application_vs_information_is_blocked():
    for d in labelled("para05") + labelled("para01"):
        basis, _, c = decided(d)
        assert basis not in CREDITED
        g = gate_of(c)
        assert g["content_gate_verdict"] == "blocked"
        assert "applic" in g["distinguishing_terms"]
        assert "21 CFR 601.12(a)" in g["distinguishing_term_sources"]["applic"]
        assert g["core_object_match"] is False


def test_C002_commodity_identity_are_not_supported_by_701_12():
    for d in labelled("para11"):
        basis, _, c = decided(d)
        assert basis not in SUPPORT_BASES
        g = gate_of(c)
        assert g["content_gate_verdict"] == "blocked"
        assert {"commod", "ident"} <= set(g["distinguishing_terms"])
        assert "21 CFR 701.11(a)" in g["distinguishing_term_sources"]["commod"]


def test_C004_bithionol_is_not_supported_by_the_chlorofluorocarbon_section():
    for d in labelled("para13"):
        basis, _, c = decided(d)
        assert basis not in CREDITED
        assert "21 CFR 700.11(a)" in gate_of(c)["distinguishing_term_sources"]["bithionol"]


@pytest.mark.parametrize("aligner_key", ["lexical", "21 CFR 700.14(a)"])
def test_C004_anaphora_these_ingredients_is_preserved_under_both_aligners(aligner_key):
    c = claim_in(frozen("C-004", aligner_key), "These ingredients are deemed to be adulterated")
    assert c["support_basis"] in SUPPORT_BASES
    assert not gate_of(c)["distinguishing_terms"]
    assert [m["source"] for m in c["citation_trace"]["markers"] if m["supports"]] == ["21 CFR 700.11(a)"]


def test_D007_packaging_and_labeling_operations_is_not_credited_to_211_122():
    for d in labelled("para18"):
        basis, source, c = decided(d)
        assert not (basis in CREDITED and source == "21 CFR 211.122(a)")
        if d["aligner"] == "semantic":
            assert "oper" in gate_of(c)["distinguishing_terms"]


def test_F007_monitoring_claim_is_not_partial_on_the_verification_passage():
    for idx in ("drop19", "para39"):
        for d in labelled(idx):
            basis, _, c = decided(d)
            assert basis not in CREDITED
            assert gate_of(c)["content_gate_verdict"] == "blocked"


def test_F007_management_components_restated_from_117_140_stays_partial():
    for d in labelled("drop18"):
        basis, source, c = decided(d)
        assert (basis, source) == ("drops_a_condition", "21 CFR 117.140(a)")
        g = gate_of(c)
        assert g["content_gate_verdict"] == "established_terms_only"
        assert g["operator_silent_passage"] is True
        assert g["material_omissions"] and g["condition_match"] is False


def test_F009_definition_claims_are_not_partial_on_the_management_components_passage():
    for idx in ("drop20", "drop21", "drop22", "drop23", "drop24"):
        for d in labelled(idx):
            basis, _, c = decided(d)
            assert basis not in CREDITED, idx
            assert gate_of(c)["distinguishing_terms"], idx


def test_F022_supply_chain_claims_get_no_partial_credit():
    for idx in ("drop26", "drop27", "drop28", "drop29", "drop30", "drop31", "drop32", "drop33"):
        for d in labelled(idx):
            assert decided(d)[0] not in CREDITED, idx


def test_F003_subpart_b_label_must_be_established_by_the_source():
    for d in labelled("list02"):
        assert decided(d)[0] not in CREDITED
    for idx in ("drop07", "drop08", "drop09", "drop10", "drop11", "drop12", "drop17"):
        for d in labelled(idx):
            assert decided(d)[0] not in CREDITED, idx


def test_F003_operator_silent_passage_founds_a_partial_but_never_a_full_support():
    a = frozen("F-003", "21 CFR 117.140(a)")
    c = claim_in(a, "21 CFR 117.140(a) requires preventive control management components")
    assert c["support_basis"] == "drops_a_condition"
    # "(a) Corrective action procedures." holds every term and states no rule
    c = claim_in(frozen("F-003"), "21 CFR 117.150(a) requires corrective action procedures")
    assert c["support_basis"] not in CREDITED
    assert gate_of(c)["content_gate_verdict"] == "established_terms_only"


def test_E005_list_item_that_drops_as_appropriate_is_partial_not_supported():
    for d in labelled("list01"):
        basis, source, c = decided(d)
        assert (basis, source) == ("drops_a_condition", "21 CFR 11.30")
        assert c["match_path"] == "list_item"
        g = gate_of(c)
        assert g["condition_match"] is False and g["material_omissions"]


def test_E005_replacement_reagent_policy_is_not_partial_on_11_30():
    for d in labelled("drop06"):
        basis, _, c = decided(d)
        assert basis not in CREDITED
        g = gate_of(c)
        assert g["content_gate_verdict"] == "not_established"
        assert g["support_block_reason"]


def test_B005_dropped_proviso_and_recipient_is_not_supported():
    for d in labelled("desc00"):
        basis, _, _ = decided(d)
        assert basis not in CREDITED


def test_F012_validation_is_not_supported_by_a_verification_window():
    for d in labelled("adja01"):
        basis, _, c = decided(d)
        assert basis not in CREDITED
        assert "valid" in gate_of(c)["distinguishing_terms"]


def test_D004_content_free_list_lead_is_a_non_claim():
    for d in labelled("para14"):
        assert decided(d) is None
    for idx in ("drop01", "drop02"):
        for d in labelled(idx):
            assert decided(d)[0] not in CREDITED


def test_M034_design_history_file_is_not_partial_on_820_45():
    for d in labelled("drop34"):
        basis, _, c = decided(d)
        assert basis not in CREDITED
        assert "21 CFR 820.10" in gate_of(c)["distinguishing_term_sources"]["design"]


# ================================================== synthetic rule cases

RETAIN = ("21 CFR 211.180(a)", "Any production, control, or distribution record that is required to be maintained in "
          "compliance with this part shall be retained for at least 1 year after the expiration date of the batch.")
COMPLAINTS = ("21 CFR 211.198(a)", "Written procedures describing the handling of all written and oral complaints "
              "regarding a drug product shall be established and followed.")
STORE = ("21 CFR 606.65", "All supplies and reagents used in the collection, processing, compatibility testing, storage "
         "and distribution of blood and blood components shall be stored in a safe, sanitary and orderly manner.")
EQUIPMENT = ("21 CFR 606.60(a)", "Equipment used in the collection, processing, compatibility testing, storage and "
             "distribution of blood and blood components shall be maintained in a clean and orderly manner and located "
             "so as to facilitate cleaning and maintenance.")
INFORM = ("21 CFR 601.12(a)", "An applicant must inform FDA about each change in the product, production process, "
          "quality controls, equipment, facilities, responsible personnel, or labeling established in the approved "
          "license application.")
ANNUAL = ("21 CFR 601.28", "Sponsors of licensed biological products shall submit the following information each year "
          "within 60 days of the anniversary date of approval of the license to the Director.")
OPEN = ("21 CFR 11.30", "Persons who use open systems to create, modify, maintain, or transmit electronic records shall "
        "employ procedures and controls designed to ensure the authenticity, integrity, and, as appropriate, the "
        "confidentiality of electronic records.")
PROVISO = ("21 CFR 606.110(a)", "The use of plateletpheresis and leukapheresis procedures to obtain a product for a "
           "specific recipient may be at variance with the additional standards for specific products prescribed in "
           "this part provided that the physician determines that the donor's health permits plateletpheresis or "
           "leukapheresis.")
STEM = ("The use of plateletpheresis and leukapheresis procedures to obtain a product for a specific recipient may be at "
        "variance with the additional standards for specific products prescribed in this part")


def only(a):
    (c,) = a.checked["claims"]
    return c


def test_paraphrase_control_kept_records_for_maintained_records_is_supported():
    c = only(judge("How long must records be retained?",
                   "Production, control, and distribution records required to be kept under this part must be retained "
                   "for at least 1 year after the expiration date of the batch.", [RETAIN, COMPLAINTS]))
    assert c["support_basis"] == "paraphrase"
    assert gate_of(c)["content_gate_verdict"] == "established"
    assert gate_of(c)["distinguishing_terms"] == []


def test_paraphrase_control_safely_for_in_a_safe_manner_is_supported():
    c = only(judge("How must supplies be stored?",
                   "Supplies and reagents used in processing blood components must be stored safely, sanitarily and "
                   "orderly.", [STORE, EQUIPMENT]))
    assert c["support_basis"] == "paraphrase"
    assert gate_of(c)["distinguishing_terms"] == []


def test_paraphrase_control_files_for_records_is_not_a_distinguishing_term():
    # "files" appears in no source, so nothing contrasts it: absent, not distinguishing
    p = VD.Passage(1, "21 CFR 211.180(a)", "exact", RETAIN[1])
    assert VD.distinguishing_terms("Production files must be retained for at least 1 year after the expiration date.",
                                   p, [p, VD.Passage(2, "21 CFR 211.198(a)", "exact", COMPLAINTS[1])]) == {}


def test_object_substitution_is_blocked_with_its_contrasting_source():
    c = only(judge("When must the annual report be submitted?",
                   "The application must be submitted within 60 days of the anniversary date of approval of the license.",
                   [INFORM, ANNUAL]))
    assert c["support_basis"] not in CREDITED
    g = gate_of(c)
    assert g["content_gate_verdict"] == "blocked"
    assert g["distinguishing_term_sources"] == {"applic": ["21 CFR 601.12(a)"]}


def test_generic_terms_never_distinguish():
    # "requires", "FDA", "regulation" are framing: present elsewhere, absent here, still not distinguishing
    p = VD.Passage(1, "21 CFR 211.180(a)", "exact", RETAIN[1])
    other = VD.Passage(2, "21 CFR 601.12(a)", "exact", INFORM[1] + " The regulation requires it.")
    assert VD.distinguishing_terms("FDA regulation requires that records be retained for at least 1 year after the "
                                   "expiration date of the batch.", p, [p, other]) == {}


def test_condition_dropped_from_an_established_proposition_is_partial():
    c = only(judge("What controls apply to open systems?",
                   "Persons who use open systems to create, modify, maintain, or transmit electronic records shall employ "
                   "procedures and controls designed to ensure the authenticity, integrity, and the confidentiality of "
                   "electronic records.", [OPEN]))
    assert c["support_basis"] == "drops_a_condition"
    g = gate_of(c)
    assert g["content_gate_verdict"] == "established" and g["condition_match"] is False


def test_condition_mismatch_without_content_support_is_not_partial():
    c = only(judge("What applies to open systems?", "The Replacement Reagent Policy applies only to open systems.", [OPEN]))
    assert c["support_basis"] not in CREDITED
    assert gate_of(c)["content_gate_verdict"] == "not_established"


def test_bare_paragraph_heading_never_gives_full_support():
    c = only(judge("What does 117.150(a) require?",
                   "Under 21 CFR 117.150(a), facilities are required to have corrective action procedures in place.",
                   [("21 CFR 117.150(a)", "(a) Corrective action procedures."),
                    ("21 CFR 117.130(a)", "(a) Requirement for a hazard analysis.")]))
    assert c["support_basis"] not in CREDITED


# ------------------------------------------------------------ "provided that"


def test_provided_that_is_a_condition():
    assert OP.PROVIDED_THAT in OP.conditions(PROVISO[1])
    assert OP.PROVIDED_THAT in OP.conditions("It may be used, provided further that the label says so.")
    assert OP.PROVIDED_THAT in OP.conditions("It may be used on condition that the label says so.")


def test_claim_without_the_proviso_is_partial():
    c = only(judge("q", STEM + ".", [PROVISO]))
    assert c["support_basis"] == "drops_a_condition"
    assert "provided that" in c["support_reason"]


def test_claim_with_the_proviso_is_supported():
    c = only(judge("q", STEM + " provided that the physician determines that the donor's health permits it.", [PROVISO]))
    assert c["support_basis"] in SUPPORT_BASES


@pytest.mark.parametrize("equivalent", ["on condition that", "only if", "as long as"])
def test_equivalent_proviso_wording_is_preserved(equivalent):
    assert OP.condition_preserved(OP.PROVIDED_THAT, f"{STEM}, {equivalent} the physician approves.")
    c = only(judge("q", f"{STEM}, {equivalent} the physician determines that the donor's health permits "
                        "plateletpheresis or leukapheresis.", [PROVISO]))
    assert c["support_basis"] != "drops_a_condition"


def test_nested_conditions_each_must_be_kept():
    nested = ("21 CFR 606.110(a)", PROVISO[1][:-1] + ", unless the donor is a minor.")
    cmp = OP.compare(STEM + " provided that the physician approves.", nested[1])
    assert [o["evidence"] for o in cmp.omissions] == ["unless"]
    cmp = OP.compare(STEM + ", unless the donor is a minor.", nested[1])
    assert [o["evidence"] for o in cmp.omissions] == [OP.PROVIDED_THAT]


def test_a_proviso_only_the_claim_states_is_recorded_not_a_conflict():
    cmp = OP.compare(STEM + " provided that the physician approves.", STEM + ".")
    assert not cmp.conflicts
    assert any(r["relation"] == "proviso_not_in_evidence" for r in cmp.relations)


# --------------------------------------------------------------- trace


TRACE_FIELDS = {"content_gate_verdict", "distinguishing_terms", "distinguishing_term_sources", "core_object_match",
                "core_subject_match", "core_action_match", "core_actor_match", "condition_match", "material_omissions", "content_support_reason",
                "support_block_reason", "candidate_selection"}


def test_every_gated_claim_carries_the_full_trace_and_a_match_path():
    a = frozen("F-003")
    gated = [c for c in a.checked["claims"] if gate_of(c)]
    assert gated
    for c in gated:
        assert TRACE_FIELDS <= set(gate_of(c)), c["claim"]
        assert c["match_path"] in {"sentence", "descriptive", "list_item", "adjacent_window"}
        # selection and support are separate records
        assert gate_of(c)["candidate_selection"]["passage"]


def test_descriptive_path_records_the_gate():
    c = only(judge("q", f"{STEM}, on condition that the physician determines that the donor's health permits "
                        "plateletpheresis or leukapheresis.", [PROVISO]))
    assert c["support_basis"] == "descriptive"
    assert c["match_path"] == "descriptive"
    assert gate_of(c)["content_gate_verdict"] == "established"
    assert TRACE_FIELDS <= set(gate_of(c))
