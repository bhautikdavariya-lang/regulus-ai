# Phase 2M: forensic investigation of the remaining evaluator errors

**Run:** 2026-10-09, started 05:52:42Z. Investigation only.
- No production code, permanent tests, fixtures, expected results, benchmark data, frozen answers, rubric or scoring changed (section 5.4).
- Nothing was installed, no model was downloaded, there was no 300-question run and no LLM judge.
- The database was used only through the server-enforced read-only connection (`transaction_read_only = on`, asserted in each script).

**Verdict: ARCHITECTURAL CHANGE REQUIRED**, with four narrow, independently safe fixes identified as interim candidates for review.

| Group | Cases | Finding |
|---|---|---|
| Independent, narrowly fixable | T3c, DX4, N9, N10, N15 | Each has a narrow switch that passes every regression criterion in this phase and changes none of the 170 frozen row-runs. |
| Coupled, not locally fixable | N12, DX2, and four more found here: MR1, NN2, AP3, T5b | Every local fix tried either breaks a control or a Phase 2D protection, or introduces a false conflict. |

**The common cause of the coupled group:**
- Polarity and strength are single, passage-level values with no proposition structure and no negation scope.
- The content gate counts *any* operator agreement, including spurious ones.

As a result, several currently *correct* decisions rest on two errors cancelling out:
- F-009 s10 (protected by Phase 2D);
- T5b;
- NN1;
- production's RC6 and DX7.

Removing one error exposes the other. That is evidence for a principled change in how claims and evidence are compared, not for more local rules.

---

## 1. Reproducibility of the seven cases

All seven reproduce exactly as reported in Phase 2L, on both production (L0) and JRN2, using the existing offline harness (`work/trace_cases.py` → `trace_L0_identity.json`, `trace_JRN2.json`).
- Evidence is verbatim eCFR text from the snapshot dated 2026-09-03. Hashes were re-fetched read-only (`texts_2m.json`) and match the 2L inputs.
- Claims are taken unchanged from the Phase 2L inputs. None was rewritten.

| Case | Source / citation | Expected | Production | JRN2 | Reproduced? |
|---|---|---|---|---|---|
| T3c | `controls_real.json`, 21 CFR 701.13(d) | no polarity conflict | polarity conflict; unverifiable | same | yes |
| DX4 | `diagnostics.json`, 21 CFR 113.40(a)(6) | no polarity conflict | polarity conflict, **but** final supported (verbatim) | same | yes; see the note below |
| DX2 | `diagnostics.json`, 21 CFR 1141.1(b) | conflict | descriptive, **supported** (false support) | unverifiable (missed) | yes |
| N9 | `numeric_cases.json`, 21 CFR 178.3760 | no numeric finding; claim wrong | paraphrase, **supported** | same | yes |
| N10 | `numeric_cases.json`, 21 CFR 112.203(d)(2) | no numeric finding; claim wrong | descriptive, **supported** | same | yes |
| N12 | `numeric_cases.json`, 21 CFR 1.379(a) | equivalent | contradicted (strength + polarity) | contradicted (strength) | yes |
| N15 | `numeric_cases.json`, 21 CFR 211.180(a) | conflict | paraphrase, **supported** | same | yes |

**Notes:**
- **DX4 is wrong only at operator level.** Its claim-level verdict is already correct (verbatim support).
- **T3c's claim** is the verbatim first clause of a semicolon sentence. The fixture labels it CONSTRUCTED, and I kept that label.

## 2. Root causes, with exact text

**Code locations (production `src/regulus/accuracy/operators.py`):**
- `polarity()` and `strength()` read `main_clause(<whole passage>)`.
- `_NEGATE_RE` includes `exempt(s|ed|ion|ions)`.
- `_STRENGTH_PATTERNS` tests "may not" (MANDATORY) before "may".
- `_QUANTITY_PATTERNS` puts "N calendar/business/working days" into one kind, `day`, and `compare()` agrees on any shared value of a kind.
- `verdicts.content_gate` grants paraphrase support when ≥ 2 operators agree and term overlap is at least 0.7.

