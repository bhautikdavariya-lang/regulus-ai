# Switch stages: selection, router, answer checks (design note)

Status: **design only, no code changes.** The refactor waits for the 30 Oct results (full300d), which decide what is
promoted to `DEFAULT`. This note describes the code as it stands at `rc-2026-10-29` (bb7543b), with line numbers from
that commit, and proposes the module boundaries the refactor should aim for.

Every switch has a `stage` in `src/regulus/rag/switches.yaml`. For a stage's list with status and evidence, run
`python scripts/switch_report.py --stage selection`. This note covers the three stages that carry most of the open
decisions:

| Module | Switches (status at 29 Oct: **D**efault / **C**andidate / **E**xperimental / **R**ejected) |
|---|---|
| Selection | SN1 C, HQ1 E, RO1 D, PC1 C (cascade), V2 E, VB1 D, SP2 C, SP2F C, SP2O C, AU2 E, HT1 D, HC1 D, SP3 D, HM1 D, DQ1 C, MS1 C, MS2 C, PL1 E, MS3 R, XC1 E, XP1 R, NAV1 R, NAV2 R, QD1 E, QD2 E, DV1 C, DV2 E, ST1 E, AR2 C, OC1 E; budget: BA1 C, RR2 E, RR1 R, HX1 C, CB1 C |
| Router | BR1 E, GT1 E, NX2 E, NX1 E, FJ1 E (and the existing scope / determination / ambiguity rules) |
| Answer checks | CL1 E, A1 D, CM1 D, AR1 R, MF1 D, AF1 D, FP1 D, QM1 D, A2 D, FC2 E, FD1 E, C2 D, C3 R, EX1 D, E1 D, E1S D, E2 D, E2B R, PT1 C, PR2 D, A4 D, A3 D, CX1 E, RS2 R, BN2 R, CV1 R; after validation: LC1 D, PC1 C (appender), ND1 D, S1 D, ISO1 C |

The other stages are retrieval (SP1, SY1-3, XR1, AG1, QX1), conversation (FU2*, CT1, CQ1, FS1/2), planning (LV1),
composers (LS1/2/3, WS1, C82, Q1/Q2/FQ1, ...) and generation (TK1, AL1, LM1, FX1, ST2, FR1). They appear below only
where they interact with the three modules.

## 1. One question, end to end

```
question
  │  SP1 spelling ─ plan_query (LV1) ─ follow-up reading (FU2*, CT1, CQ1)        pipeline._answer_once 1455-1470
  │  QM1 / QC1 re-plan onto live Part 820                                        1471-1481
  ▼
┌──────────────────────────── SELECTION (which provisions, how much of each) ─────────────────────────────┐
│ S0  DV1 small-part paragraphs (DV2 guard) ──fires──► promotion is DV1's; S1-S5 are skipped     1485-1490 │
│ S1  candidates: lexical + dense, SN1 named subpart, AU1, HQ1 appended      section_promotion 1036, 1619  │
│ S2  pick: RO1 reorder → PC1 cascade or LM picker → reranker veto (V2, VB1)                    2014-2046 │
│ S3  second pick: SP2 → SP2F floor → [statute branch: AU2] → SP2O lead swap                    2050-2080 │
│ S4  companions of the pick: HT1, companions(), HC1, SP3, HM1, DQ1          _cfr_promotion     2108-2130 │
│ S5  added context: MS1 (+MS2 pool, PL1 families, MS3) → XC1 → XP1 → NAV1(+NAV2) → QD1(+QD2)  2090-2107 │
│ S6  ST1 cited Act sections                                                           pipeline 1548   │
│ S7  retrieve the plan (XR1 rows, AG1 anchored guidance) → select_evidence:                              │
│       BA1 block charging, RR2/RR1 order of required sections, HX1 48 paragraphs, CB1 15k ceiling          │
│                                                                                  selection 178-406   │
│ S8  package: AL1 answer allowance, ST2/TK1/FX1/LM1; added sections become optional; OC1 → context       │
│                                                                                     pipeline 1594-1655 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
  ▼
┌──────────────────────────── ROUTER (answer, decline, or answer differently) ──────────────────────────┐
│ R0  GT1 guidance-title lookup, NX2 subpart lookup (DB, precomputed)                 pipeline 1699-1714  │
│ R1  gate.decide: scope OUT → general knowledge → GT1 → NX2 → BR1 → determination → ambiguous →          │
│     requested provision not found (→ NX1 text) → no evidence → reference target → value absent →        │
│     partial / mixed → FJ1 note on the remaining answerable / unknown verdicts  answerability 120-215   │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
  ▼
  composers first (QC1, QM1, FP1/RS1, D1, LS1, WS1, LS2 ...): a composed answer skips the model    1750-1800
  ▼
┌──────────────────────────── ANSWER CHECKS (is the draft safe to show) ────────────────────────────────┐
│ C0  model draft → normalise → A4 re-point citations                                         1928       │
│ C1  validate_answer: CL1 degenerate → A1/AF1/MF1 figures → CM1 → FP1/QM1 → AR1 →                         │
│     check_claims: A2 absence → FC2 figure attribution → FD1 false denial → C2/C3 conditions → EX1 →      │
│     E1 (E1S) / E2 / E2B duty strength → PR2 / PT1 premise          validation 559-740, claim_validation  │
│ C2  A3 excise unsupported uncited sentences, re-validate                                      1949      │
│ C3  CX1 skip? → correction pass (model) → re-validate                                         1960-1978 │
│ C4  RS2 / BN2 rescue drafts                                                                   1979-1995 │
│ C5  not shown → Q1/Q2 focused quote (FQ1 size) or withhold                                   2000-2033 │
│ C6  validated: CV1 → LC1 → PC1 appender → ND1; then S1 status note, ISO1 clauses             2034-2105 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
  ▼
answer()  AR2: a validated answer that says "does not specify" → one more pass with the section that holds it
```

