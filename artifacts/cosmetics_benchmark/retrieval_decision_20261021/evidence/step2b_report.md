Written for: you and your team, deciding whether to authorise Step 3.

# Step 2B: Read-only retrieval diagnosis

**Decision: proceed to Step 3. Nothing blocks it.**

- The historical registries were reproduced exactly, and every sampled missing-evidence case now has an evidence-based cause.
- None of the 54 sampled cases is a corpus or database gap.
- The open questions are about how well a fix would work, and Step 3's controlled experiment is what answers them.

The historical benchmark used Qwen3-0.6B on CPU. Retrieval and context selection don't depend on the model: the replay reproduced them with no model loaded, and the 1.7B MLX branch in `serve_ui.py` swaps only the generator. So these findings apply unchanged to Qwen3-1.7B MLX.

## Safety and integrity

- **What ran:** the existing retrieval-only path, `production_pipeline()` with the `NoGenerator` stub in place of the model. Code and configuration were unchanged.
  - Its configuration hash matched the 20 Oct run (`6cd19913…`), and so did the system-prompt hash.
- **Read-only database access:** enforced by the server. The connection sets `default_transaction_read_only=on` plus a read-only session, and I confirmed both flags were `on` before and after.
  - My harness also refused anything that wasn't a SELECT; it refused nothing.
  - Row counts, write counters and corpus identity were unchanged.
  - The only server-side effect was ordinary read statistics and cache activity.
- **No model or index loading:** no model of any size was loaded. The semantic index loader was replaced with one that refuses to load, and it was never called. The generator stub returned empty text 68 times.
- **No file changes:** Git state, all 358 changed or untracked file hashes and the 28 relevant code files were identical before and after. No file anywhere in the project changed, including `models/`, `data/`, `.venv/` and `__pycache__`.
- **Where everything lives:** the harness and all outputs are in `/private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/ccb13d8a-5576-44ec-89de-8adef836ae63/scratchpad/s2b/`. Key findings are also saved to my memory notes, outside the repository.

## 1. Reproduction: exact

All 68 sampled questions matched the saved run, in every field:

- the candidate registry: candidates, scores, tiers, methods and order;
- the selected and dropped evidence, with drop reasons;
- every retrieval-diagnostics field.

**Sample, with no double counting:** 68 questions = 51 never retrieved (this includes the 9 Part 73 questions) + 3 budget drops + 14 controls (the 9 full-evidence and 12 exact-CFR controls overlap on 7). All 14 controls got their evidence from exact-citation lookup (12) or the definition and RC1 legs (2), which H1 and H2 don't touch.

## 2. Part 73 vs Part 1271.90: explained from the observed query

1. **The question is the query.** The AND leg passes the whole question to `websearch_to_tsquery`, and in that syntax the word **"or" is an operator**. The template "…certification **or** labeling apply?" therefore became:
   `'re' & 'develop' & … & 'restrict' & 'certif' | 'label' & 'appli'`
2. **One branch matches nothing; the other matches widely.**
   - The first branch matches **0 rows** in the entire database.
   - The second, "labeling" AND "apply", matches **415 rows**, including **all 21 rows** of 1271.90. Every one of those rows carries both words in its heading, "Are there other exceptions and what labeling requirements apply?", at the top search weight (A), so they rank highest.
3. **No target row can match.** The Part 73 sections put "labeling" in paragraph (c) or (d) and "apply" in (b), never in the same row.
4. **The fallback never ran.** The AND leg's 16 slots filled with these rows. Because it returned 3 or more rows, the OR fallback and RC1 section coverage were skipped. That happened for all 9 questions.
5. **Counterfactual, read-only:**
   - Had RC1 run, it would have ranked the target section 1st to 4th.
   - The OR query would still have ranked the target rows 17th to 1,658th, against its limit of 8.

## 3. Hypotheses

