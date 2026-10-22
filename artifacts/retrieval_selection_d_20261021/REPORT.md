# Retrieval repair D (context selection): result (2026-10-21)

**Decision: FAIL. Pre-registered criteria A3 and A5 are not met. No production change is kept.**
- The candidate code was removed and the source files restored byte-exact.
- The patch and its tests are archived in [candidate_patch/](candidate_patch/).
- Pre-registration: [PREREGISTRATION.md](PREREGISTRATION.md) `3ca91c52…`, [RUBRIC.md](RUBRIC.md) `fce098c0…`. Locked at
  15:57:32, before any candidate run or judgement.

## 1. Protected state
- **Repository:** branch main, HEAD fbd2e60, nothing staged. The prior uncommitted work and the source-text repair
  are preserved (diff hash `1bdb467e…` unchanged).
- **Benchmark backend** ([baseline/environment.json](baseline/environment.json)):
  - database `regulus`, local Homebrew PostgreSQL 18.6, repaired corpus 65,280 rows / `4f0457d7…`;
  - `SemanticFallbackRetriever` over `LexicalRetriever` with `ScopePolicy`, as `serve_ui.py` builds it;
  - context policy 8 sources, 1,200 chars per source, 3,600 total, 1,200 eCFR reserve, order `tier`.
- **Baseline:**
  - 100-question traces ([baseline/traces](baseline/traces)): 18/174 required paragraphs in context;
  - 352-row run `retrieval_baseline_20261021T102326Z_16fa796d`: identifiers 108/119, plain-language 90/157;
  - full tests 2,744 passed and 9 failed (pre-existing, [baseline/pytest_failed.txt](baseline/pytest_failed.txt));
    integration 50/50.
- **Not run:** no semantic index rebuild and no embedding model (0 loader attempts in every run).

## 2. Why guidance takes the space
- **Where the choice is made:** `select_evidence` in `src/regulus/rag/selection.py`. It walks optional evidence in
  `_optional_order`: tier by tier, registry order.
- **How coverage rows end up last:** `lexical.py:605–611` puts the section-coverage eCFR rows behind every other piece
  of evidence. In the shared discovery tier, up to 8 guidance OR-fallback chunks (~1,500 chars each) therefore compete
  first.
- **What eCFR gets:** rows enter mainly through the 1,200-char reserve. The 3 required paragraphs dropped at the soft
  budget are 70.55, 71.15(b) and 701.3(b).

## 3. Candidate tested (exactly one)
`general_evidence_order="ecfr_discovery_first"`. For general questions, within the discovery tier, eCFR passages
compete before guidance passages. Everything else is unchanged.
- Implemented in selection.py and context.py, default off.
- 11 focused unit tests (`candidate_patch/test_selection_ecfr_discovery_first.py`) check that regulatory evidence is
  kept, that guidance which matched every question word keeps its place, that guidance fills the remaining budget, and
  that named-provision and guidance questions are unaffected. All 11 passed.

## 4. Results against the pre-registered criteria

| Criterion | Result | Evidence |
|---|---|---|
| A1 required paragraphs +≥3, 0 lost | **PASS**: 18 → 21 of 174, 0 lost | [evaluation.json](evaluation.json) |
| A2 the 3 targets enter | **PASS**: 70.55 (COS-70.55-Q1), 71.15(b) (COS-71.15-Q2), 701.3(b) (COS-701.3-Q1) | idem |
| A3 0 directly relevant (R2) guidance removed | **FAIL**: 1 R2 removed | [relevance.json](relevance.json) |
| A4 12 named-provision contexts identical | **PASS**: 12/12 | evaluation.json |
| A5 352-row baseline loses no keyed target | **FAIL**: 3 guidance-docket targets lost | [candidate_eval/compare_352.json](candidate_eval/compare_352.json) |
| A6 tests | **PASS**: 2,755 passed (2,744 + 11 new), the same 9 failures; integration 50/50 | candidate_eval/pytest_full_with_candidate_code.log |
| A7 budget and order | **PASS**: no optional-only context above 8 sources or 3,600 chars; registry order (unit-tested) | evaluation.json |