## 2. Selection

### Order and contract

The output of selection is a `Promotion` (sections, companions, notes, method, rerank score), and then the
`GenerationPackage` built from it. The notes are the interface to the later stages, and they are matched as string
prefixes:

| Note prefix | Written by | Read by |
|---|---|---|
| `second pick: ` | SP2 (resolve 2088) | optional-section filter (pipeline 1640); **not** OC1, so it stays a requested provision |
| `reranked: ` | MS1, and with it MS2, PL1, MS3 and XC1, which all go out under this one note | optional filter, OC1 |
| `absence retrieval: ` | AR2 (pipeline 1509) | optional filter, OC1 |
| `sub-questions: ` | QD1/QD2 (resolve 2106) | optional filter only; **not** OC1, so QD sections stay requested units |
| `cross-part: `, `navigated: ` | XP1, NAV1 (rejected) | optional filter, OC1 |
| `paragraph companions: ` | **nothing** (dead prefix, see CLEANUP_PROPOSAL 5.5) | optional filter, OC1 |

### Dependencies (a switch that does nothing without another)

These follow from the code paths, not from the docstrings:

- **SP2F, SP2O need SP2.** `second_cfr` comes only from `second_in_part`, which checks SP2.
- **MS2, PL1, MS3, XC1 need MS1.** All four run inside `reranked_companions`, which is called only under MS1 (2090).
  XC1's docstring does not say so.
- **QD2 needs QD1.** QD2 widens `multi_part` and the sub-question search, and QD1 is the call site.
- **DV2 needs DV1** for its narrowing. Its Q2 quoting of DV1 promotions (pipeline 1690-1693) also needs Q2.
- **NAV2 needs NAV1.** Both are rejected.
- **E2B needs E2, and C3 extends C2.** Both of these are rejected.
- **OC1 acts only on the notes above.** With no MS1, AR2, XP1 or NAV1 note it changes nothing (the test
  `test_oc1_changes_nothing_when_every_requested_provision_is_added`).

### Interactions to watch on 30 Oct

1. **The budget is shared and zero-sum.** MS1, PL1 and XC1 draw on one `MS1_MAX_CHARS` allowance in that order, and XC1
   gets what MS1 leaves. All required evidence then competes under CB1 (15,000 chars) and HX1 (48 paragraphs). Every
   memory note since 20 Oct says the same: a lever that adds evidence displaces evidence. Over-supply caused 4 of the 8
   PASS lost in full300c (S-024, F-012, L-014, Y-007).
2. **PL1 raises MS1's count cap.** It makes it `max(MS1_MAX, PL1_MAX)` (605), so PL1 on means more companions as well as
   smaller ones.
3. **The order of S5 decides who gets the space.** MS1 runs before XC1, XC1 before QD1. QD1's sub-question sections
   are added after the character allowance has been used and are not counted against it, so it is the one S5 addition
   with no char cap (QD1_MAX = 2 sections).
4. **The cascade (PC1) and the picker look the same to S3.** The cascade returns a picker-form reply, so SP2/SP2F/SP2O
   act on cascade picks too.
5. **HQ1 is upstream of everything.** It changes the candidate list, and so the picker, RO1, SP2, MS1's pool and XC1's
   pool. Measure it alone first.
6. **DV1 bypasses S1-S5 entirely.** A Part 820 / 11 question therefore gets none of SP2, MS1, XC1 or QD1. The lost
   DV1 PASS (M-001, M-008, M-026, NC-022) are DV2's targets.
