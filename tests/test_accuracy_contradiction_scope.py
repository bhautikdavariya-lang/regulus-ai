"""Contradiction scope: what a modal and a negation GOVERN (Measurement Audit Phase 2F/2G).

A contradiction needs the claim and the evidence to disagree about the same
thing. Phase 2F found two places where the operators compared words rather
than what the words govern:

  H-003 (modality / means). "If you are an authorized user of CBP's ABI/ACE/ITDS,
  you may submit prior notice through either the ABI/ACE/ITDS interface or FDA
  PNSI" was compared, modal against modal, with 21 CFR 1.279(a) "you must submit
  the prior notice to FDA". The "may" chooses a CHANNEL for an act the evidence
  mandates; the evidence names no channel. Both claims were CONTRADICTED and a
  human-N=1 answer scored incorrect, 0. The captured text does not state the
  channel rule, so the claims are unverifiable - not contradicted.

  D-009 (negation scope). 21 CFR 211.113(a) "Appropriate written procedures,
  designed to prevent objectionable microorganisms in drug products not required
  to be sterile, shall be established and followed" was read as a NEGATED duty:
  the bare "not required" in "drug products not required to be sterile" modifies
  the products, it does not negate "shall be established". The polarity conflict
  removed the stating source and the claim was left unverifiable.

The negative controls pin the other side: a mandate that NAMES a channel still
conflicts with a permission to use another one.

Rows H-003 and D-009 use LEGACY_RECONSTRUCTED evidence (frozen acceptance-run
inputs), not an exact prompt-evidence snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

from regulus.accuracy import answer as AN
from regulus.accuracy import evaluate
from regulus.accuracy import operators as OP
from regulus.accuracy.alignment import LexicalAligner
from tests.test_accuracy_claim_extraction import Cov, Pkg, Src, judge

ROWS = {r["id"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_contradiction_rows.json").read_text(encoding="utf-8"))["rows"]}

CREDITED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}

R1279A = ("(a) Except as provided in paragraph (c) of this section, you must submit the prior notice to FDA and the "
          "prior notice submission must be confirmed by FDA for review as follows:")
H003_ABI = ("If you are an authorized user of CBP’s ABI/ACE/ITDS, you may submit prior notice through either the "
            "ABI/ACE/ITDS interface or FDA PNSI.")
H003_PNSI = "If you are not an authorized user, you may submit prior notice through FDA PNSI."
R211113A = ("(a) Appropriate written procedures, designed to prevent objectionable microorganisms in drug products not "
            "required to be sterile, shall be established and followed.")
D009_CLAIM = ("Written procedures shall include control of microbiological contamination to prevent objectionable "
              "microorganisms in drug products not required to be sterile.")


def frozen(row_id):
    r = ROWS[row_id]
    srcs = tuple(Src(s["index"], s["citation"], s["text"], s.get("heading"),
                     citation_fields=s.get("citation_fields") or {}) for s in r["sources"])
    reqs = tuple(tuple(x) for x in r.get("requirements") or ())
    pkg = Pkg(r["question"], srcs, reqs, tuple(r.get("satisfied_ids") or ()))
    cov = Cov(reqs, tuple(r.get("satisfied_ids") or ()), tuple(r.get("missing_labels") or ()), bool(r.get("explicit")))
    return evaluate(r["question"], r["answer"], package=pkg, coverage=cov, model_called=r["model_called"],
                    fallback_type=r["fallback_type"], aligner=LexicalAligner())


def claim_in(a, prefix):
    return next(c for c in a.checked["claims"] if c["claim"].startswith(prefix))


def conflicts(claim_text, evidence_text, authority=OP.BINDING):
    return [c["operator"] for c in OP.compare(claim_text, evidence_text, authority=authority).conflicts]


# ======================================================= A. H-003: a permission over the channel


def test_H003_a_permission_over_the_channel_does_not_conflict_with_the_mandate_it_serves():
    for claim_text in (H003_ABI, H003_PNSI):
        cmp = OP.compare(claim_text, R1279A)
        assert not cmp.conflicts, claim_text
        rel = [r for r in cmp.relations if r["operator"] == OP.CONFLICT_STRENGTH]
        assert rel and rel[0]["relation"] == "permission_over_means"
        assert (rel[0]["claim"], rel[0]["evidence"]) == (OP.PERMISSIVE, OP.MANDATORY)
        assert OP.CONFLICT_STRENGTH in cmp.undetermined


def test_H003_channel_claims_are_unverifiable_not_contradicted_and_the_answer_is_not_incorrect():
    a = frozen("H-003")
    for prefix in ("If you are an authorized user", "If you are not an authorized user"):
        c = claim_in(a, prefix)
        assert c["final"] != AN.CONTRADICTED and c["support"] == AN.UNVERIFIABLE, c["support_reason"]
    assert not [c for c in a.checked["claims"] if c["final"] == AN.CONTRADICTED]
    assert a.checked["answer_verdict"]["verdict"] != AN.INCORRECT


# ======================================================= B. D-009: an embedded "not required"


def test_D009_not_required_qualifying_the_products_does_not_negate_the_duty():
    assert OP.polarity(R211113A) == OP.AFFIRM
    assert OP.polarity(D009_CLAIM) == OP.AFFIRM
    assert "polarity" not in conflicts(D009_CLAIM, R211113A)


def test_D009_the_stating_source_211_113a_remains_usable_as_support():
    c = claim_in(frozen("D-009"), "Written procedures shall include control of microbiological contamination")
    assert c["support_basis"] in CREDITED, c["support_reason"]
    assert c["evidence"][0]["citation"] == "21 CFR 211.113(a)"
    assert c["final"] != AN.CONTRADICTED


def test_a_not_required_that_governs_the_duty_is_still_a_negation():
    # captured text, 21 CFR 117.136(a) (row F-003): the copula form is the negated duty
    assert OP.polarity("If you are a manufacturer/processor, you are not required to implement a preventive control "
                       "when you identify a hazard requiring a preventive control (identified hazard) and any of the "
                       "following circumstances apply:") == OP.NEGATE
    # captured text, 21 CFR 211.130 (row D-009)
    assert OP.polarity("Identification need not be applied to each individual container but shall be sufficient to "
                       "determine name, strength, quantity of contents, and lot or control number of each "
                       "container.") == OP.NEGATE


# ======================================================= C. a mandated channel is still a contradiction
# No captured regulation in the repository mandates one named channel and excludes the others, so these
# negative controls are CONSTRUCTED in the wording of 21 CFR 1.279; they assert the rule's boundary.

MANDATED_CHANNEL = ("You must submit the prior notice to FDA through FDA PNSI; prior notice submitted through "
                    "ABI/ACE/ITDS or by email is not accepted.")
MANDATED_CHANNEL_ONLY = "You must submit the prior notice to FDA through FDA PNSI."
OTHER_CHANNELS = "You may submit prior notice through either the ABI/ACE/ITDS interface or email."


def test_a_permission_to_use_channels_the_rule_excludes_is_still_a_contradiction():
    assert conflicts(OTHER_CHANNELS, MANDATED_CHANNEL)
    a = judge("How must prior notice be submitted?", OTHER_CHANNELS + " [1]", [("21 CFR 1.279(a)", MANDATED_CHANNEL)])
    assert a.checked["claims"][0]["final"] == AN.CONTRADICTED
    assert a.checked["answer_verdict"]["verdict"] == AN.INCORRECT


def test_a_mandate_that_names_its_channel_keeps_the_modal_conflict():
    """The channel exemption applies only when the mandate names no means of its own."""
    cmp = OP.compare(OTHER_CHANNELS, MANDATED_CHANNEL_ONLY)
    assert OP.CONFLICT_STRENGTH in [c["operator"] for c in cmp.conflicts]
    assert not [r for r in cmp.relations if r["relation"] == "permission_over_means"]
    a = judge("How must prior notice be submitted?", OTHER_CHANNELS + " [1]",
              [("21 CFR 1.279(a)", MANDATED_CHANNEL_ONLY)])
    assert a.checked["claims"][0]["final"] == AN.CONTRADICTED


def test_a_permission_without_a_means_or_over_another_act_is_still_a_modal_conflict():
    # no means marker: the permission is over the act itself (existing genuine control, 21 CFR 820.30(a) text)
    assert conflicts("Each manufacturer of any class III or class II device may establish procedures to control the "
                     "design of the device.",
                     "Each manufacturer of any class III or class II device shall establish procedures to control "
                     "the design of the device.") == ["strength"]
    # a means marker, but the permitted act is not the mandated one
    assert "strength" in conflicts("You may store the records using an electronic system.",
                                   "You must retain the records for 2 years.")
