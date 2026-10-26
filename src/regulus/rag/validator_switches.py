"""Validator precision switches (23 Oct 2026, holdout failure analysis, fix A).

Correct drafts were withheld by validator findings that are themselves false (9 of 63 non-PASS holdout answers).
REGULUS_VALIDATOR_PRECISION lists the fixes switched on, e.g. "A1,A2,A3"; the default is every fix that passed the gates,
"A1,A2,A3,A4,G1,S1,E1,C82,P1" since 26 Oct; "off" keeps the validator exactly as it was before them. Each
fix ships only after the exact replay of the recorded answers (holdout PASS rows unchanged or re-scored PASS, the named
misleading drafts still withheld) and a blind answer A/B.
  A1  a CFR citation whose number the evidence carries is not a figure ("§74.705(a)(1)" read as "74"). FD&C Act
      section numbers are left as figures: on the blind A/B (23 Oct) A1 over both released one misleading draft whose
      only finding was the false figure 605 (FDCA605-Q1, an invented reporting route); CFR-only keeps it withheld and
      still gains 82.1602 (exact replay: 6 answers changed, each already blind-scored or re-scored).
  A2  a scoped absence statement ("these provisions set no limit on the amount") is checked against the cited
      text's limiting terms instead of word overlap; unscoped denials stay errors
  A3  whole sentences that carry no citation and fail support (or repeat a supported sentence) are dropped and the
      rest re-validated, before the draft is handed back to the model; never on a truncated draft or one whose verdict
      says the evidence does not govern the question
  A4  a citation marker re-pointed to the one supplied source that IS the provision the sentence names first
      ("21 CFR 71.30(b) requires ... [1]" with [1] = 71.30(a) and [2] = 71.30(b)), when its words are that source's
Blind A/B (23 Oct, 170 recorded answers replayed, two scorers + adjudicator): A2+A3+A4 gained 3 PASS (70.10, 73.2120,
FDCA201(i)), lost none, released no misleading draft; A1 is held (above).
Answer post-processing fixes share the switch (failure analysis fix G):
  G1  duplicate removal keeps a repeated sentence that is part of a passage quoted verbatim from a supplied source
      (740.17: the full caution quoted twice lost three of its five sentences the second time)
  E1  a duty its cited source only requests or recommends ("is required to file" for 720.1's "is requested to file")
      is an error, and the draft goes back to the model with the source's own word (regulus.rag.claim_validation)
  S1  a cited provision's current status that its text does not carry (710/720 program closed, 740.18 stayed, no 606
      rule) is appended verbatim from data/reference/status_notes_v1.json (regulus.rag.status_notes)
  C82 a Part 82 certification listing that is one conformity sentence is answered from its text and the subpart's
      general section (regulus.rag.color_listing.compose_certification); for an FD&C (subpart B) certification
      question 82.5 joins as a companion and the answer says its 82.5(b)(1) limits govern; a provision named inside a
      verbatim quotation of the sentence's own cited source is not read as mis-cited (82.50 quoting "§ 82.5")
  P1  a cosmetics question about a manufacturing practice no general cosmetic provision and no cosmetics section of
      the Act mentions (calibration, pest control, cleaning SOPs, equipment certification - a search of the database
      text decides) is answered from FD&C Act 606 and 601 (and 610 for records) (regulus.rag.practice_silence).
      26 Oct: fires on 5 of the 1,211 section-benchmark questions (UC-004/005/008/010/012); blind two-lens scoring
      PASS 0 -> 5 on both lenses, exact replay of 228 recorded answers byte-identical
Fallback fix (26 Oct 2026; NOT in the default until its blind A/B passes):
  Q1  an answer that cannot be shown (withheld after validation, or a model decline although the provision was
      supplied) on a question whose provision is identified - named by it or resolved for it - gives that provision's
      paragraphs sharing most subject words with the question, verbatim and cited, instead of "not shown"
      (regulus.rag.fallback.focused_quote)
  FP1 a confirmation question ("..., correct?", "Does X require a 24-month ...?") that attributes to the identified
      provision a figure none of the supplied text states is answered "No", with the provision's paragraphs stating
      figures of that kind, verbatim (regulus.rag.premise_figures)
  RS1 a records question about identified 21 CFR sections whose full text has no record-keeping language is answered
      "sets no recordkeeping requirement", with what the section requires, verbatim (regulus.rag.records_silence)
  D1  a question asking what terms mean is answered with the supplied paragraphs that define every one of them,
      verbatim and cited (regulus.rag.definitions)
  ST1 the FD&C Act text a requested regulation itself cites ("section 403(i) of the act") joins the evidence after the
      regulation's own, at most two Act sections, within the hard ceiling (regulus.rag.section_promotion.statute_references)
  QM1 a section of the former Quality System regulation (820.30, 820.100 ...) is said not to be in the current eCFR, the
      live part 820 text that carries its subject is quoted, and the ISO 13485:2016 clause on that subject is named by
      number and title with its basis; a non-existent ISO 13485 clause is said not to exist (regulus.rag.qmsr)
Promotion fix (26 Oct 2026; NOT in the default until its live A/B passes):
  SP2 the picker's second regulation joins the first as a companion when it is in the same part, outside the cosmetics
      programme (regulus.rag.section_promotion.second_in_part): 300-question keys need more than one section for 21
      of 35 recorded picks; a same-part second pick was a key section 11 of 14 times
  C2  a condition stated in the supplied parent or child of a cited paragraph ("FDA may withdraw a qualified facility
      exemption if:" in 117.251(a) for a claim citing (a)(1)) counts as stated in the cited source; a sibling does not
      (regulus.rag.claim_validation). 26 Oct: 397 recorded answers, 6 changed, blind scored FAIL->PASS 2 (U-003, M-004),
      FAIL->PARTIALLY FAIL 3, unchanged 1, none worse
  PO2 a question naming only a 21 CFR part outside the cosmetics programme ("under Part 211") is resolved to its
      section(s) inside that part, as "Under Part 82, ..." is (regulus.rag.section_promotion.part_only_any): 74 of
      225 300-question dev rows; a key section ranks first inside the part for 57
Blind A/B (23 Oct evening; exact replay of 228 recorded answers, the 6 E1 corrections run live on Qwen3-4B; 20 changed
questions, plain + skeptic scorers, adjudicator on 7 splits): PASS 2 -> 7 (740.17 G1, 82.1602 A1, 710.3 S1, 82.1328 and
82.1330 C82), none lost, misleading 4 -> 2.
"""
from __future__ import annotations

import os

VALIDATOR_PRECISION = frozenset(x.strip().upper() for x in os.environ.get("REGULUS_VALIDATOR_PRECISION", "A1,A2,A3,A4,G1,S1,E1,C82,P1").split(",")
                                 if x.strip() and x.strip().lower() not in ("off", "none"))


def enabled(fix: str) -> bool:
    return fix in VALIDATOR_PRECISION