7. **OC1 changes what the answer checks demand, not what the model sees.** Added sections stay in the prompt as
   supporting sources but leave the answer plan and the completeness requirements. That is the intended fix for the 29
   truncated answers, and also the reason OC1 must be judged on answers, not on retrieval recall.

## 3. Router

### Order

`gate.decide` (answerability.py 120-215) returns at the first rule that holds, so the order is a precedence:

1. Scope OUT (question analysis), then general knowledge.
2. **GT1**: a quoted guidance title that is not in FDA's listing → INSUFFICIENT_EVIDENCE, `boundary_unknown_guidance`.
3. **NX2**: the named subpart is absent or reserved → INSUFFICIENT_EVIDENCE, `boundary_premise_fact`.
4. **BR1**: certify / attest / conceal / litigate / reproduce a standard / other agency / unscoped retention →
   UNSUPPORTED_REQUEST (OUT_OF_SCOPE for another agency). BR1 is *classified* before GT1 and NX2 but *returned* after
   them.
5. Determination or prediction, then ambiguous provision.
6. Requested provision not found. **NX1** does not decide here: it rewrites the not-found answer text afterwards
   (pipeline 1833, 1843), unless the gap could be a data gap, a reserved section or a former QSR section (QM1's case).
7. No evidence, reference target, requested value absent, partial / mixed scope.
8. **FJ1**: a foreign regulator named beside FDA → a limitation note on the UNKNOWN or ANSWERABLE verdict. It never
   blocks.

### Interactions

- **FJ1's note is lost whenever an earlier rule returns.** A question naming Health Canada whose coverage is partial
  (rule 7) or whose requested value is absent returns before FJ1 is computed, so it gets no foreign-jurisdiction note.
  Today FJ1 fires on SD-013 only, so this does not show in the benchmark. It is a design fault all the same: FJ1 is an
  annotation, not a route, and should be computed before the rule cascade.
- **GT1 outranks BR1.** A request to certify compliance with an invented guidance gets "not in the listing", not the
  certification boundary. That is probably right, since the premise is the bigger problem, but it is accidental. Make it
  explicit.
- **GT1 and DV2 both target NC-022.** DV2 stops DV1 from promoting Part 820 paragraphs for a guidance-document question.
  GT1 then declines it. With GT1 off and DV2 on, NC-022 goes to the general path. Measure them as a pair.
- **NX1 vs QM1.** NX1 skips former QSR sections (`qmsr.reference()["former_sections"]`), and QM1 re-plans them earlier,
  before S0 in the diagram. Their order is safe as built.
- **Cost: the router runs after selection.** GT1, NX2, BR1 and FJ1 depend only on the question text and database
  lookups, never on the evidence. Yet a BR1-blocked question still pays for candidate generation, the cross-encoder, the
  LM picker (16-19 s with MC1) and evidence selection before it is turned away.

## 4. Answer checks

### Order

The order is in the diagram (C0-C6). In words: the draft is normalised and its citations re-pointed (A4). It is then
validated. Inside `validate_answer` the degenerate check (CL1) comes first, then figures (A1, AF1, MF1), mismatches
(CM1), the composer cross-checks (FP1, QM1) and arithmetic (AR1). Last comes `check_claims`, sentence by sentence:
absence (A2), figure attribution (FC2), false denial (FD1), conditions (C2/C3), certification wording (EX1), duty
strength (E1 with E1S, E2, E2B) and the yes/no premise (PR2, PT1).

A failing draft is trimmed (A3) and re-validated. Then, unless CX1 skips it, the draft goes back to the model once. The
rescue drafts (RS2, BN2) come next. If the draft still cannot be shown, a focused quote (Q1/Q2, sized by FQ1) or a
withhold follows. A shown answer then gets CV1, LC1, the PC1 appender and ND1, then the S1 status note and the ISO1
clauses.

### Interactions to watch on 30 Oct

1. **AL1 must not be promoted without FC2.** AL1 gave truncated drafts room to finish. Their long paraphrases then
   replaced the verbatim quote they used to fall back to, and misattributed figures (F-016 PASS → PP, F-015, T-009). FC2
   catches exactly those, and on replay its fallbacks are byte-identical to full300c's graded answers. AL1 alone: 2 up /
   2 down. AL1 with FC2: losses cancelled on replay. The live pair is first measured in full300d.
2. **CX1 was calibrated before FC2, FD1 and CL1 existed.** It skips the correction pass at 3 or more distinct error
   codes (31 of 32 such passes were rejected in full300c). The three new checks add codes, so drafts that had 2 codes
   can now reach 3 and lose their pass. In full300d look at the answers where CX1 fired *and* one of FC2, FD1 or CL1
   contributed a code. If any PASS is lost there, count only full300c's codes in CX1.
3. **CL1 guards the correction pass.** M-042's accepted correction was fifteen bare citation lines. Without CL1 any
   correction that asserts nothing validates. Promote CL1 with or before anything that adds correction passes.
4. **A3 trims before FC2/FD1 get a correction.** A3 removes failing *uncited* sentences. FC2 and FD1 flag *cited* ones,
   so they reach the correction pass. No overlap in theory, but check the order in a trace.
5. **FD1 and A2 overlap on denials.** A2 handles a scoped absence ("these provisions set no limit"). FD1 handles a
   denial an EXACT paragraph contradicts. A2's unscoped denials stay errors, so one sentence can carry both A2's code and
   FD1's `false_denial`. That matters for CX1's count (item 2). Check how often it happens in full300d.
6. **The post-validation appenders change a validated text after validation.** LC1, the PC1 appender, S1 and ISO1 append
   text that is never re-validated. Each appends verbatim database text, so this is safe by construction, but it is why
   ISO1 and WS1 were held back from the 27 Oct release: 25 tests pin the old delivered path.
7. **OC1 (selection) relaxes completeness.** With OC1 on, the answer is no longer required to restate added sections,
   so the "omits" findings drop on those answers. Read full300d's changed verdicts with that in mind.

## 5. Proposed module boundaries (after 30 Oct)

These are design targets, in order of value. None is started.

1. **One ordered step list per module.** Each switch becomes a step object: `name`, `stage`, `requires` (the
   dependencies in section 2), `reads` and `writes` (Promotion fields or notes), and `run(state) -> state`. The step lists
   live in `selection_steps.py`, `router_rules.py` and `answer_checks.py`. `resolve()`, `gate.decide()` and
   `validate_answer()` keep their signatures and just iterate the list, so callers and the 3,200 tests see no change.
   The precedence that is implicit today (GT1 > NX2 > BR1, MS1 > XC1 > QD1) is then written down in one list per module.
2. **A per-question step trace.** Each step records whether it fired and what it changed, e.g. `{"MS1": ["111.75"],
   "XC1": [], "SP2F": "dropped 117.135"}`. It is stored in the measurement record. Every attribution in the ledger
   (MS1 44 up / 8 down, DV1 12 / 4, "7/8 lost PASS had the same evidence") was reconstructed by hand from notes and
   replays. With a trace, `impact_run.py diff` can attribute each changed answer to the steps that fired.
3. **Typed notes instead of string prefixes.** `Promotion.added: tuple[Added(label, by, role)]`, where `role` is
   `requested` / `optional` / `context`. This replaces the prefix tuples at pipeline 485 and 1640, ends the dead-prefix
   class of bug, and makes OC1's policy one field instead of a list of strings.
4. **Router first for question-only rules.** Move BR1, GT1, NX2 and FJ1 (annotation only) into a `route(question, db)`
   call before selection. They need the question and database lookups, not the evidence. That saves the picker and
   reranker time on every routed question, and fixes FJ1's lost-note fault. The evidence rules (provision not found,
   value absent, partial) stay in `gate.decide`.
