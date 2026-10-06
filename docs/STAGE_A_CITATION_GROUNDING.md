# Stage A / A3 — citation and grounding diagnostic

Stage A deliverable 5: do the final answer's citations actually support the claims being made?
Measurement only — nothing about the citation system is redesigned here.

Reproduce with `python3 scripts/stage_a_citations.py`; figures from
`artifacts/stage_a/citation_grounding.json`, per-row detail in `citation_rows.jsonl`.

**Finding in one line:** citations are almost always present and almost always wrong. 87.7% of
delivered answers carry a citation; **35.1% of those cite the governing provision** (28.4% once
answers that merely echoed a section named in the question are excluded), and **85.1% carry a
citation that is wrong**. The dominant error is not fabrication — it is citing a
topically-related section of the right part instead of the rule that governs.

---

## 1. Denominators

Of 300 rows: 1 ERROR (no answer), 46 withheld (a safe message, nothing to cite), leaving **253
delivered answers**, of which **222 carry at least one citation**.

A distinction the run data makes and a summary would hide: `citations` in `answers.jsonl` is the
whole marker-to-source map the pipeline *offered*, not the citations the answer *used*. A claim is
cited only if its marker appears in the delivered text, so markers are extracted from the answer
itself and only those count. CFR references written in prose ("under 21 CFR 820.10") are counted
too, since a user reads them as citations.

Authority for whether a citation supports its claim is rubric column L — hand-verified against the
regulation snapshot. The production validator's support codes are reported beside it as an
independent machine signal, never as the judgement.

## 2. L1 — citation present or absent

| | Rows | Share of 253 delivered |
|---|---|---|
| Carries a citation | 222 | 87.7% |
| No citation of any kind | 31 | 12.3% |
| — marker-attached citation | 192 | |
| — prose CFR reference only, no marker | 55 | |
| — cites only FDA guidance, no CFR section | 70 | 27.7% |

Presence is not the problem. The 70 guidance-only answers are a distinct failure: the question asked
for a binding requirement and the answer points at a guidance document as its source, which the
rubric scores L=0 regardless of whether the guidance is accurately described.

## 3. L2 — does the citation resolve to a real provision?

| | Rows |
|---|---|
| Fabricated citation (rubric M=1) | **2** — S-002, D-015 |
| Markers in the answer that resolve to no source | 13 |
| Answers citing a section absent from the snapshot | 12 |

Fabrication is rare — 2 of 299 scored rows — and it still fails gate G2, which is zero-tolerance.
The 13 unresolved markers are a separate, mechanical defect: the answer displays `[n]` for an `n`
the citation map does not contain, so the user sees a citation that cannot be followed.

## 4. L3 and L4 — does the citation point to the governing rule, or merely to related words?

This is the core of the diagnostic.

| Of the 222 cited answers | Rows | Share |
|---|---|---|
| Cites the governing section | 78 | **35.1%** |
| — of which the match is only a section the question itself named | 15 | 6.8% |
| — **located a governing section the question did not give** | **63** | **28.4%** |
| Does not | 144 | 64.9% |
| — cites the **right part, wrong section** | 63 | 28.4% |
| — cites the **wrong part entirely** | 18 | 8.1% |
| — cites no CFR section at all (guidance only) | 45 | 20.3% |

**The right part, wrong section case is the signature failure.** 63 answers reach the correct body of
regulation and then cite a neighbouring section — 111.x sections for a 111.x question, 820.10 where
820.1(a) governs, 507.53(d) for a 117.180(d) question. These are exactly the answers that a
lexical-overlap check cannot distinguish from correct ones, because a neighbouring section of the
same part shares almost all of its vocabulary. It is the mechanism behind the 85.5% false-pass rate
in [STAGE_A_VALIDATOR_LIMITATION.md](STAGE_A_VALIDATOR_LIMITATION.md).

By question type (delivered answers):

| Type | n | Cites governing section | L=1 |
|---|---|---|---|
| Direct Lookup | 164 | 53 | 21 |
| Cross-Reference | 17 | 5 | 2 |
| Application | 16 | 3 | 0 |
| Distinction | 15 | 4 | 0 |
| Negative Control | 15 | 4 | 8 |
| Scope/Boundary | 14 | 0 | 4 |
| Temporal/Version | 11 | 9 ※ | **0** |
| Abstention | 1 | 0 | 0 |

