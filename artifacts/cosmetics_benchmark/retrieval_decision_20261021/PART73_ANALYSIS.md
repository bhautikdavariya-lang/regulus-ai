# Part 73 failure analysis after the literal-OR experiment (2026-10-21)

**Decision: no change.** The literal-OR switch stays off. No ranking, budget, row-cap or database change is made for these five questions.

## Evidence base
- **Trace:** part73_trace/<ID>.json, from tools/trace_part73.py. It covers the 9 questions only, under the saved
  experiment's switch-on conditions, read-only, with no model.
- **Self-checks, all passing 9/9:**
  - prompt and drops reproduce runs/C2_on_cosmetics.jsonl exactly;
  - the step-by-step budget replay equals the real selection;
  - section scores recomputed from lexeme weights equal the leg's scores;
  - 0 semantic loads; database unchanged.
- **Analysis:** workflow (part73_trace/workflow_result.json) with 5 failure analysts, 1 control analyst, 2 adversarial
  verifiers (a ranking lens and a selection/database lens) and 1 judge. The load-bearing numbers below were re-checked
  directly against the traces.

## Shared finding (all 9)
- The eCFR all-words and trigram legs return 0 rows, so section coverage (RC1, discovery tier) is the only eCFR source.
- The guidance all-words search still reads "or" as an operator, as designed (it was outside the switch). Its 16 rows
  are supporting tier, and the first two fill the 3,600-char soft budget in every case:
  - HCT/P donor eligibility, block 1,598;
  - food hazard analysis, squeezed to fit.
- So an eCFR row reaches the prompt only through the 1,200-char eCFR reserve, which takes 2–3 rows in tier order, then
  registry order.

| Question | Required evidence (core ¶) | Stored text | Evidence rank (RC1) | Selection outcome | Primary cause |
|---|---|---|---|---|---|
| COS-73.2085-Q1 caramel | 73.2085(a)–(d); core (b) | complete | Not returned. Section score 0.7818 vs 0.8502 for both bronze-powder sections 73.1646/73.2646 | Never a candidate. Reserve: 73.1646(e) 404, 73.2646(d) 404, 73.1646(c) 377 | **Competing related provisions:** "bronzing" → *bronz* (idf 8.27) beats *caramel* (7.02), credited twice (section + best ¶) |
| COS-73.2095-Q1 β-carotene | 73.2095(a)–(d); core (b) | complete | 73.2095(d) RC1 rank 3 (0.7238); core (b) not returned (row 6) | Reserve: 70.3(u) 1,053 alone; 1,053 + 397 = 1,450 > 1,200. Soft budget full (3,600) → dropped | **Context budget** (secondary: 70.3 ranks first via *tint* 7.36 from "tinted") |
| COS-73.2298-Q1 ferric ammonium ferrocyanide | 73.2298(a)–(d); core (b) | complete | (d) rank 3, (b) rank 4 (1.1738) vs drug twin 73.1298 (1.3374) | Reserve: 73.1298(a)(1) 664 + (e) 419 = 1,083; +416 = 1,499 > 1,200. Soft budget full → both dropped | **Context budget** (secondary: drug twin ahead via *blue* 4.89) |
| COS-73.2645-Q1 aluminum powder | 73.2645(a)–(d); core (b) | complete | Not returned. Section 4th of 4 (0.9612, exact tie with drug twin 73.1645, lost on section number); rows would be 5th–6th of 4 | Never a candidate. Reserve: 73.1645(e) 398, 74.2053(c) 527 | **Competing related provisions:** 74.2053 via *eyelin* 7.87; 73.1646 via *metal* 3.72; tie with 73.1645. The 4-row cap is the mechanism (verifiers split on the label) |
| COS-73.2725-Q1 ultramarines | 73.2725(a)–(e); core (c) | (c) complete; **(b) truncated** (no Pb/As/Hg limits) | (c) RC1 rank 1 (1.1721) | Reserve walks heading-promoted 73.50(e) 404 + (c) 409 = 813 first; +399 = 1,212 > 1,200 (misses by 12). Soft budget full → dropped | **Context budget** (truncated (b) not decisive) |
| COS-73.2250-Q1 control | core (c) | — | 73.2250(e) rank 4 | Reserved first (heading-promoted) → context rank 1 | passed at section level; core (c) not in context |
| COS-73.2575-Q1 control | core (b) | — | (b) rank 2 (ties drug twin) | Reserved second → in context | passed; core in context |
| COS-73.2646-Q1 control | core (b) | — | (b) rank 2 (ties drug twin) | Reserved second → in context | passed; core in context |
| COS-73.2647-Q1 control | core (b) | — | (d) rank 2 (ties drug twin) | (d) reserved; core (b) dropped for budget | passed at section level; core (b) not in context |

- **Primary causes:** context budget 3; competing related provisions 2; database content 0 (73.2725(b) is truncated but not
  decisive); row cap 0 as primary.
- **Core paragraph:** in context for 2 of the 9 (73.2575, 73.2646).
- **Drug vs cosmetic use** is not the distinguishing feature. The twins cover identical lexemes and tie exactly, and no
  question contains "cosmetic". The decisive words are product descriptors: bronzing, tinted, eyeliner, metallic, blue.

## Why no change
| Direction | Fixes | Verdict |
|---|---|---|
| Improve cosmetic vs drug distinction | 0 of 5 | Not supported. Twins tie on identical text; the competitors win on descriptor words, and in COS-73.2085 the competitor is itself a cosmetic section. |
| Repair truncated row | 0 of 5 | 73.2725(b) is truncated but caused no retrieval failure. A data-quality item for answer completeness, outside this decision. |
| Selection: section-first reserve walk (best of the four; the judge's pick) | +2 (73.2298 at section level only, 73.2725 core (c)); projected 6/9 | **Not justified:** (1) its benefit exists only with the literal-OR switch on, which failed acceptance and stays off; with the switch off these questions never reach RC1, so the change does nothing for them; (2) 6/9 is still below the 7/9 threshold; (3) it changes the reserve walk for any general question with ≥2 reserved rows (148 of 194 in the 352 set with the switch off, as in production; 147 with it on; verified from runs/P1_off_352 and P2_on_352), the zero-sum lever family that netted 0 in Phases 2–4; (4) one known harm path (a key section's second, discovery-tier row displaced) is unresolved for COS-740.12-Q1 and COS-720.4-Q3. |
| No change | — | Chosen: no evidence-backed fix reaches the threshold without displacement risk. |

**Rollback status:** nothing to roll back. No file outside this folder changed during the analysis. The literal-OR code
remains in the tree, switch off.
