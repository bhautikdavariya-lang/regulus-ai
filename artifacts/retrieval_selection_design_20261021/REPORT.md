# Evidence selection: design investigation (2026-10-21)

**Method:** read-only. No code, prompt, configuration, database or index change. No model or embedding model was run.
The eCFR-only answering policy is untouched. The findings of D, D2, the capacity study and F2 are preserved, and no
rejected candidate was reapplied.

**Evidence produced here:**
- [tools/signal_check.py](tools/signal_check.py) → [signal_check.json](signal_check.json);
- [tools/signal_check2.py](tools/signal_check2.py) → [signal_check2.json](signal_check2.json).

## 1. Concrete limitations of the current selector (`select_evidence`, selection.py)
1. **Order decides, not relevance.**
   - Optional evidence competes tier by tier (structural, supporting, discovery), in registry order (`_optional_order`).
   - The registry orders discovery evidence by leg-specific scores that are not on one scale (lexical.py's own note),
     and moves every section-coverage row behind all other evidence (lexical.py:605–611).
2. **Greedy first-fit with squeezing.**
   - Each item is taken whole if it fits; otherwise it is cut to the remaining space (≥ 200 chars), or dropped.
   - There is no look-ahead: a 1,200-char item taken early blocks several later items that together carry more
     evidence.
   - 155 of 373 general-question sources are truncated.
3. **Category rules stand in for value.** The 1,200-char eCFR reserve and the tier order are blanket rules. D (eCFR
   first) and D2 (guidance floor) showed that any blanket order loses something directly relevant.
4. **No redundancy control across documents.**
   - Only near-duplicate chunks of one guidance document are consolidated.
   - Parallel provisions that state the same rule for other product categories (101.5(d), 201.1(i), 801.1(d), 501.5(d)
     in COS-701.12-Q2) each take a slot.
5. **Cost includes headers.** About 34% of the 3,600 chars is per-source header (corpus, citation, long guidance
   titles, URL), charged as if it were evidence.
6. **Interacting limits.** The 8-source cap binds as soon as more short items fit (X-001 lost 4.1 under the larger
   budgets).

## 2. Signals available to a selector (already on each `Evidence`, no new retrieval)

| Signal | Where | Comparable across legs? |
|---|---|---|
| tier, `satisfies` / `structural_for` (required / structural) | Evidence | yes (identity) |
| corpus, retrieval method(s) | RetrievalResult | yes |
| leg score (`relevance_score`): ts_rank_cd, OR rank, coverage share, trigram similarity, definition order | RetrievalResult, metadata | **no** (different scales) |
| section-coverage `section_coverage` / `paragraph_coverage` (idf-weighted share of the question) | metadata, coverage rows only | within the coverage leg |
| `heading_match`, `defines` | metadata | partial |
| citation (section, paragraph path, heading); guidance title, sector, centre, status, docket, chunk ordinal | citation, metadata | yes |
| text and its length; rendered block cost (`_block_chars`) | text | yes |
| **Derivable at selection, not stored today:** an idf-weighted question-coverage share computed from each passage's own text, the same weighting section coverage uses | (new, offline-tested here) | **yes** |

## 3. Can a leg-independent relevance signal carry selection? Measured offline

**Against blind relevance labels** (165 judged items: 138 guidance from D, 27 regulation rows from F2):

| | AUC R2 vs rest | AUC R1/R2 vs R0 | Median coverage R2 / R1 / R0 |
|---|---|---|---|
| Guidance (138; only **1** R2) | 1.00 (n = 1, not meaningful) | 0.61 | 0.74 / 0.14 / 0.11 |
| Regulation rows (27; 4 R2) | **0.58** | 0.55 | 0.38 / 0.26 / 0.26 |
| All | 0.81 | 0.62 | 0.38 / 0.16 / 0.11 |

**Against required paragraphs** (415 context passages of the 88 general questions, base and F2; 23 required):
- AUC **0.73** for required vs non-required regulation rows;
- AUC **0.80** for required vs guidance;
- medians: required 0.35, non-required eCFR 0.19, guidance 0.13.

**Reading:** the signal is informative on average, but weak where it matters most. It does not reliably separate a
directly relevant regulation row from an R1 row of the same topic. The judged set has only 5 R2 items, too few to
calibrate on.

## 4. The displacement cases
**COS-74.2602a-Q1 (F2 failure).**

| Passage | Coverage | Chars | In base / F2 |
|---|---|---|---|
| 81.30(i) (**R2**) | **0.304** | 399 | base only |
| 74.2602a(c) (required) | 0.264 | 184 | F2 only |
| 74.2602a(e) (required) | 0.262 | 133 | F2 only |
| 720.4(c)(8)(v), (vi) | 0.225 | 27, 37 | both |
| CVM GFI #246 animal food; human-food HARPC (guidance) | **0.072** | **1,200**, **588** | both |

- The R2 row and both required rows could all fit if the two 0.072 guidance chunks, which both policies kept, did not
  spend 1,788 chars first.
- **The loss was budget spent on low-value text, not a real trade-off.** A whole-set value rule resolves it.

**COS-701.12-Q2 (D failure).**

| Passage | Coverage |
|---|---|
| OTC-drug Q&A passage (**R2**) | 0.737 |
| 101.5(d) food, 201.1(i) drug, 801.1(d) device, 501.5(d) animal food | 0.737 each |
| Prescription labeling guidance | 0.042 |

- Coverage **ties exactly**: the four parallel provisions state the same rule in other product categories.
- **Coverage cannot choose here. Only redundancy can**: one parallel provision covers what the other three add.
- The cosmetic 701.12(d) itself is never retrieved (an upstream ranking loss).

**X-001** (D2, the budget candidates) and **retrieval-031/-034/-039** (D):
- These losses came from blanket rules: the floored guidance, the 8-source cap, and eCFR first.
- A value rule that keeps each item's existing position unless something of clearly higher value per char displaces
  it would not have made them. That still has to be measured.

## 5. Proposed design: value-per-cost selection with redundancy discount (S1)
**Scope:** only the soft-budget phase for general questions, where `_binding_reserve_applies`.
- Required, material, structural and exact evidence are untouched.
- The same candidates, usefulness filter, and limits: 8 sources, 1,200 chars per source, 3,600 total, hard ceilings,
  and the 1,200 eCFR reserve kept for the first experiment.
- The presented order stays registry order.

**Rule:**
1. **Value of a candidate** = the idf-weighted share of the question's lexemes its text and citation cover that the
   already-selected set does **not** cover (marginal coverage: a redundancy discount). A small tie-break keeps
   registry order.
2. **Cost** = its rendered block chars, unchanged accounting.
3. **Greedy by value per cost:** repeatedly take the candidate with the highest marginal value per char that fits
   whole. Squeezing is allowed only for the last item, as today.
4. **Fill:** once no candidate adds new coverage, fill the remaining budget in today's order. Nothing that today's
   order would add is excluded merely for being redundant if space remains.
5. **The weights** are the per-question lexeme idf already computed for section coverage. They would be passed through
   retrieval diagnostics, or computed once with the same SQL.

**Expected trade-offs:**
- **Gains:** text that covers nothing new (the 0.072 animal-food chunks) loses its slot to text that does. 81.30(i) and
  74.2602a(c), (e) can coexist. One parallel provision would be kept instead of four.
- **Risks:**
  - lexical coverage is a weak proxy: AUC 0.58 among judged regulation rows; R0 rows that share vocabulary score like
    R1;
  - ties: COS-701.12-Q2 depends on the tie-break and the fill step;
  - idf from the CFR applied to guidance text;
  - long guidance chunks are penalised by cost even when relevant, and the one R2 guidance passage seen is 1,200 chars;
  - previously successful evidence could be displaced by a higher value-per-char passage.

## 6. Test plan (offline, retrieval-only; for a future authorized step)
**Arms:** S1 is simulated in process on today's candidates. A second arm, S1 + F2, uses F2's wider section coverage, to
learn whether better selection lets F2's 15 found paragraphs survive. Both are judged separately against the same
criteria.

**Benchmarks:** the 100 cosmetics questions and the 352-row baseline, against base run `…16fa796d` and the current
production contexts.

**Fixed acceptance criteria (each arm):**
- **E1.** Required paragraphs (cosmetics) **≥ +3 and 0 lost.**
- **E2.** 352: **0 keyed targets lost**, and identifier and plain-language in-context counts not lower.
- **E3.** Every guidance passage or regulation row removed from a base context is judged blind (existing labels reused
  for an identical question, key and text). **0 R2 removed.**
- **E4. Regression set behaves:**
  - COS-74.2602a-Q1 keeps **81.30(i)**;
  - COS-701.12-Q2 keeps the **OTC-drug Q&A passage**;
  - X-001 keeps **4.1**;
  - retrieval-031, -034, -039 keep their **guidance dockets**;
  - COS-740.11-Q2 keeps the restored **740.11(b)(1)** warning row;
  - COS-70.3-Q1 keeps **70.3(f)**;
  - COS-740.12-Q1 keeps **740.12(b)** and does not lose **740.12(a)** if base had it.
- **E5.** Named-provision questions (12), docket and guidance questions: identical contexts.
- **E6.** Limits and presented order unchanged. Selection is deterministic (two runs identical).

**Targets to report** (not pass/fail beyond E1):
- 70.55 (COS-70.55-Q1);
- 71.15(b) (COS-71.15-Q2);
- 701.3(b) (COS-701.3-Q1);
- 70.19(i) (COS-70.19-Q2);
- 74.2602a(c), (e) (COS-74.2602a-Q1);
- the 352 gains L-004 101.5, L-016 101.11, Y-004 108.35.

**Rollback:** the experiment is offline and in process, so nothing persists. Any later implementation would sit behind
a default-off switch, with byte-exact `pre_edit/` restoration on failure, as in D, D2 and F2.

## 7. Recommendation
**Not sufficiently grounded to implement.**
- The only leg-independent relevance signal available is lexical coverage. It separates required from other evidence
  moderately (AUC 0.73–0.80) but not directly relevant from related regulation rows (0.58).
- One of the two displacement cases is an exact tie it cannot resolve.
- Changing production on this basis risks the same kind of loss that sank D, D2 and F2.

**Sufficiently grounded for one bounded, offline, pre-registered simulation of S1** (§5–§6, both arms), because:
- it addresses the measured cause of the F2 failure (low-value text holding budget);
- it needs no new retrieval, model or limit change;
- its criteria cover both required gains and the loss of any other directly relevant or keyed evidence.

That simulation is the recommended next step, if you authorize it.