### 2.1 Cross-sentence negation: T3c, DX4

**T3c, 21 CFR 701.13(d).**
- Evidence (real): "(d) The declaration may contain common or decimal fractions. A common fraction shall be in terms of halves, …; except that … they may be employed. **A common fraction shall be reduced to its lowest terms; a decimal fraction shall not be carried out to more than two places.** A statement that includes small fractions of an ounce shall be deemed to permit smaller variations than one which does not include such fractions."
- Claim: "A common fraction shall be reduced to its lowest terms."
- The obligation is in sentence 3, clause 1.
- The negation is in **the same sentence**, clause 2 after the semicolon. A second "does not" sits in sentence 4, in a relative clause that JR already discounts.
- The two clauses share the implicit actor (the labeler) but differ in object (common vs decimal fraction) and action (reduce vs carry out). The negation does not modify the claim's proposition.
- **Earliest wrong stage:** `polarity(evidence)` returns NEGATE for the whole passage. The polarity conflict then makes the claim unverifiable, a false negative.

**DX4, 21 CFR 113.40(a)(6).**
- Evidence (real): "(6) Crate supports. **A bottom crate support shall be used in vertical still retorts.** Baffle plates shall not be used in the bottom of still retorts."
- Claim: sentence 2, verbatim.
- The negation is in sentence 3. The verb ("be used") is the same, but the object (baffle plates vs bottom crate support) and the location differ, so it is unrelated to the claim.
- **Earliest wrong stage:** the same whole-passage `polarity()`. The verdict survives only because the verbatim path wins.

**Sentence boundaries alone do not settle scope.**
- In T3c the unrelated negation is in the claim's own sentence.
- Context in other sentences can matter, for example "However, an article may be detained for 10 additional calendar days" in 1.379(a).
- Corpus exposure (read-only scan, `corpus_scan_2m.json`): 35 snapshot sentences mix an affirmative clause and a negated clause across a semicolon, and 33 of them read as NEGATE overall.

### 2.2 Modal strength in a relative clause: N12

- Evidence (real, 21 CFR 1.379(a), sentence 1): "(a) FDA **may detain** an article of food for a reasonable period **that may not exceed** 20 calendar days after the detention order is issued."
- Claim: "… for a reasonable period of no more than 20 calendar days …"

Four readings need to be kept apart:
1. permission or discretion: "FDA **may** detain", the main clause;
2. prohibition: "may not" as a main-clause modal (1.379(b): "The entire detention period may not exceed 30 calendar days");
3. a maximum constraint: "a period **that may not exceed** 20 days", a relative clause limiting the period;
4. obligation: must or shall.

**Earliest wrong stage:** `strength()`.
- It scans the whole main clause, and "may not" (pattern 1, MANDATORY) wins over the main clause's "may".
- So the evidence reads mandatory, the claim permissive, and they conflict.
- In production, `polarity()` also reads the relative-clause "may not" as NEGATE. JR removes that part.
- NUM2 correctly finds the two limits equal (≤ 20 calendar days on both sides).

**Classification:** a modal-parser defect, interacting with limit direction.
- All 21 "may not exceed" sentences in the snapshot read MANDATORY. Most are main-clause prohibitions, where that is right.
- Only the relative-clause forms (1.379(a), 1.980(c), 800.55(c)) are misread.
- **The interaction:** the same misreading is what currently *catches* T5b (133.111(d), "the cumulative levels of which shall not exceed current good manufacturing practice" against the claim "levels exceeding cGMP"). That case has no number for NUM2 and uses a participle that JR does not read. Fixing the modal reading removes T5b's only conflict (section 4).

**The diagnostic set exposes two more production errors:**
- **MR1, false support:** "FDA **must** detain … that may not exceed 20 calendar days" is credited verbatim against "FDA **may** detain …", because both sides read MANDATORY.
- **MR7, false contradiction:** "FDA may detain … for **up to** 20 calendar days" is contradicted.

### 2.3 Quantity mismatch: N9

