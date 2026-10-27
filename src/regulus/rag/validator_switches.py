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
Fallback fixes (26 Oct 2026; in the default since 27 Oct):
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
Promotion fixes (26 Oct 2026; C2, Q2, PR2 and PO2 in the default since 27 Oct, SP2 and SA1 off):
  SP2 the picker's second regulation joins the first as a companion when it is in the same part, outside the cosmetics
      programme (regulus.rag.section_promotion.second_in_part): 300-question keys need more than one section for 21
      of 35 recorded picks; a same-part second pick was a key section 11 of 14 times
  C2  a condition stated in the supplied parent or child of a cited paragraph ("FDA may withdraw a qualified facility
      exemption if:" in 117.251(a) for a claim citing (a)(1)) counts as stated in the cited source; a sibling does not
      (regulus.rag.claim_validation). 26 Oct: 397 recorded answers, 6 changed, blind scored FAIL->PASS 2 (U-003, M-004),
      FAIL->PARTIALLY FAIL 3, unchanged 1, none worse
  SA1 a question outside the cosmetics programme is offered, after the regulations, the 3 FD&C Act sections it is most
      about (lexical + paragraph-embedding order; 301 never), as a cosmetics question is offered chapter VI
      (regulus.rag.section_promotion.general_act_offered): 25 of 225 300-question dev rows are keyed to the Act; the key
      Act section is offered for 18 of the 19 general ones
  Q2  Q1's quotation for a section the picker chose, when the reranker scores it at least 0.6, under a lead that does
      not claim it is the provision the question concerns (regulus.rag.pipeline.Q2_MIN_RERANK). 26 Oct: 25 recorded
      withheld answers; without the score floor 3 PASS declines (must-refuse, false premise, out of scope) were lost
  PR2 the yes/no premise check ignores words used in 40 or more of Title 21's sections ("instead", "outer", "appear"):
      ordinary regulatory English is not a premise (regulus.rag.premise_vocabulary). 26 Oct: 397 recorded answers, 9
      changed; blind scored FAIL->PASS 4, FAIL->PARTIALLY PASS 1, unchanged 4, none worse
  PO2 a question naming only a 21 CFR part outside the cosmetics programme ("under Part 211") is resolved to its
      section(s) inside that part, as "Under Part 82, ..." is (regulus.rag.section_promotion.part_only_any): 74 of
      225 300-question dev rows; a key section ranks first inside the part for 57
  ND1 (27 Oct) the bare decline sentence ("The available regulatory sources do not provide enough information to
      answer this.") is removed from an answer that states something cited without it (regulus.rag.pipeline.
      drop_stray_decline): 9 of 154 answers of the 26 Oct full run were scored down for that contradictory line
Fixes of 27 Oct 2026 (first 50 cosmetics main questions, the 26 Oct follow-up verdicts):
  DF1 a question asking how FDA's definitions classify what it describes ("Are these 'color additives' in FDA's
      sense?") is resolved to the definition paragraphs of 70.3 / 700.3 / 82.3 it names, with the paragraph limiting
      a definition and the short definitions a matched one-word term uses (SectionPromoter.definitions_asked): the 5
      bank questions it fires on get exactly their key paragraphs; 0 of 300 acceptance questions
  EY1 an unnamed color whose listing the question says does not provide for eye-area use: 70.5(a), not a guessed
      listing
  MF1 "$75" is the source's "$75.00": a whole amount equals the same amount with zero decimals (figure check)
  E2  E1 for a sentence with no citation marker that names the section ("720.1 still requires a filing"), or as the
      answer's opening sentence says it of the supplied provisions
  CM1 a sentence naming a provision that its cited source itself names ("the fee for listing a diluent under
      § 80.35" citing 70.19(j)) is not a provision-citation mismatch
  LV1 "list"/"listing" asks for an enumeration only as an instruction or followed by what to enumerate: in Parts
      70-82 "petitioning to list a colorant" is approval, and the question was read as "every paragraph of 70.19"
      (64 of 1,962 bank, follow-up and 300Q questions change, all from enumeration)
  FU2 a demonstrative with a subject word ("this color", "that exemption") points back to the conversation unless the
      question introduced it itself; FU2B a follow-up of at most 3 subject words naming nothing continues the
      conversation (resolution harness, 1,000 dev follow-ups: anchored with the key's section 512 -> 523, false
      anchoring of a new main question 22 -> 22). FU3 (the follow-up's own top-ranked section as a companion) was
      measured and dropped: 55 added, 5 in the key. FU2C: shared subject words alone do not anchor a question of more
      than 12 subject words with no pointer back (false anchors 22 -> 20, no correct anchor lost)
  FU2D a color named in a conversation anchored to a general section (82.51 lakes, 81.30, 82.50) does not make the
      follow-up a new question unless it asks whether that color may be used (harness: +8 correct anchors, 0 false;
      all FU2 rules together: anchored with the key's section 512 -> 531, false anchors 22 -> 20 of 1,000)
  CS1 a color additive regulation (Parts 70-82, which carry out section 721) is not given MoCRA's 603-614 as a
      co-promoted Act section (5 of 16 Part 70 questions got 607/608/609, filling the budget)
  FS2 (off) follow-up subject words stemmed by PostgreSQL's Snowball English stemmer (the retrieval index's) instead of
      the suffix rule: right in itself, but on the harness +6 correct anchors for +6 false ones at today's thresholds
  RO1 the picker reads the regulation candidates reordered by reciprocal-rank fusion of lexical rank and the
      cross-encoder's score (reorder-then-pick); the veto reuses the same scores
  V2  a reranker veto in a near tie (within 0.05) takes the picker's own other choice instead of the reranker's top
  UR1 the listing composer reads the uses paragraph under each heading the listings use ("Uses and restrictions.",
      "Use and restrictions.", "Use and restriction."): carmine 73.2087 and annatto 73.2030 were answered by the model
      and annatto's answer denied the eye-area use its listing grants
  LC1 an opening listing question ("May we use X, and what applies?") the model answered gets the listing's paragraphs
      no citation of the answer points to, verbatim and cited (73.2125: the 0.1 percent limit said, (a), (c), (d) not)
  EX1 a source's "certification ... is not necessary" supports an answer's "exempt from certification"
  CQ1 conversational query rewriting (regulus.rag.conversation.rewrite_messages): the model rewrites a follow-up into
      a standalone question naming the anchored provision, or repeats it for a new subject; the word rules decide when
      the rewrite is unusable
Blind A/B (23 Oct evening; exact replay of 228 recorded answers, the 6 E1 corrections run live on Qwen3-4B; 20 changed
questions, plain + skeptic scorers, adjudicator on 7 splits): PASS 2 -> 7 (740.17 G1, 82.1602 A1, 710.3 S1, 82.1328 and
82.1330 C82), none lost, misleading 4 -> 2.
"""
from __future__ import annotations

import os

# every fix measured as a gain is on (27 Oct 2026: the UI ran the 26 Oct default A1..P1 while tests ran all of these);
# SP2, SA1 and ST1 stay off
DEFAULT = "A1,A2,A3,A4,G1,S1,E1,C82,P1,Q1,FP1,RS1,QM1,D1,PO2,C2,Q2,PR2,ND1"
VALIDATOR_PRECISION = frozenset(x.strip().upper() for x in os.environ.get("REGULUS_VALIDATOR_PRECISION", DEFAULT).split(",")
                                 if x.strip() and x.strip().lower() not in ("off", "none"))


def enabled(fix: str) -> bool:
    return fix in VALIDATOR_PRECISION