**H1 – confirmed, but it explains only 10 of the 51.**
- The gating rule is visible in the code ([lexical.py:553-575](src/regulus/retrieval/lexical.py#L553-L575)). It held in all 10 cases where the AND leg returned 3 or more rows: the 9 Part 73 questions, plus COS-71.27-Q1.
- In COS-71.27-Q1 the AND leg *did* match the target, but ranked it 22nd against its limit of 16.
- 11 of the 51 AND queries contained an OR operator because the question contained "or".
- The other 41 questions ran in fallback mode, where the AND leg returned 0 rows, so H1 doesn't apply to them.

**H2 – mixed.**
- **Refuted for the eCFR OR term list.** In all 41 fallback-mode misses, RC1 found candidates and replaced the eCFR OR query, so that query never ran. The 8-term list drove only the guidance OR leg.
- **Confirmed for RC1's term construction.** RC1 discards any word containing a digit and any word under 3 characters. That removed a distinguishing number in 26 of the 41 misses.
  - In 16 colour-additive questions (Parts 74 and 82), "D&C Red No. 17" is reduced to just **"red"**.
  - The target section then ranked anywhere from 4th to 117th, against RC1's cut of 4 sections.
- **Confirmed at paragraph level.** RC1 returns at most 2 paragraphs per section and 4 rows in total.
  - It reached the right section but returned the wrong paragraph in 2 cases (700.15, 700.25).
  - For the cross-referenced definition 70.3(v), it returned 70.3(u) or (f) instead in 5 more cases.

**H3 – mixed:**
- **Supported:** the required paragraph is missing from the registry (51 cases); a candidate was generated but ranked out (37); a candidate was retrieved but dropped by the budget (3).
- **Refuted:** absence from the corpus or database (0 of 180 required paths absent); inconsistent artifacts (0, given the exact reproduction).
- **Not observed in this sample:** the trigram usefulness filter.

## 4. Separated causes (54 missing-evidence questions)

Each question is classified by its primary required section.

| Cause | Count | Questions |
|---|---|---|
| **Corpus or database gap** | **0** | All 180 required paths are live, including **COS-80.37 (a)–(c)** and 701.13(g)(1), 700.25(d), 81.30(r), 701.12(d), 71.1(c), 700.15(c) and 701.3(r). Parts 71, 80, 81 and 700–740 are in the database but outside the saved corpus snapshot; that is a difference in scope, not an inconsistency. |
| **Not generated:** the AND leg filled from other rows and the fallback legs were skipped (H1) | 9 | The 9 Part 73 questions |
| **Not generated:** no overlap with RC1's terms | 5 | COS-71.1-Q2, 701.9-Q1, 720.7-Q1, 740.11-Q1, UC-COS-006 |
| **Ranked out:** RC1 section below the top 4 | 30 | COS-70.51, 71.6, 71.25, 71.26, 73.2180, 74.2203, 74.2208, 74.2254, 74.2304, 74.2317, 74.2322, 74.2327, 74.2340, 74.2708, 74.2710, 74.2711, 80.37, 80.38, 81.30, 82.50, 82.1104, 82.1206, 82.1254, 82.1317, 701.12, 701.13-Q1, 701.13-Q3, 720.3, 720.8, 740.19 |
| **Ranked out:** RC1 section in the top 4, but cut by the 4-row cap | 4 | COS-70.50-Q1, 74.2602a, 700.35, 740.11-Q2 |
| **Ranked out:** right section, wrong paragraph (2-row cap) | 2 | COS-700.15-Q1, 700.25-Q2 |
| **Ranked out:** AND matched but ranked 22nd of 16; fallback skipped | 1 | COS-71.27-Q1 |
| **Context-budget loss** | 3 | COS-70.55, 71.15-Q2, 701.3-Q1 |

**Budget losses:** RC1 did retrieve the required row in all three cases, but the code deliberately places RC1 rows after every other candidate. The 1,200-character eCFR reserve then admitted a *different* RC1 row, and guidance chunks filled the rest of the 3,600-character budget.

## 5. Unresolved questions (none block Step 3)

1. **Would the obvious fixes actually work?** For example: keeping colour numbers in RC1's terms, handling "or" in the AND query, or relaxing RC1's caps. This can only be tested by changing code or configuration, which Step 2B forbids. It is exactly what Step 3's controlled experiment measures.
2. **Counterfactual row caps:** for the Part 73 targets that RC1 would have ranked 3rd or 4th, it isn't established whether their paragraphs would have survived the 4-row cap. This informs the design of a fix but doesn't block one.
3. **Statute questions (20):** out of scope here. Step 2A's corpus gap stands, and it limits only claims about the statute questions.

**Decision: proceed to Step 3.** I've stopped here and am waiting for your approval.