※ The Temporal/Version line needs unpacking, and unpacking it exposes a limit of the mechanical
match. On 9 of the 11 rows the only CFR reference in the answer is the **reserved** section the
question itself named — 820.30, 820.198, 820.20 and so on. The draft key lists that reserved section,
so a section-level match scores it as "cites the governing section" when what the answer did was
echo the question. On **none** of the 11 rows does the answer name the provision that now carries the
requirement (820.10, 820.35). All 11 score L=0.

That is the opposite of a citation-retrieval success: the answer repeats the reserved number and
treats it as in force. Temporal reasoning, not citation retrieval, is the constraint.

Across all 222 cited answers, **15 of the 78 governing-section matches are satisfied entirely by
sections the question already named.** The genuine rate at which the system *locates* a governing
provision the user did not supply is therefore 63 of 222 (28.4%), not 35.1%.

## 5. L5 — unsupported claims despite a citation

| Of the 222 cited answers | Rows | Share |
|---|---|---|
| Citation present, rubric L=0 (the citation is wrong) | **189** | **85.1%** |
| Citation present and L=1 | 33 | 14.9% |
| Cites the governing section and is **still** substantively wrong (N<2) | **70** | |
| Validator raised at least one support code | 80 | |

Two results worth separating.

**A correct citation does not make a correct answer.** 70 answers cite the governing section and
still score N<2. Grounding and correctness are independent axes, which is why Stage A keeps them as
separate questions and why they must never be collapsed into one score.

**The validator's support signal has 38% sensitivity as a citation check.** Cross-tabulated against
the hand-verified L column:

| | L=0 (citation wrong) | L=1 (citation right) |
|---|---|---|
| Support codes raised | 72 | 8 |
| No support codes | **117** | 25 |

It misses 117 of the 189 wrong citations and fires on 8 right ones. Codes raised, in order:
`low_overlap_with_cited_source` (57), `uncited_statement` (19), `provision_citation_mismatch` (18),
`unsupported_claim` (15), `condition_not_in_cited_source` (14), `synthesis_citation_gap` (6),
`paragraph_misattribution` (3).

The reason is structural and the same one that defeats the content-recall proxy: the codes are
computed from overlap between the claim and the cited source's text, and a neighbouring section of
the same part overlaps heavily. The validator can see that a sentence has *no* support; it cannot see
that a sentence is supported by the *wrong* provision.

## 6. How much of the baseline is a citation/grounding failure?

Very little, and this is the result that should change priorities. A failure is a citation failure
only if the substance was right and the row failed on grounding alone — N=2, O≥1, P=1, failing on L,
M or Q:

- **2 rows certain** (S-009, M-020) — 0.7% of the 290 non-passing rows.
- **8 rows upper bound** (2.8%), if an SME rules that the borderline citation defects on D-013,
  E-007, V-002, P-007, P-012 and H-001 are disqualifying. Those six scored N=2 and their only
  unresolved question is the citation verdict; see
  [STAGE_A_BASELINE_REPORT.md](STAGE_A_BASELINE_REPORT.md) §6.

The other 181 wrongly-cited answers are also substantively wrong. **Fixing citation selection on
those rows would not produce a passing answer.** Citation accuracy is a gate the product cannot
currently clear (G1 at 11.7% against a 99% threshold) and it must be fixed for acceptance — but it
is not what is holding the pass rate at 3.3%.

## 7. Limits of this diagnostic

1. **"Supports the claim" rests on the hand-scored L column**, one reviewer, no second-reviewer
   agreement figure. The mechanical layers (L1–L4) are reproducible from the run data; L5 is not.
2. **Governing-section matching is at section granularity, and credits echo.** An answer citing
   820.1 where 820.1(a)(2) governs counts as citing the governing section here, while rubric L
   requires paragraph accuracy wherever a paragraph-level requirement is asserted; and 15 matches
   are satisfied by a section the question already named. The mechanical L3 figure is therefore an
   **upper bound** on citation correctness — the true rate is the L=1 rate, 33 of 222.
3. **The draft key defines "governing".** 11 rows are flagged key-in-doubt and are excluded from the
   attribution in the baseline report, but they are included in the tables above.
4. **Guidance-tier correctness is not assessed.** Whether a cited guidance document is accurately
   described was not separately measured; citing guidance for a binding requirement fails L either
   way.
