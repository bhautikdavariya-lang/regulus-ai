# Retrieval capacity and evidence selection (2026-10-21)

**Method:** read-only. No production, prompt, configuration, database or index change. No model or embedding model was
run. Every candidate was an in-process setting only, and production behaviour is unchanged. The target runtime is
**Qwen3-1.7B MLX 4-bit**; the 0.6B rationale is not used as evidence.

## 1. Current limits and where they live
- **Soft budget for optional evidence** (`ContextPolicy`, [context.py:56–58](../../src/regulus/rag/context.py#L56)):
  `max_results` 8, `max_chars_per_result` 1,200, `max_total_chars` 3,600.
- **Hard ceilings for required evidence:** 24 sources, 9,000 chars, 4,000 per source.
- **eCFR reserve:** `binding_reserve_chars` 1,200, for general questions only.
- **Where they are applied:** `select_evidence` in [selection.py](../../src/regulus/rag/selection.py).
  - Reserve walk at :399–421; soft-budget walk at :424–451. A source is squeezed when at least 200 chars remain, and
    otherwise dropped.
  - The budget is charged by `_block_chars` (:170), which counts the whole rendered SOURCE block, header included.
- **Configuration:** production uses the dataclass defaults (`configured_rag_config`). They are recorded in the
  dashboard fingerprint (fingerprint.py:93).

## 2. Documented rationale, reassessed for the 1.7B MLX runtime
**3,600 chars** ([docs/lexical_rag.md:85](../../docs/lexical_rag.md)): "about 900 tokens of sources… On this CPU prefill
costs roughly 8–15 s at that size… Qwen3-0.6B does not use long contexts well."
- This rationale was written for **CPU inference and the 0.6B model**, and does not hold for the current runtime.
- The training data (SFT) was also packed to 3,600, but no adapter is used in production.

**1,200 reserve** (context.py:67–72): "one source's worth… of the three the budget is sized for." It was added so that
two 1,200-char guidance chunks could not fill the budget ahead of eCFR text. It is a fraction of the 3,600, not an
independent limit.

**Actual Qwen3-1.7B MLX 4-bit constraints** (from configuration and existing logs):

| Constraint | Value | Bearing on the budget |
|---|---|---|
| Context window | `max_position_embeddings` 65,536 (`config.json`); tokenizer max 131,072 | Not binding: the largest Step 6 prompt was 3,469 tokens, the median 1,382 |
| Memory | 8 GB unified RAM; KV cache ≈ 0.11 MB per token (28 layers × 8 KV heads × 128 × fp16) | +1,200 chars ≈ +300 tokens ≈ +35 MB. The binding rule is the existing 2,000 MB free-memory preflight, not the budget. |
| Prefill latency | Step 6 fit (100 calls): ≈ 2.2 ms per input token, ≈ 16.8 ms per output token | +1,200 chars ≈ +0.65 s; +2,400 chars ≈ +1.3 s |
| Answer quality with longer context | Not measured; that needs 1.7B inference, which is out of scope here | Open |

**Conclusion:** no documented or runtime constraint of the current system requires 3,600. Whether a different budget
helps is a recall question, answered in §3–§4.

## 3. Capacity versus upstream losses
**100 cosmetics questions** (post-repair traces, [capacity_breakdown.json](capacity_breakdown.json)):
- **Upstream, 152 + 6:** 152 required paragraphs of the general questions are never returned by any search leg, plus 6
  of the named-provision questions.
- **Capacity, 3:** only 3 are dropped by the soft budget alone: 70.55, 71.15(b) and 701.3(b).
- **Filter, 1:** 1 is rejected by the usefulness filter (700.14(a)).
- **So capacity is about 2% of the losses.**

**352-row baseline** (run `…16fa796d`; 551 keyed targets, 285 in context):
- **Upstream: 182** never become candidates.
- **Capacity only: 38**, meaning soft budget or the 8-source cap.
- **Other:** filtered 18; hard ceilings 15; filtered and budget 6; consolidation 2.
- **So capacity is about 14% of the losses** on this broader set.

**Packing, 88 general cosmetics questions:**
- **Header overhead:** 34% of the 3,600 chars is header (Corpus, long guidance titles, URL), not evidence text, at a
  median of 286 header chars per source. Contexts carry a median of 2,482 chars of text.
- **Truncation:** 155 of 373 sources are truncated.
- **Repeated documents:** 15 sources are extra chunks of a guidance document already in the context.

## 4. Bounded comparison (retrieval-only)
**Pre-registration:** [PREREGISTRATION.md](PREREGISTRATION.md) `46995ea0…`, locked before the run. Each candidate
changes one dimension only.

**Candidates:**
- **T4800 and T6000:** total budget raised to 4,800 or 6,000.
- **H3600:** budget unchanged, but each block is charged with a compact header, `SOURCE n` + Citation.

**Criteria:**
- **K1:** 0 required paragraphs lost.
- **K2:** 0 keyed targets lost on the 352 rows, with summary counts not lower.
- **K3:** 0 guidance passages removed.
- **K4:** the selection is a superset of production's, in the same order.
- **K5:** added prefill ≤ 1.5 s.

| Candidate | Required (100) | 352 keyed targets | Guidance removed | Superset / order | Added prefill (max) | Added sources (100 Qs) | Eligible |
|---|---|---|---|---|---|---|---|
| T4800 | +1 (71.15(b)), −0 | +2 (S-019 111.205, L-008 101.9(b)), **−1** (X-001 4.1) | 0 | ok | +1.22 s | 65 guidance, 14 eCFR | **no** (K2) |
| T6000 | +0, −0 | +3, **−1** (X-001 4.1) | 0 | ok | **+1.78 s** | 91 guidance, 15 eCFR | **no** (K2, K5) |
| H3600 | +1 (71.15(b)), −0 | **+15**, **−4** (retrieval-026 and K-001 50.25, G-005 201.62, X-001 4.1) | 0 | **11 violations** | +0.57 s | 3 guidance, 61 eCFR | **no** (K2, K4) |

Evidence: [evaluation.json](evaluation.json), [compare_raw.json](compare_raw.json), [runs_352/](runs_352/). The run
made 0 semantic-loader attempts and left the database unchanged.

**What this shows (retrieval and selection only):**
- **A bigger budget mostly buys guidance, not regulation.** Guidance discovery chunks compete before the
  section-coverage eCFR rows (tier order), so extra characters go to them first. 4,800 recovers 1 cosmetics paragraph;
  6,000 recovers none.
- **The budget is not the only binding limit.** With more characters, the 8-source cap binds instead: X-001 loses 21
  CFR 4.1 under both larger budgets. A budget change alone is not monotone.
- **Header overhead is the largest lever measured,** and it is a packing effect, not a category priority. Compact
  charging admits mostly short eCFR paragraphs, whose headers had cost more than their text: +15 keyed targets on the
  352 rows.
- **But compact charging is not safe as tested.** Its losses come from the 8-source cap and from passage-truncation
  shifts.
- **Implementing it would change the rendered prompt** (dropping header lines), which is not allowed in this step.

## 5. Fix B (section-coverage caps), documented and not implemented
Source: the root-cause classes ([refined_classes.json](../retrieval_rootcause_20261021/refined_classes.json),
pre-repair, 174 paragraphs). Section coverage keeps at most 2 rows per section and 4 rows in total.
- **B1:** 22 paragraphs in 16 questions. The section is found, but the paragraph lies beyond its section's 2 rows; 3 of
  them share no word with the question.
- **B2:** 5 paragraphs in 3 questions. The section ranks 3rd or 4th, but the 4-row total goes to sections 1–2.
- **Under fix A:** the caps hold 27 of the 39 paragraphs that fix A would make reachable.
- **Compared with capacity:** caps cause about 27 first losses, against 3 for capacity, on the cosmetics set.
- **Interaction:** rows that Fix B adds would enter selection at the back of the queue, like the coverage rows today, so
  the current order and budget would drop many of them. This is the same interaction measured for fixes A and D.

## 6. Recommendation
**Do not run a 1.7B runtime test of a different budget now.** The retrieval-only evidence does not show a budget worth
evaluating:
- 4,800 and 6,000 recover at most 1 cosmetics paragraph;
- they add mostly guidance;
- they lose a keyed target through the 8-source cap.

Keep 3,600 and 1,200 unchanged. The reason is not the 0.6B rationale, which no longer applies: on this evidence, more
budget does not improve recall.

**Exact next action: a pre-registered, retrieval-only measurement of Fix B at the candidate level.**
- Measure how many required paragraphs become candidates if the section-coverage leg returns more rows from its
  top-ranked sections.
- Measure where those rows would land in selection under the current order and budget.
- Make no code change: in-harness settings only, as here.
- **Why:** upstream is where the losses are (152 of 158 missing cosmetics paragraphs; 182 of 266 missing keyed targets
  on the 352 rows). The caps are the largest measured upstream cause with a concrete mechanism. Measuring first shows
  whether Fix B's gains would survive selection before anyone changes code.
- **Acceptance:** fixed before the run, in the K1–K4 form, plus the count of required paragraphs that become candidates.

**Secondary finding to keep, not to act on yet:** about a third of the context budget is per-source header text. Any
future packing change (shorter headers) changes the rendered prompt, so it needs its own authorization and, after
that, a 1.7B test.