5. **A dependency check at start-up.** `switch_registry` already knows every code. Add `requires:` to the registry
   entries listed in section 2 and warn (never fail) when `REGULUS_VALIDATOR_PRECISION` turns on a switch whose
   requirement is off, or names a code the registry lacks (CLEANUP_PROPOSAL 5.3).
6. **One paragraph-family helper.** PL1, XC1 and MS3 repeat the same top-level-paragraph query (see
   CLEANUP_PROPOSAL 5.4).

## 6. Promotion checklist for the 30 Oct results

These are the groups that move together, from section 2 and section 4. Promoting one member alone is either a no-op or
a known loss:

| Promote | Together with | Reason |
|---|---|---|
| SP2 | SP2F (and SN1) | SP2 alone lost 3 PASS (LEDGER 28 Oct 12:55); SP2F's floor projected 0 lost |
| SP2F, SP2O | SP2 | no-op without it |
| MS2, PL1, XC1 | MS1 | no-op without it |
| AL1 | FC2 | AL1 alone lost F-016's PASS |
| CX1 | after checking item 4.2 | its threshold predates FC2 / FD1 / CL1 |
| DV2 | DV1 | narrows DV1; its Q2 quoting needs Q2 (default) |
| QD2 | QD1 | no-op without it |
| PC1 | after splitting it (CLEANUP_PROPOSAL 4) | one code, two features |
| WS1, ISO1 | reconcile the 25 pinned tests | held back from the 27 Oct release for this |

To get the switch string for "DEFAULT + every candidate", run `python scripts/switch_report.py --promote-list`. Run
`python scripts/switch_report.py --run full300d` to list what tonight's run added.