- Evidence (real, 21 CFR 178.3760): "Polyethylene glycol (400) monolaurate containing **not more than 0.1 percent by weight of ethylene and/or diethylene glycol** may be used at a level **not to exceed 0.3 percent by weight of twine** as a finish on twine …"
- Claim: "… may be used at a level **exceeding 0.1 percent by weight of twine** …"

The evidence states two quantities:
- an impurity specification of the additive (glycol ≤ 0.1 %);
- a use level on twine (≤ 0.3 %).

The claim attaches 0.1 % to the use level, so it states the wrong quantity. It is not a direct reversal, because 0.1–0.3 % is allowed, but it is not supported either.

**Earliest wrong stage:** quantity extraction.
- `quantities()` yields `{(percent, 0.1), (percent, 0.3)}` with no attachment to what each number measures.
- `compare()` records `quantity:percent` as **agreed** because 0.1 appears in both sets.
- The gate then has strength, polarity and quantity agreeing, so the claim is credited as paraphrase.

**Can quantity identity be checked reliably?** Only where both sides name what is measured ("by weight of X"). That is local to NUM2's bound reader and does not generalise to related but distinct quantities named with shared words (section 6).

### 2.4 Time unit and event: N10

- Evidence (real, 21 CFR 112.203(d)(2)): "(2) Appeal the order within 15 **calendar** days of the date of receipt of the order …"
- Claim: "… within 15 **business** days …"
- The event, the anchor ("date of receipt of the order") and the value are identical. **The discrepancy is the unit only, not the event.**
- **Earliest wrong stage:** `_QUANTITY_PATTERNS` puts "15 calendar days" and "15 business days" into the same `(day, 15)`, so quantity agrees.
- Neither side has a modal (it is an imperative), so the claim is credited through `judge_descriptive`, by containment plus a verbatim run.
- The diagnostic set shows the same defect is **credited as verbatim** for "30 business/working days" against 1.379(b)'s "30 calendar days" (DQ3, DQ4).

**Comparability and outcome:**
- 15 business days always ends later than 15 calendar days, so the claim allows appeals the rule forbids.
- Quantifying that needs calendar knowledge (weekends, holidays), so the evaluator cannot safely call it a contradiction.
- **Recommended outcome when both sides name the counting convention and they differ: block support (unverifiable).**
- An unqualified "days" against "calendar days" must not block (DQ1), since CFR usage is mixed.
- A contradiction is correct only for a direction reversal on comparable units, which NUM2 already handles (N11).

### 2.5 "Exemption": N15

- Evidence (real, 21 CFR 211.180(a)): "… shall be **retained for at least 1 year** after the expiration date of the batch or, in the case of certain OTC drug products lacking expiration dating because they meet the criteria for **exemption** under § 211.137, 3 years after distribution of the batch."
- Claim: "… shall **not** be retained for more than 1 year … [rest identical]".

The trace (`trace_details.py`):
1. **Claim:** the main clause equals the full text. Negators: `shall not` (genuine) and `exemption`. Polarity NEGATE.
2. **Evidence:** the main clause equals the full text, because "because …" and "in the case of …" are not condition boundaries in `_CONDITION_BOUNDARY_RE`. Negator: `exemption` only. Polarity NEGATE.
3. The claim's **genuine** negation and the evidence's **spurious** one agree. Strength, polarity and `quantity:year` agree, overlap is high, and the claim is credited as paraphrase.
4. NUM2 abstains by design: the claim's bound has a negation outside the bound phrase, so it reads as ambiguous.

The word here is a noun inside a subordinate clause about § 211.137 expiration-dating exemptions. It does not touch the retention duty.

**The earliest wrong stage** is operator extraction (`_NEGATE_RE` plus the main-clause boundary list). It is not lexical matching, source applicability or alignment.

**The same spurious reading causes the opposite error, NN2:** "No production, control, or distribution record … shall be retained for less than 1 year …" is a correct claim with no negator the operator recognises. It reads AFFIRM against the evidence's NEGATE and is **falsely contradicted**.

**Corpus scale:** 418 snapshot sentences with an otherwise affirmative modal read NEGATE only because of an "exempt*" word in the main clause. The word before it is mostly "an" (111), "the" (45) or "for" (28), which are noun uses, or "be/are/is" (110), which are predicate uses that do negate the duty.

