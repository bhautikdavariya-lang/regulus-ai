# Fix B / F2 code experiment: result (2026-10-21)

**Decision: FAIL. Criterion C4 was not met: a directly relevant regulation row was displaced.**
- The candidate was removed. lexical.py (`cb5f0c9c…`) and system_identity.py (`161b5134…`) are restored byte-for-byte,
  and the diff against HEAD is empty.
- The added tests are archived in [candidate_patch/](candidate_patch/).
- Nothing enabled, committed or pushed.
- No database, index, budget, prompt or model-configuration change. No model or embedding model was run.

**Pre-registration:** [PREREGISTRATION.md](PREREGISTRATION.md) `7e8f81a2…` and [RUBRIC_ECFR.md](RUBRIC_ECFR.md)
`67c99ba8…`, locked at 17:24:32, before implementation ([LOCK.txt](LOCK.txt)). Script hashes are in
[RUN_MANIFEST.json](RUN_MANIFEST.json).

## Candidate (archived: candidate.diff `55442459…`)
- `REGULUS_SECTION_COVERAGE_WIDE=1`, off by default.
- When on, section coverage returns up to 8 rows per section and 16 in total (instead of 2 and 4) from the same 4
  top-ranked sections.
- Only the SQL row caps change: 17 lines in lexical.py, plus 3 in system_identity.py to record the switch when it is
  on.

**Regression tests:**
- 7 unit tests (`test_retrieval_section_coverage_wide.py`): default caps, wide caps, preservation of default rows,
  coverage rows still last and ranked by score, selection limits with 16 rows, fingerprint only when on, named
  provisions never call coverage.
- 3 live read-only tests (`test_section_coverage_wide_live.py`): default rows are a subset of wide rows, at most 4
  sections, and 700.25(d) becomes a candidate.
- All passed.

## Results ([evaluation.json](evaluation.json), [eval/](eval/))

| Criterion | Result |
|---|---|
| C1 required paragraphs (cosmetics) ≥ +3, 0 lost | pass: in context 18 → 21; candidates 22 → 37; 0 lost |
| C2 352: 0 keyed targets lost, class counts not lower | pass: in context 285 → 288; identifier 163 → 163, plain-language 112 → 115; 0 lost (run `retrieval_baseline_20261021T115936Z_d1142e95`) |
| C3 0 guidance passages removed | pass: 0 removed. Guidance text shrinks by 9,587 chars through extra squeezing (142,863 → 133,276). eCFR text grows 58,821 → 62,056 |
| **C4 previously successful evidence preserved** | **FAIL**: required paragraphs and keyed targets all kept, but 1 of the 9 displaced regulation rows is judged R2 (below) |
| C5 12 named-provision contexts identical | pass |
| C6 budget unchanged | pass: max 3,600 chars, ≤ 8 sources |
| C7 switch off = production | pass: 100/100 contexts identical; full suite 2,751 passed (2,744 + 7 new), the same 9 pre-existing failures; integration 53/53 (50 + 3 new) |
| C8 new tests | pass |

**Gains:**
- **Cosmetics:**
  - COS-70.19-Q2: 70.19(i);
  - COS-74.2602a-Q1: 74.2602a(c), (e).
- **352 rows:**
  - L-004: 101.5;
  - L-016: 101.11;
  - Y-004: 108.35.

**Found but dropped by the unchanged 3,600-char budget (12):**
- COS-70.50-Q1: 70.50(a)
- COS-71.15-Q2: 71.15(c)
- COS-80.10-Q1: 80.10(c), (d)
- COS-82.1104-Q1: 70.3(v)
- COS-700.13-Q2: 700.13(d)
- COS-700.25-Q2: 700.25(d)
- COS-701.3-Q1: 701.3(a), (f)
- COS-701.3-Q4: 701.3(r)
- COS-720.4-Q3: 720.4(d)
- COS-740.12-Q1: 740.12(a)

## The nine displaced regulation rows (C4)
**Method:** judged blind against RUBRIC_ECFR.md by two independent AI judges, in a pool of the 9 displaced rows plus
18 added or kept fillers, shuffled. The judges agreed on 27 of 27, so no adjudication was needed.
([judgements.json](judgements.json), pool [pool_blind.json](pool_blind.json), key [pool_key.json](pool_key.json).)
AI-assisted, not SME-validated.

| Question | Displaced row | Label |
|---|---|---|
| **COS-74.2602a-Q1** (Ext. D&C Violet No. 2 in nail enamel: use, limit, certification?) | **21 CFR 81.30(i)**: certificates for Ext. D&C Violet No. 2 and its provisional listing for externally applied cosmetics | **R2** (both judges) |
| COS-82.50-Q1 | 82.1050, 82.2050, 82.6(a) | R1 |
| COS-74.2327-Q1 | 74.2052(c) | R1 |
| COS-74.2340-Q1 | 82.1051(b) | R1 |
| COS-74.2052-Q1 | 720.4(c)(6)(ii) | R0 |
| COS-74.2203-Q1 | 720.4(c)(3)(iii) | R0 |
| COS-82.1206-Q1 | 720.4(c)(6) | R0 |

In COS-74.2602a-Q1, F2 gains the required 74.2602a(c) and (e) but displaces 81.30(i). The extra rows of 74.2602a take
the budget that 81.30(i) had. Under the fixed rule no R2 displacement is allowed, so the trade fails.

## What the evidence now says
- **F2 works at candidate level:** 22 → 37 required paragraphs found, with 0 lost.
- **Under the unchanged 3,600-char budget, only a fifth of what it finds survives selection** (3 of 15), and it starts
  displacing relevant non-keyed evidence (1 R2).
- This is the same limit the D, D2 and capacity studies reached: the binding constraint is the soft budget combined
  with the evidence order. No single knob tested so far, whether order, floor, budget or row caps, clears every
  criterion on its own.
- **Next step, for decision only and not taken:** any further attempt needs a design that changes how the budget is
  shared, and that needs its own authorization.
