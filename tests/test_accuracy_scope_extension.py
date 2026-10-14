"""A requirement the evidence applies "in either case" (whether or not / regardless of / irrespective of).

Incident: "What does 21 CFR 211.192 require?" was answered with "... shall be thoroughly investigated." - the
source's "whether or not the batch has already been distributed" dropped - and the live check gave it PASS 100,
because the condition vocabulary did not know a scope extension. Dropping one makes the rule read narrower than it
is (an investigation only before distribution), so it is an omission like any dropped condition.

Pinned: the dropped extension no longer passes; an extension kept verbatim or reworded still does; an extension
attached to something the claim does not state (a lead-in, acceptance row M-020) is not the claim's to repeat; a
claim adding an extension the evidence lacks is not supported by it; questions that do not reach the clause are
untouched.
"""

from __future__ import annotations

import pytest

from regulus.accuracy import operators as OP
from tests.test_accuracy_pass_integrity import production
from tests.test_accuracy_window_support import BROAD, FOCUSED, S1, S2, S3, S4, T211, claim_final

PASS = "pass"
DROPPED = S2.replace(", whether or not the batch has already been distributed", "")


def omitted(claim, evidence):
    return [o for o in OP.compare(claim, evidence).omissions if o["evidence"] == OP.SCOPE_EXTENSION]


# ------------------------------------------------------------- the incident

def test_the_answer_that_drops_the_clause_no_longer_passes_in_production():
    assert DROPPED != S2
    v, _, _ = production(BROAD, f"{S1} [1] {DROPPED} [1] {S3} [1] {S4} [1]", T211)
    assert v["status"] != PASS


def test_the_complete_answer_still_passes_in_production():
    v, _, _ = production(BROAD, f"{S1} [1] {S2} [1] {S3} [1] {S4} [1]", T211)
    assert v["status"] == PASS and v["live_check_score"] == 100


@pytest.mark.parametrize("kept", [
    "whether or not the batch has already been distributed",
    "regardless of whether the batch has already been distributed",
    "even if the batch has already been distributed",
    "whether the batch has been distributed or not",
])
def test_the_clause_kept_or_reworded_is_supported(kept):
    claim = S2.replace("whether or not the batch has already been distributed", kept)
    assert claim_final(FOCUSED, claim) == "supported"


def test_questions_that_do_not_reach_the_clause_are_untouched():
    for question, answer in [("What must the written record of an investigation under 21 CFR 211.192 include?", S4),
                             ("Under 21 CFR 211.192, who must review and approve production and control records?", S1)]:
        v, _, _ = production(question, answer + " [1]", T211)
        assert v["status"] == PASS


# ------------------------------------------------------------- the rule, beyond 211.192

def test_any_dropped_extension_is_an_omission():
    evidence = "Records shall be retained for the life of the device, regardless of whether the device is still marketed."
    assert omitted("Records must be retained for the life of the device.", evidence)
    assert not omitted("Records must be retained for the life of the device, even if it is no longer marketed.", evidence)
    assert not omitted("Records must be retained for the life of the device irrespective of whether it is marketed.",
                       evidence)


def test_an_extension_attached_to_what_the_claim_does_not_state_is_not_required():
    """M-020: one listed record item, against a lead-in whose "regardless of" modifies which complaints count."""
    lead_in = ("For complaints that the manufacturer determines must be investigated, and complaints that the "
               "manufacturer investigated regardless of those requirements, the manufacturer must record the "
               "following information:")
    assert not omitted("21 CFR 820.35 adds the date the complaint was received.", lead_in)
    assert not omitted("21 CFR 820.35 adds the name of the device.", lead_in)


def test_an_extension_only_the_claim_states_is_not_supported_by_the_evidence():
    r = OP.compare("Records must be retained, regardless of whether the device is still marketed.",
                   "Records shall be retained for the life of the device.")
    assert not r.conflicts                                       # not shown false ...
    assert "invented_condition" in r.undetermined                # ... and not shown true either
    assert not omitted("Records must be retained, regardless of whether the device is still marketed.",
                       "Records shall be retained for the life of the device.")