### 2.6 Applicability: DX2

- Evidence (real, 21 CFR 1141.1(b)): "The requirements of this part **do not apply** to manufacturers or distributors of cigarettes that do not manufacture, package, or import cigarettes for sale or distribution within the United States."
- Claim: "The requirements of this part **apply** to manufacturers of cigarettes that do not manufacture cigarettes for sale within the United States."

**Earliest wrong stage:** `polarity()` defines polarity only for obligations, meaning text with a modal.
- Neither side has a modal, so polarity is undetermined.
- In production, the claim's relative-clause "do not" made it read NEGATE and agree with the evidence, which is a false support.
- JR removes that, and the claim becomes unverifiable.
- No operator represents applicability ("applies to" vs "does not apply to").

**A seventh error found here, AP3, which JR introduces.** The claim "The requirements of this part apply to manufacturers of cigarettes that **manufacture** cigarettes for sale within the United States" is consistent with (b): both the applicability and the qualifier are reversed.
- JR's qualifier check (JRQ) flags `qualifier_polarity` and **contradicts** it.
- Production does not.

## 3. Findings by mechanism

| Mechanism | Cases | Nature | Local fix? |
|---|---|---|---|
| Cross-sentence / cross-clause negation | T3c, DX4; new PR1, PR3 (production **false supports**: "A common fraction shall **not** be reduced …" and "A bottom crate support shall **not** be used …" are credited); PR7 (cross-sentence **strength**) | passage-level operator reading | **Yes:** PROP / PROPS (anchored proposition), section 4 |
| Modal strength in a relative clause | N12; new MR1 (production false support), MR7 (false contradiction) | modal parser, coupled with limit direction (T5b) | **No:** MODREL fixes N12, MR1 and MR7 but turns T5b into a false support |
| Quantity identity | N9; QS3 | value sets without attachment | **Yes:** QSCOPE (bounded; it needs NUM2's "of X" reading) |
| Time unit | N10; new DQ3, DQ4 (production false supports **credited verbatim**) | qualifier discarded in extraction | **Yes:** DAYQ |
| "Exemption" | N15; new NN2 (false contradiction) | noun read as negation; the main-clause boundary misses "because / in the case of" | Partly. **NNEG** (negated-bound composition) fixes N15 without touching polarity. **EXN** (exemption only as a predicate) fixes N15 and NN2 but breaks Phase 2D F-009 and creates a new false contradiction (NN1). |
| Applicability | DX2; AP3 (a JR defect) | no applicability operator; JRQ ignores double reversals | **No:** APPL fixes DX2 but adds a false conflict on frozen data (below) |

## 4. Isolated offline experiments

**Setup:**
- Seven independent switches (plus PROPS, a strength-also variant of PROP), each built on a fresh copy of the production package (`work/make_variants_m.py`).
- Each switch was measured alone on **two bases**: production (`L0_X`) and JRN2 (`JRN2_X`).
- No switch was merged with another to form a candidate. The two combined variants below are interaction measurements only.

**The switches:**
- **PROP:** the evidence's polarity is read from the *single* proposition the claim anchors to. A unit is a sentence, or a semicolon clause when every clause has its own modal. Anchoring requires ≥ 80 % of the claim's content stems, a margin of ≥ 0.25 over the next unit, and a modal in the unit. Otherwise the passage-level reading stands.
- **PROPS:** PROP plus strength from the anchored unit.
- **MODREL:** a modal inside a relative clause (that/which/who + modal) is ignored by `strength()` when a modal remains outside it.
- **QSCOPE:** block support when the claim's bound value and unit match only evidence bounds that measure a different stated "of X" quantity.
- **DAYQ:** block support when the same number of days is counted in a different, explicitly named convention (calendar vs business/working).
- **NNEG:** in NUM2's bound reader, a clause whose *only* negator is a modal negation directly governing the bound ("shall not be retained for more than") flips the relation (> becomes ≤) instead of abstaining.
- **EXN:** "exempt*" negates a duty only as a predicate ("be/is/are exempt(ed)", "exempts"), never as the noun.
- **APPL:** an applicability operator ("applies to" vs "does not apply to", outside relative clauses), raised only when JRQ finds no qualifier difference.

**Labelled diagnostics** (`work/m_cases.json`, built by `build_m_cases.py`):
- 29 cases plus the 7 targets. Expectations were fixed before any switch ran.
- Evidence is verbatim with SHA-256. 23 claims are constructed and 6 are verbatim.

### Results on the JRN2 base

`--runxfail` assertions; "15" = Phase 2I checks; "11" = decision cases; "num" = 16 numeric cases at check level; FS / FC = verdict-level false support / false contradiction over every labelled set (`error_counts.json`).

| Variant | 7 tests | Suite | 15 | 11 | 5 probes | num | 11 limit probes | 19 genuine | 44 real | 170 rows | Comparisons changed | FS | FC |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| JRN2 (base) | 7/7 | 1840 pass | 14 | 9 | 5 | 14 | 11 | 19 | 44 | 0 | — | 8 | 4 |
| **+PROP** | 7/7 | 1840 | **15** | **10** | 5 | 14 | 11 | 19 | 44 | **0** | **0** | **6** | 4 |
| **+PROPS** | 7/7 | 1840 | **15** | **10** | 5 | 14 | 11 | 19 | 44 | **0** | **0** | **6** | 4 (also fixes PR7) |
| +MODREL | 7/7 | 1840 | **13** (T5b **new false support**) | 9 | 5 | 15 | 11 | 19 | 44 | 0 | 0 | 8 | **2** |
| **+QSCOPE** | 7/7 | 1840 | 14 | 9 | 5 | 14 | 11 | 19 | 44 | **0** | **0** | **7** (N9 fixed) | 4 |
| **+DAYQ** | 7/7 | 1840 | 14 | 9 | 5 | 14 | 11 | 19 | 44 | **0** | **0** | **5** (N10, DQ3, DQ4) | 4 |
| **+NNEG** | 7/7 | 1840 | 14 | 9 | 5 | **15** | 11 | 19 | 44 | **0** | **0** | **7** (N15) | 4 |
| +EXN | 7/7 | **2 failed:** Phase 2D `para40-F-009` (both aligners) | 14 | 9 | 5 | 15 | 11 | 19 | 44 | **4 claim changes** (F-009 s10 support lost) | 11 | 7 | 4 (**NN1 new**) |
| +APPL | 7/7 | 1840 | 14 | **10** | 5 | 14 | 11 | 19 | 44 | 0 | **1 new false operator conflict** | 8 | 4 |
| *JRN2_CLEAN4 (PROPS+QSCOPE+DAYQ+NNEG, interaction only)* | 7/7 | 1840 | 15 | 10 | 5 | 15 | 11 | 19 | 44 | 0 | 0 | **1** (MR1) | 4 |
| *JRN2_SENT (Phase 2I approach A, comparison only)* | — | — | 14 (T3c) | 10 | 5 | — | — | 19 | **39** | — | — | — | — |

Under every JRN2 variant, the 18 invented-condition cases and 6 reading assertions are unchanged. "Comparisons changed" is measured against the base, over all recorded frozen comparisons (`compare_diffs.json`).

### Results on the production base

These are what each switch would do without JR.
- `L0_PROP` and `L0_PROPS`: Phase 2I checks 9 → 10 and decision cases 7 → **9** (fixes DX4 and DX6).
- `L0_QSCOPE`: fixes N9.
- `L0_DAYQ`: fixes N10, DQ3 and DQ4.
- `L0_NNEG` (with NUM2): fixes N15.
- `L0_MODREL`: does **not** fix N12, because production polarity still reads the relative-clause "may not". This confirms the interaction.
- `L0_EXN`: breaks F-009 para40 again.
- `L0_APPL`: fixes DX2 (production false support) and adds the same false operator conflict.
- **All of the above except EXN:**
  - 0 changes across the 170 frozen row-runs;
  - 19/19 genuine contradictions and 44/44 real readings kept;
  - the 7 tests behave as in production (RC1–RC3 still strict-xfail, RC4–RC7 pass).

**Numeric family alone on production** (`L0_NUMFAM` = NUM2 + QSCOPE + DAYQ + NNEG, no JR):
- 15/16 numeric cases (N12 remains);
- **false supports 21 → 7**, and the 7 left are all non-numeric (PR1, PR3, MR1, T2b, T2c, DX2, DX9);
- false contradictions unchanged at 6;
- 0 changes across the 170 frozen row-runs;
- all controls kept; test outcomes identical to production.

**Changed decisions inspected:**
- **EXN's frozen changes:** F-009 s10 "The issuance of an order to withdraw a qualified facility exemption is approved by an FDA …" goes from **paraphrase by 117.254(a)** to not_decisive (117.251(a)) in F60 and REAL17, under both aligners. Its support rested on "exemption" reading as negation on **both** sides; it is a Phase 2D-protected decision. Its other 7 comparison changes are removed false polarity conflicts that change no verdict (117.201(a)/117.251(a) withdrawal text; H-006 Food Traceability headings).
- **APPL's new conflict:** the claim "It does not apply to radiopharmaceuticals intended for therapeutic purposes" against "This subpart applies to radiopharmaceuticals intended for in vivo administration for diagnostic …". The objects differ, so this is a false conflict. The verdict is unchanged only because the pair is not decisive for that claim.
- **Every other single switch** changed no frozen comparison. All of their changed decisions are the labelled cases listed above.

**Rejected:**
- **MODREL:** T5b becomes a false support.
- **EXN:** breaks the Phase 2D lock and introduces NN1.
- **APPL:** a false conflict, because it does not match the object of "apply to".
- **Sentence-local (A):** misses T3c and PR1 and loses 5/44 real readings, as in Phase 2I.

## 5. Regression and frozen-row results

1. **The 170 frozen row-runs** (F60 legacy-reconstructed + GUIDE8 + REAL17, both aligners), compared with `h_current.json`:
   - 0 claim, answer or dimension changes for L0, NUM2, JRN2, and every PROP, PROPS, MODREL, QSCOPE, DAYQ, NNEG and APPL variant on either base, as well as L0_NUMFAM and JRN2_CLEAN4;
   - **EXN: 4 claim changes**, all F-009 s10 (above).
2. **F-007** is unchanged in every variant. **F-009** is unchanged in every variant except EXN.
3. **Phase 2D gate suite** (240 tests): passes in every variant except EXN (2 failures).
4. **State:**
   - `src/`, `scripts/`, `tests/`, `web/` (305 files): **identical** by SHA-256 at start and end (`work/manifest_*.sha256`; the start state equals Phase 2L's end state);
   - permanent tests (including `test_accuracy_relative_clause.py` and `test_accuracy_content_gate.py`) and all fixtures are inside this manifest;
   - 23 benchmark, frozen-input and fixture files: **identical** (`benchmark_manifest_*.sha256`);
   - `git status --porcelain`: **63 lines, identical** at start and end. This folder is under the already-untracked `artifacts/accuracy/`.

**Limitation:** frozen verdicts being unchanged is **not** evidence that claim-level decisions are correct.
- The frozen set barely exercises these mechanisms: 4 of 2,105 claim/evidence pairs share a numeric limit (Phase 2L), and none of PROP, QSCOPE, DAYQ or NNEG changes a single frozen comparison.
- Every benefit reported here comes from labelled real-text cases with constructed claims.
- Benefit on real answers is **unmeasured**.

## 6. Prioritized recommendation for the next engineering phase

1. **Tests-first review of the numeric family on production** (NUM2 + QSCOPE + DAYQ + NNEG; *no* JR).
   - Measured benefit: false supports 21 → 7 on the labelled sets, with nothing lost.
   - It does not import JR's qualifier logic and leaves the RC1–RC3 strict-xfail markers as they are.
   - Before implementing, add permanent tests for N1–N16, QS1–3, DQ1–4 and NN1–2, plus the 11 limit probes.
   - Known limits:
     - no unit conversion;
     - exact values only;
     - lexical "of X" scope;
     - NNEG handles only "modal + not + verb + bound".
2. **Review PROP (polarity only) as a separate change after that.**
   - It is independent of JR, fixes T3c, DX4, PR1 and PR3 (and DX6 on production), keeps all 44 real readings, and is inert on frozen data.
   - PROPS (anchoring strength too) is equally clean and also fixes PR7, but it widens scope. Decide between them in review.
3. **Do not ship JR in its current form.**
   - JRQ falsely contradicts AP3 (a double reversal), in addition to the Phase 2L notes.
   - Do not ship MODREL, EXN or APPL either. Each is coupled to another error.
4. **Architectural work (the main recommendation):** a proposition-level comparison.
   - Segment the evidence into propositions, each with actor, modality, polarity, action, object, qualifiers and bounds, and scoped negation (main clause vs relative clause vs bound).
   - Anchor each claim to one proposition, with abstention when that is ambiguous.
   - Make the content gate count only agreements from the anchored proposition, so that spurious agreements (F-009 s10's "exemption") can no longer found support.
   - Add an applicability operator that compares objects, and a non-numeric limit reading ("shall not exceed cGMP"), so MODREL's strength correction no longer loses T5b.
   - The Phase 2D lock will need a reviewed re-baseline for F-009 s10 at that point. It must not be relaxed silently.
5. **Expand the measurement base.**
   - Build a labelled set of real generated answers that state numeric limits, durations and multi-proposition rules.
   - The 170 frozen rows cannot show either benefit or harm for these mechanisms.

## 7. Verdict: ARCHITECTURAL CHANGE REQUIRED

**Narrow fixes identified (interim review candidates, not implemented):**

| Switch | Fixes |
|---|---|
| QSCOPE | N9 |
| DAYQ | N10 |
| NNEG | N15 |
| PROP / PROPS | T3c and DX4 |

Each passed every criterion this phase measured, alone and together:
- all 7 tests' assertions;
- the 15 checks and 11 decision cases (as far as each switch reaches);
- the 11 limit probes;
- 19/19 genuine contradictions and 44/44 real readings;
- Phase 2D, F-007 and F-009 intact;
- 0 frozen-row changes.

**Not locally fixable:**

| Case | Why the local fix fails |
|---|---|
| N12 | Fixing the modal reading loses T5b. |
| DX2 | The applicability rule raises a false conflict on frozen data without object matching. |
| NN2 | Removing the "exemption" negation loses Phase 2D F-009 s10 and exposes NN1. |
| AP3 | JR's qualifier logic. |
| MR1 | Only the modal fix reaches it. |

These share one cause: operator readings are passage-level and unscoped, and the gate treats agreement as evidence whatever its source.

**Why not "NARROW FIX IDENTIFIED":** it would claim that the remaining errors are addressable by more local rules, and this phase measured the opposite for the coupled group.

**Why not "INVESTIGATE FURTHER":** the coupling mechanism is identified and demonstrated case by case.

No candidate was implemented in production.

## Artifacts (`work/`)

- **Reproduction:** `trace_cases.py` → `trace_{L0_identity,JRN2}.json`; `trace_details.py`.
- **Corpus:** `corpus_scan_2m.py` → `corpus_scan_2m.json`; `fetch_texts_2m.py` → `texts_2m.json`.
- **Diagnostics:** `build_m_cases.py` → `m_cases.json`; `eval_m_cases.py` → `m_cases_*.json`.
- **Variants:** `make_variants_m.py` → `variants/*`.
- **Battery:**
  - `run_battery.sh` → `battery_*.log`;
  - `real_controls_*.json`, `diagnostics_*.json`, `numeric_*.json`, `numeric_probes_*.json`, `controls_result_*.json`;
  - `h_cf_*.json` → `diff_cf.py` → `cf_diffs.json`;
  - `compare_diff.py` → `compare_diffs.json`;
  - `error_counts.py` → `error_counts.json`.
- **State:** `manifest_*.sha256`, `benchmark_manifest_*.sha256`, `git_status_*.txt`.
