# Evidence supply, Phase 1 — taxonomy, ranked mechanisms, chosen intervention

Deliverables 1–3. Population: the 126 rows Stage A attributed to EVIDENCE_SUPPLY
(`artifacts/stage_a/attribution_rows.jsonl`). The full 300-question benchmark was not re-run; no
model was loaded for this phase.

```
.venv/bin/python scripts/es_phase1_trace.py      # where the governing section is lost, per stage
.venv/bin/python scripts/es_phase1_depth.py      # is it reachable at greater retrieval depth
.venv/bin/python scripts/es_phase1_taxonomy.py   # taxonomy + the frozen diagnostic subset
```

Method: replay the production path — `plan_query` → `retrieve` → `build_bundle` → `build_package` —
and record at each stage whether the benchmark's governing section is still present. A row's
mechanism is the first stage at which it disappears. Production is imported and called, never
modified.

---

## 1. The headline

**In 92 of the 126 rows (73.0%) the governing provision is reachable from the corpus and still never
reaches the prompt.** It is not a corpus problem and, for three quarters of the population, not a
fundamental retrieval-capability problem: it is a problem of which candidates get the budget.

| Rank | Mechanism | Rows | % of 126 |
|---|---|---|---|
| 1 | **A2** — not returned at `top_k=8`; the retriever *does* return it at `top_k` 24–96 | **45** | 35.7% |
| 2 | **A1a** — whole-part listing is ASCII-ordered and cut at the budget, so which sections are supplied is independent of the question | **33** | 26.2% |
| 3 | **B** — never returned at `top_k` up to 96: a recall problem depth cannot solve | 30 | 23.8% |
| 4 | **A1b** — the governing section is retrieved, then discarded by the trigram similarity cut-off, and guidance fills the budget | **14** | 11.1% |
| 5 | **C** — no live rows in the snapshot, or reserved under the QMSR | 4 | 3.2% |

A1a + A1b + A2 = 92 reachable. B + C = 34 not reachable by this retriever as configured.

## 2. The mechanisms, precisely

**A1a — the part listing is question-blind (33 rows).** A whole-part request routes to
`ECFR_EXACT_PART`, which is `WHERE part_number = … AND ordinal = 0 ORDER BY r.section_number LIMIT …`
(`src/regulus/retrieval/sql.py:58-69`). There is no relevance term anywhere in it. The rows come
back as *required* evidence with identical exact scores (measured: all 84 candidates for S-001 score
100.0), so `select_evidence` admits them in registry order until the hard ceiling, and the ceiling
falls at about 21 blocks.

The consequence is stark: **every Part 111 question in this population receives the identical first
21 sections** — 111.103, 111.105, 111.10, 111.110, 111.113, 111.117, 111.120, 111.123, … — whatever
it asked. In 32 of the 33 rows the governing section lies beyond the cut (its position in the listing
ranges from 19 to 83). S-001 asks who is subject to Part 111; 111.1 sits at position 24 and is cut,
while 111.103 (holding reserve samples) is supplied.

**A1b — the trigram cut-off discards the right section (14 rows).** These questions name no
provision, so the governing section is found by trigram match on section number or heading. The
retriever returns it — often at rank 1 of 8 — and `RagPipeline.is_useful`
(`src/regulus/rag/pipeline.py:284-291`) then drops it because trigram similarity is below
`min_trigram_similarity = 0.400`. Measured similarities for the governing sections in this stratum:
**0.316, 0.354, 0.364, 0.364, 0.376, 0.383, 0.397** below the line; 0.400, 0.408, 0.427, 0.473, 0.500
above. The guidance hits, which arrive by full text and are not subject to that rule, take the 2–3
slots the budget allows.

C-003 is the clean case: the question asks about cosmetic warning statements, 740.10(a) comes back at
rank 1 with the highest relevance score in the candidate set (1.822), and it is discarded; the prompt
is filled with three tobacco-warning guidance chunks.

**A2 — the candidate pool stops at 8 (45 rows).** At production depth the governing section is in
0 of 75 candidate sets. Holding everything else constant and varying only `top_k`:

| `top_k` | Rows whose governing section is returned (of 75) |
|---|---|
| 8 (production) | 0 (0.0%) |
| 24 | 25 (33.3%) |
| 48 | 37 (49.3%) |
| 96 | 45 (60.0%) |

Depth is not the whole fix — a returned candidate still has to win a budget slot — but it is the
precondition for 45 rows.

**B — unreachable at any tested depth (30 rows).** The retriever does not surface these at `top_k=96`.
Lexical matching cannot connect the question's words to the provision's. Out of scope for this
experiment; it needs a different retrieval method, not a different budget.

**C — corpus gap (4 rows).** 820.20 and 820.30 are reserved under the QMSR. Three of the four are
negative controls where declining is the correct answer, so these are arguably not failures of
supply at all.

## 3. The chosen intervention: ES-1, question-directed evidence admission

One mechanism — **candidate admission is question-independent** — addressed with the smallest change
that reaches all three fixable strata. **No budget number changes**: this reallocates the existing
prompt budget rather than enlarging it, which is the "minimum sufficient evidence" requirement and
the reason it is not a repeat of H4.

| Edit | Targets | What changes |
|---|---|---|
| **E1** | A1a, 33 rows | A whole-part listing is ordered by the question's own relevance — the database's `ts_rank_cd` restricted to that part, with production's own `fallback_terms` OR-query construction — instead of by section number. Same hard ceiling, same block count, different sections. A requested *section*'s own paragraphs keep their document order, untouched. |
| **E2** | A1b, 14 rows | An eCFR candidate found by trigram is no longer discarded by the `min_trigram_similarity` cut-off; it competes for the budget on relevance like every other candidate. |
| **depth** | A2, 45 rows | `top_k` 8 → 48. Candidate generation only: retrieval depth costs database time, not prompt tokens. Run as a separate arm so its contribution is separable. |

Why this and not the alternatives:

- **Not H4.** H4 expanded already-selected sections to their complete text and was rejected. ES-1
  changes *which* sections are selected and keeps one paragraph each, exactly as production does.
  No section is expanded, no ceiling is raised, no paragraph group is added.
- **Not K1.** Phase D1 refuted K1, which re-sorted evidence by numeric CFR key. ASCII order beat
  numeric order there because it accidentally favoured the substantive 1xx band. ES-1 sorts by
  neither: it sorts by the question.
- **Not a bigger context.** D1 refuted raising the context ceiling (2.4–5× latency for nothing).
  Every budget number here is identical to production.
- **B and C are excluded deliberately.** 34 rows cannot be fixed by admission and would only dilute
  the measurement.

Arms: `control` (production), `es1` (E1+E2), `es1_deep` (E1+E2+depth). Everything else — model,
prompt builder, prompt text, decoding, validation, repair, rubric, question set — is held constant,
and the generation allowance is pinned to the control arm's own per-question value so extra evidence
cannot buy extra tokens (the confound D1 identified).

Isolation: the arms are installed in-process by wrapping `regulus.rag.pipeline.select_evidence`
(the name the pipeline calls at `pipeline.py:341`) and by copying the config dataclass — the same
technique `scripts/d1_experiment.py` uses. Nothing under `src/regulus` is modified.

## 4. The frozen diagnostic subset

36 rows, frozen in `artifacts/stage_b/subset_frozen.json` **before any treatment was run**, by a
deterministic rule: a fixed per-stratum quota filled in ascending benchmark id order. B and C are
included at small quota as controls — the intervention should *not* help them, and if it appears to,
that is a sign the measurement is wrong.

| Stratum | In subset | Available |
|---|---|---|
| A1a part listing question-blind | 12 | 33 |
| A1b trigram cut-off | 6 | 14 |
| A2 reachable at greater depth | 12 | 45 |
| B unreachable at any depth | 4 | 30 |
| C corpus gap / reserved | 2 | 4 |

Scored under the frozen `regulus_substantive_rubric_v1`. The span-support validator is not a success
metric.
