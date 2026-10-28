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
  SP2F (28 Oct, off until measured) SP2's second pick stands only when its cross-encoder score reaches
      REGULUS_SP2F_MIN_SCORE: SP2 live 28 Oct, the 3 losses in 29 changed answers were second picks outside the key
  SN1 (28 Oct, off until measured) a question naming "Part N Subpart X" is answered from that subpart's candidates
      (regulus.rag.section_promotion.named_subpart): F-003 promoted 117.4 for 117.10, F-016 117.5 for 117.201, and SP2's
      second pick 117.135 cost F-004 (Subpart B named)
  PT1 (28 Oct, off until measured) a product the yes/no question names is not an unstated premise when a supplied source
      permits its category outside an exception (regulus.rag.claim_validation.covered_product_words): "Is mica permitted in
      eye shadow?" was declined because no source contains "shadow" though 73.2496(b) allows eye-area use
  FQ1 (28 Oct, off until measured) the focused verbatim quote takes up to 8 paragraphs / 4,000 characters of the
      requested provision (was 3 / 1,600): 300Q 27 Oct, 27 focused quotes scored 0 PASS+PP, 22 as "omits (b)-(g)"
  MS1 (28 Oct, off until measured) rerank-threshold-budget selection: the other candidates of the promoted section's
      part whose cross-encoder score reaches REGULUS_MS1_MIN_SCORE join it as companions, best first, at most
      REGULUS_MS1_MAX and REGULUS_MS1_MAX_CHARS (regulus.rag.section_promotion.reranked_companions); 300Q 27 Oct: 68
      wrong answers had a key section among the candidates and not in the prompt
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
  SP1 spelling correction against the regulations' vocabulary, SymSpell-style (regulus.retrieval.spelling): "carmin"
      -> "carmine", "anatto" -> "annatto". 277 bank questions with seeded typos: key section first 124 -> 131 (clean 134),
      in the top 5 189 -> 200 (202), color matched 78 -> 90 (95); 0 of 1,962 correctly spelled questions changed
  QX1 (off until measured) LLM query expansion: the model restates the question in the regulation's terms and the
      sections that ranks first join the picker's candidates (71.18 "petition for exemption" for "ask FDA to exempt")
  LM1 (off until measured) "lost in the middle": with 6+ sources the prompt names, before the evidence, the (at most 3)
      the cross-encoder scores closest to the question (70.19-Q2 read the new-petition fee (c) for an amendment, (i))
  CV1 (off until measured) Chain-of-Verification with an entailment model: each cited sentence of a validated answer is
      judged against its cited sources by MiniCheck-RoBERTa-Large (regulus.rag.entailment; Tang et al., EMNLP 2024);
      sentences below REGULUS_CV1_MIN_SUPPORT go back to the model once, the revision kept if it validates and its
      weakest sentence improves, else the unsupported sentences are removed when cited statements remain
  FR1 (off until measured) facts first (FaithfulRAG-style): the model lists what the sources state about the question,
      with source numbers and conditions, then answers from that list (one more generation)
  FC1 a Part 70/71 section whose heading names a subject a 70.19 fee paragraph prices (a two-word phrase used in at
      most 3 sections of the two parts) gets that paragraph as a companion: of all 40 sections, exactly 70.51 -> 70.19(l),
      (m) and 70.55 -> 70.19(n), the fees their keys name. RO1 measured 27 Oct on the 50: +3 picks, -3 (the reranker
      favours color listings for "exempt from certification" questions) - off; QX1 recovered nothing - off
  CT1 (off until measured) conversation topic memory: with no focus chosen and no deployment scope, a follow-up in a
      conversation anchored only to cosmetics provisions (Parts 70-82, 700-799, FD&C Act 601-614) is answered with the
      cosmetics focus
  SY1 (off until measured) "ask FDA to / for ..." with no "petition" adds "petition" to the search terms (domain
      synonym expansion): 71.18 was not among the candidates of "Can we ask FDA to exempt it from certification?"
  27 Oct measurements: SY1 (71.18 not a candidate -> first; 0 other changes) and CT1 (802 bank follow-ups read alone
      in a general deployment: key section in the top 5, 531 -> 643) are on. LM1 + FR1 together on 22 questions:
      +3 / -2 blind, answers 30% slower - off
  BN2 (off until measured) best of two with a verifier: a facts-first draft beside the plain one; the validated draft
      citing more of the requested paragraphs with fewer denials is delivered (plain on a tie), and a validated
      facts-first draft replaces a plain one that would be withheld
  FX1 (off until measured) dynamic answer example: one verified dev-split key of a similar question about another
      provision, section numbers removed, shown as an example of a complete answer's content (regulus.rag.answer_examples);
      never from the question's own provisions or the question itself, never a sealed question. The examples file is
      the client's keys and stays outside the repository (REGULUS_ANSWER_EXAMPLES)
  RO1 ON since 27 Oct 12:30: with color listings given no reranker credit when no color is named, 118 dev picker
      questions key first 44 (lexical) -> 59, MRR 0.489 -> 0.588; live 5 of 9 problem picks right (baseline 3).
      BN2 on 22: +1 / -1 by its own choice, answers 75% slower - off; FC1 confirmed live (70.51, 70.55 -> PASS)
  WC1 (off until measured) a question asking what a Part 740 warning or label must say is answered with the statement's
      paragraph named and the section's paragraphs verbatim (regulus.rag.warning_statements); "do we need it?" stays
      with the model
  TK1 an answer applying provisions gets at least 640 tokens (70.55-Q1 cut at 256, 740.2-Q1 at 416, both withheld); the
      allowance is not in the prompt, so with greedy decoding only answers that hit the old limit change
  E1S a prescribed label statement's own words ("Caution—... a physician should be consulted") are not the strength of
      the duty to bear it (740.12-Q1 withheld as "'must' where the source says 'should'")
  27 Oct stratified 50 (unseen, bank mix): 64% PASS+PP; listings 13/14, Part 82 8/8, labeling 6/15, FD&C Act 2/7
  DF2 a question classifying something under the FD&C Act's own definitions ("Is it a cosmetic under the FD&C Act
      definition?") is resolved to the defining paragraph, read from the Act text of 201, 604 and 608 ('The term "X"
      means'); MoCRA questions use 604 / 608. Fires on 4 of 1,962 bank, follow-up and 300Q questions, each its key
      paragraph (201(i), 604(2), 608(c)(1), 608(c)(2)); 201(i)-Q1 had gone to 604
  NL1 a listing that names the cosmetics it may color (74.2052, 74.2053: "the following cosmetics ...: Eyeliner, ...") is
      composed too: a named product is permitted, any other not (the model permitted D&C Black No. 2 in a hair gel)
  ST2 (off until measured) the S1 status note of a supplied provision is also shown to the model before it answers
  VB1 after a reranker veto the picker's second pick stands only if it is from the other corpus (bug: FDCA606-Q2's veto
      720.1 -> Act 606 kept Act 612 as a regulation, "21 CFR 612" was promoted and the answer declined)
  SY2 domain thesaurus for the search terms: "become public / keep confidential" -> public disclosure, confidentiality;
      "hide / disguise / cover up" -> conceal, deception. Fires on 7 of 1,962 questions; key section rank 71.22-Q1 14 -> 1,
      71.15-Q1 / Q2 / Q2-F4 2 -> 1, one anchored follow-up 1 -> 2
  PC1 (off until measured) after a validated answer from one requested 21 CFR section, its uncited paragraphs that the
      cross-encoder scores >= 0.5 for the question (at most 3) are appended verbatim and cited
  QD1 (off until measured) question decomposition (Question Decomposition for RAG, ACL SRW 2025): a multi-part question
      is split by the model into at most 3 sub-questions; each one's best regulation section by the cross-encoder
      (>= 0.5) joins the picked section as a companion, at most 2
  WC1 ON since 27 Oct 14:00: diagnostic 30 (unseen weak-family dev questions), both "what must the warning say"
      questions composed and blind-scored PASS (740.11-Q1, 740.17-Q1); the three withheld drafts there had real errors
      (invented duties, a mis-cited sub-paragraph), so the validator stays as it is
  ISO1 (measured gain, held back from the 27 Oct release) the ISO 13485 clauses that the cited Part 820 paragraphs (or their section's lead-in) name,
      and the answer does not, are added on one line with those citations (regulus.rag.iso_clauses); never guessed
  AF1 a section number a source states with its paragraph ("section 601(c) of the act") counts as supplied, so an
      answer's "§ 601" is not an invented figure (sealed 700.27-Q1 withheld over it)
  RS2 (off until measured) rescue: when the plain draft and its correction fail validation, a facts-first draft is
      tried once before the answer is quoted or withheld, and delivered only if it validates (a fallback chain; it
      never touches an answer that validated)
  LS1 (on since 27 Oct release) "what must X include / contain / show / record" about one requested 21 CFR section is
      answered with the lead-in paragraph that introduces the matching list and every paragraph under it, verbatim
      (regulus.rag.list_answers)
  SY3 MoCRA thesaurus: "small brand / under $1 million / annual sales" -> 612 (small businesses), "also an OTC drug /
      drug and cosmetic" -> 613 (products also subject to chapter V). 23 bank questions keyed to 605-613 that fire:
      Act rank better 14, same 8, worse 1 (2 -> 3); the 10 "small brand" listing questions keep their CFR rank
  RC1 (off until measured) rules as code for the MoCRA small-business exemption: a small-business question with FD&C
      Act 612 supplied gets the verdict from its facts (a product of 612(b) excludes; 612(a) covers only 364b and 364c)
      and 612's text verbatim (regulus.rag.mocra_rules)
  DV1 (off until measured) a question naming only a small 21 CFR part (<= 12 live sections; Part 820, the QMSR, has 6)
      or, naming none, ISO 13485 / the QMSR, is answered from that part's most relevant paragraphs: cross-encoder rank
      fused with shared two-word phrases, top 3 (regulus.rag.section_promotion.part_paragraphs). Dev device questions it
      handles: key paragraph among its picks 13 of 19 (the baseline read the whole part and missed the paragraph)
  QM2 (on since 27 Oct release) the former regulation's record types named in words - device master record, device history
      record, design history file, quality system record - are its former sections for QM1 (regulus.rag.qmsr.former_by_name)
  E2B (off until measured) an uncited duty sentence E2 would call strengthened stands when another supplied source states
      that duty itself with at least 40% of its words - E1's escape (regulus.rag.claim_validation.duty_stated)
  LS2 (on since 27 Oct release) "What does 21 CFR X require?" about a section whose own lead-in introduces its list (820.10
      "... must:" then (a)-(e)) is answered with LS1's whole list, verbatim (regulus.rag.list_answers)
  AR1 (off until measured) a figure the answer computes in plain sight ("2,000 pounds x $0.45 = $900") is supported when
      both operands are supplied figures and the arithmetic holds (regulus.rag.validation.verified_arithmetic)
  C3 (off until measured) a paragraph of the same section that names the cited paragraph ("unless an exemption pursuant
      to paragraph (b)") counts as cited for the condition checks, as C2 counts a parent or child
  XR1 (on since 27 Oct release) a requested section is fetched whole up to 400 rows (was 100), so the selector's relevance
      order - not the row limit - decides which of a long section's paragraphs fit (720.4(d)/(e); 27 sections exceed 100)
  HC1 (on since 27 Oct release) a promoted section whose heading names one topic of the question brings the same-subpart
      sibling whose heading names another (211.137 "Expiration dating" + 211.134 "Drug product inspection"), at most two
      (regulus.rag.section_promotion.sibling_companions)
  HT1 (on since 27 Oct release) a section repeated by heading and number in another part (213.192 / 211.192) is read as the
      larger, general part's unless the question names the specialised part's subject (213: medical gases)
  HM1 (on since 27 Oct release) a section of the promoted section's part whose heading's lead phrase the question contains
      word for word (two topic words or more) joins it: "use of approved components ... rejected components" -> 211.86,
      211.89 (regulus.rag.section_promotion.heading_matches)
  WS1 (measured gain, held back from the 27 Oct release) an overview question whose subject is the promoted section's own heading ("What are the
      reserve sample requirements under Part 211?" -> 211.170) is answered with the whole section verbatim when it is at
      most 3,600 characters (regulus.rag.list_answers.compose_section)
  SP3 (on since 27 Oct release) in Part 111 a promoted section brings the rest of its subpart when the subpart is at most 8
      sections and 4,500 characters (Subpart O complaints: 111.553 + 111.560 + 111.570), except for a list question
      (regulus.rag.section_promotion.small_subpart)
  HX1 (off until measured) up to 48 required paragraphs (was 24) under the unchanged character ceiling (111.260's list)
  QC1 (on since 27 Oct release) "does Part 820 require ISO 13485 certification / does a certificate exempt us from inspection"
      is answered from 820.10(a) once the database confirms no live part 820 text mentions certification
      (regulus.rag.qmsr.compose_certification)
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
# SP2, SA1, ST1, FS2 stay off; RO1, V2, QX1, CQ1 join after their measurement.
# Release 27 Oct evening: LS1, LS2, QM2, QC1, XR1, HC1, HT1, HM1, SP3 joined after blind-scored live checks
# (devices +9, drug CGMP 7->14/15, supplements 2->5/15, cosmetics +4) and a replay gate over every recorded answer
# (230 cosmetics, 30 devices: 0 PASS lost). Measured and left off: HX1 (S-018 lost), RS2, E2B, C3, AR1; DV1 pending.
DEFAULT_BEFORE_27OCT_RELEASE = ("A1,A2,A3,A4,G1,S1,E1,C82,P1,Q1,FP1,RS1,QM1,D1,PO2,C2,Q2,PR2,ND1,"
                                "DF1,EY1,MF1,E2,CM1,LV1,CS1,EX1,UR1,LC1,FU2,FU2B,FU2C,FU2D,SP1,FC1,SY1,CT1,RO1,TK1,E1S,DF2,NL1,"
                                "VB1,SY2,WC1,AF1,SY3")
# WS1 and ISO1 measured as gains but held back from this release: they change the delivered-answer path that 25 tests
# pin (WS1 answers fixture questions before the draft is validated; ISO1 appends after validation) - reconcile first
DEFAULT = DEFAULT_BEFORE_27OCT_RELEASE + ",LS1,LS2,QM2,QC1,XR1,HC1,HT1,HM1,SP3"
VALIDATOR_PRECISION = frozenset(x.strip().upper() for x in os.environ.get("REGULUS_VALIDATOR_PRECISION", DEFAULT).split(",")
                                 if x.strip() and x.strip().lower() not in ("off", "none"))


def enabled(fix: str) -> bool:
    return fix in VALIDATOR_PRECISION