**What the A3 failure is:**
- The removed passage is G129, for COS-701.12-Q2 ("Can we leave our street address off the label and show only city,
  state and ZIP?"). It comes from FDA's OTC-drug labeling Q&A and states the "city, state, ZIP if the street address is
  listed in a directory" rule.
- Both judges independently rated it R2.
- The candidate replaced it with section-coverage eCFR rows from other product categories: 101.5(d), 201.1(i),
  801.1(d), 501.5(d).

**What the A5 failure is:** three plain-language questions keyed to a guidance document lose that document
(soft_budget):
- retrieval-031, docket FDA-2007-D-0372;
- retrieval-034, docket FDA-2017-D-6821;
- retrieval-039, docket FDA-2013-D-0114.

**Gains measured:**
- **100 cosmetics questions:** +3 required paragraphs (the three targets).
- **352 rows:** plain-language in context 90 → 97, with 11 keyed targets gained in 10 records:
  - L-007 101.9(c), L-008 101.9(b), L-012 101.14, L-013 101.36, L-016 101.11;
  - U-010 830.320, G-007 201.100, Y-004 108.35, H-001 1.230;
  - PB-006 part 820 and 820.10(a).

**Questions with changed context:**
- **Improved:** COS-70.55-Q1, COS-71.15-Q2, COS-701.3-Q1.
- **Regressed:** COS-701.12-Q2 (the R2 guidance passage lost), and on the 352 rows retrieval-031, -034 and -039.
- **No required paragraph lost.**
- **Changed but not scored either way:** 77 of 100 contexts changed, 74 of them with no keyed effect.
- **Displaced:** 0 eCFR rows; 97 guidance passages.

**Context totals** (88 general questions):
- eCFR 58,821 → 157,690 chars;
- guidance 142,863 → 41,809 chars (152 → 56 passages).

**Relevance of the 97 displaced passages:**
- 1 R2 (directly relevant), 42 R1 (related, not needed), 54 R0 (not relevant).
- Assessed blind by 2 AI judges with the fixed rubric. They agreed on 128/138 items (92.8%, Cohen's κ 0.85), and a
  blind adjudicator settled the other 10.
- The pool held the 97 removed, 1 added and 40 kept "filler" passages, shuffled with no labels.
- **This was AI-assisted and not SME-validated.**
- The judging pool is [pool_blind.json](pool_blind.json). The key, [pool_key.json](pool_key.json), was never shown to
  the judges. The judgements are in [judgements.json](judgements.json).

## 5. State now (rollback already done)
- `src/regulus/rag/selection.py` `2470fb2b…` and `src/regulus/rag/context.py` `0123fe6e…` are restored from
  `pre_edit/`, identical to HEAD.
- `scripts/retrieval_baseline.py` choice list is restored, identical to HEAD.
- The candidate test file was removed from `tests/` and archived.
- **Production behaviour is the baseline.**
- **To re-apply for a future experiment:** `git apply candidate_patch/candidate.diff` and copy the test file back. Do
  not do this without authorization.

## 6. Smallest safe next experiment (proposed, not run)
**Observation:** in all 4 regressions (COS-701.12-Q2 and retrieval-031, -034, -039), the guidance that mattered was
the **top-ranked** guidance passage, in prompt position or candidate rank 1.

**Proposal:** the same candidate plus a one-passage guidance floor. The highest-ranked guidance discovery passage
keeps its turn ahead of the eCFR discovery rows; only the guidance behind it moves back.

**To run it:**
- a fresh pre-registration with the same criteria A1–A7;
- blind judging of any removed passage;
- the same 100 questions and 352 rows.

**Unknown until measured:** whether all 3 targets still fit the 3,600-char budget with one guidance passage ahead of
them.
