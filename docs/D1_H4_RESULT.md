# D1 · H4 — evidence completeness: controlled experiment result

2026-10-05. n = 3 (M-002, M-003, M-004), Part 820, keyed section 820.1. Model `Qwen/Qwen3-0.6B`
rev `c1899de2`, float32, CPU. Production unchanged: `git diff f570776~1 HEAD --stat -- src/ configs/`
returns nothing.

> **Verdict: H4 is UNSUPPORTED — and the intervention is actively harmful.**
>
> Evidence completeness was delivered in full (27.8% → 100%). Substantive accuracy improved on
> **0 of 3** rows. All three H4 answers are substantively wrong, and on **2 of 3** rows H4 converted a
> correctly-withheld wrong answer into a wrong answer **delivered to the user**.

---

## A. Implementation finding — where section completeness was lost

**At the SQL layer, in retrieval. Not in downstream truncation.**

`src/regulus/retrieval/sql.py:64`, `ECFR_EXACT_PART`:

```sql
WHERE r.part_number = %(part_number)s
  AND r.ordinal = 0          -- "the first live row of each section in the part"
ORDER BY r.section_number
```

`RetrievalResult.text = row["body_text"]` (`lexical.py:653`) is 1:1 with a single DB row, so **one row
per section means one paragraph per section.**

Ruled out as causes: `_truncate` never fires (820.1's supplied paragraph is 1,469 chars against a
4,000-char `required_max_chars_per_result` cap; `truncated=False` on every row);
`consolidate_evidence` only dedupes and has no paragraph-merging behaviour; the character ceiling cuts
sections, not paragraphs.

**The complete section was available upstream the whole time.** Production supplied row 1 of 10 for
820.1 — paragraph `(a) Applicability`, 1,469 of 5,277 chars — and withheld `(a)(1)`–`(a)(4)`, `(b)`,
`(c)`, `(d)`.

Data flow: `plan_query` → `exact_cfr` (`lexical.py:525`) → `_ecfr_result` → `relate` → `order_evidence`
→ `build_bundle` (`pipeline.py:343`) → `check_coverage` → `select_evidence` (`selection.py:164`) →
`required_only` (Stage 6) → `consolidate_evidence` (Stage 8) → `render_selection` / `render_source`.

## B. Intervention

`install_h4_complete_sections(db)` in `scripts/d1_experiment.py`, arm `h4`. It wraps
`regulus.rag.pipeline.select_evidence`, calls the **real** function under the **unchanged production
policy** first — so the section set, their order and the keyed section's rank are identical to
production by construction — then replaces each selected eCFR section's text with all of its
paragraphs in `path_ordinal, ordinal` order, as **one source block per section**: the same block that
was already there, now complete.

Deliberately not done, because each would confound completeness with something else:

- **no ceiling change** — raising `hard_max_total_chars` would let selection admit *more sections*;
- no extra or neighbouring sections, no whole-Part retrieval;
- no reordering, re-ranking, or change to which requirement anything satisfies;
- the per-result cap is not re-applied to the expanded text, so expansion cannot truncate;
- generation budget **pinned to Arm 0's exact integer** (1,171 on all three rows; the adaptive policy
  would have granted 1,536 — the pin held it down).

Model, system prompt, decoding, thinking mode, citation architecture, post-processing, benchmark
questions and evaluator: all untouched.

## C. Evidence verification — the §5 gate, run before any model call

`scripts/h4_verify.py`, stub generator, so `coverage → select_evidence → required_only →
consolidate_evidence` all executed. **Identical on all three rows:**

| Metric | Arm 0 | H4 |
|---|---:|---:|
| Total evidence sections | 6 | **6 — unchanged** |
| Exact target section present | yes | yes |
| Exact target section rank | **2** | **2 — unchanged** |
| Target paragraphs available | 10 | 10 |
| Target paragraphs supplied | **1** | **10 (all)** |
| Target chars supplied | 1,469 | **5,286** |
| Target chars available | 5,277 | 5,277 |
| **Target section completeness** | **27.8%** | **100%** |
| Evidence chars, all sources | 3,347 | 15,864 |
| Evidence tokens | 773 | 3,580 |
| Prompt tokens | ~1,677 | ~4,548 |

Section list byte-identical in both arms. **GATE: PASS.** The model demonstrably received the
complete governing provision, including verbatim:

> **820.1(a)(2)** — "*Components or parts.* The provisions of this part **do not apply** to
> manufacturers of components or parts of finished devices, but such manufacturers are encouraged to
> consider provisions of this regulation as appropriate."
>
> **820.1(a)(3)** — "*Blood and blood components.* The provisions of this part **do not apply** to
> manufacturers of blood and blood components used for transfusion or for further manufacturing. Such
> manufacturers are subject to subchapter F of this chapter."

## D. Results

| Row | Prod recall | H4 recall | Prod pass | H4 pass | Prod gen tokens | H4 gen tokens | Prod latency | H4 latency |
|---|---:|---:|---|---|---:|---:|---:|---:|
| M-002 | 0.143 | 0.143 | FAIL | FAIL | 91 | 198 | 10.1 s | 44.2 s |
| M-003 | 0.800 | 0.800 | PASS * | PASS * | 108 | 250 | 11.7 s | 42.4 s |
| M-004 | 0.300 | 0.400 | FAIL | FAIL | 320 | 141 | 32.8 s | 25.4 s |
| **mean / total** | **0.414** | **0.448** | **1/3** | **1/3** | 519 | 589 | 55 s | 112 s |

\* M-003's PASS is a **proxy artefact** — see §E.

Termination and safety-net behaviour:

| | Arm 0 | H4 |
|---|---|---|
| reached end-of-turn | 2/3 | **3/3** |
| repetition stop | 1 (M-004) | **0** |
| answer withheld by validation | **3/3** | **1/3** |
| answer delivered to user | 0/3 | **2/3 — both wrong** |

## E. Interpretation — **UNSUPPORTED**

Against the §8 criteria: strong positive needed ≥2/3 meaningful improvement; weak positive needed
1/3 substantial. Observed: **0/3**. Mean recall moved +0.034, no verdict changed.

**Substantively, all three H4 answers are wrong, and the model contradicted text it had been given
verbatim.**

- **M-002** — *"Are manufacturers of components and parts of finished devices subject to Part 820?"*
  Correct answer: **no** (820.1(a)(2)). H4 answered *"Manufacturers of components and parts of
  finished devices subject to 21 CFR Part 820"* — the opposite of a sentence sitting in its own prompt.
- **M-003** — *"Are manufacturers of blood and blood components subject to Part 820?"* Correct answer:
  **no**, they fall under subchapter F / Part 606 (820.1(a)(3)). H4 answered *"are subject to 21 CFR
  Part 820"* and then **fabricated** *"applies to devices that support or sustain life, including blood
  and blood components."*
- **M-004** — HCT/Ps. H4 cited 820.10 for a class II/III rule, then concluded *"the available
  regulatory sources do not provide enough information to answer this"* — while holding 820.1(a)(4),
  which answers it directly.

**Two adverse findings, both more consequential than the null result.**

1. **H4 disabled the safety net.** Withholding fell from 3/3 to 1/3, so two substantively wrong
   answers reached the user that production had correctly suppressed. The validator's criterion is
   *span support* — whether sentences can be matched to evidence text — not *responsiveness*. More
   evidence text means more of the model's sentences find a matching span, so validation passes while
   the answer remains wrong. Completeness made the output **more plausible and no more correct**,
   which is the worst combination in a regulatory QA system.
2. **The mechanical proxy is unreliable, in the optimistic direction.** M-003 scores **0.80 recall and
   PASS in both arms** while asserting the exact opposite of the governing rule — because the question
   and the wrong answer share content words ("blood and blood components", "Part 820"). Under the
   acceptance rubric all three rows would fail on substantive correctness (N = 0), and M-003 would
   additionally fail the fabrication gate (M = 1), which is absolute. **This retrospectively qualifies
   every pass count in Phase D1, including Arm 0's 8 of 20, in the same direction.**

**On the §9 latency safeguard: no runaway.** Latency doubled (55 s → 112 s) but every row terminated
on end-of-turn, 3/3 versus 2/3, and H4 *fixed* M-004's repetition loop (320 tokens with
`stop_reason=repetition` → 141 tokens, clean stop). One source block per section, rather than Arm 4's
55 blocks, is what kept generation stable — Arm 4's M-002 ran past 24 minutes without completing.
Operationally H4 is viable; it simply does not work.

**Confidence: high, for a small sample.** n = 3, one section, two question types — but the result does
not rest on the proxy or on statistics. It rests on the model being handed "*the provisions of this
part do not apply to manufacturers of components or parts*" and answering that they are subject. No
larger sample is needed to interpret that.

## F. Recommendation

> **2 — H4 unsupported → close the D1 retrieval hypothesis and proceed to capability testing.**

Phase D1 has now eliminated every retrieval explanation by direct measurement: ordering (Arm 1, 0
gained / 3 lost), position (4 rank improvements, 0 verdict changes), breadth and deletion (Arm 2
7 vs 8; Arm 3 4 vs 4), and completeness (H4, 0 of 3 with the provision supplied verbatim at 100%).
**Do not expand H4. Do not implement it in production** — it would ship two wrong answers that are
currently suppressed.

Two narrowly scoped items follow from the adverse findings, neither of which is a redesign:

1. **Re-score the acceptance results against the rubric, not the content-recall proxy.** M-003 proves
   the proxy passes flatly incorrect answers. This is analysis work, no compute, and it affects every
   figure quoted in this phase.
2. **Treat the validator's span-support criterion as a known limitation**, recorded not fixed: it
   suppresses wrong answers when evidence is thin and stops suppressing them when evidence is rich,
   which is the opposite of the desired behaviour. No change is proposed here.

**The critical path is now CP-01 on a 24 GB CUDA host.** Reasoning categories scored 0/20
Cross-Reference, 0/20 Application, 0/23 Distinction, 0/11 Temporal across the 300-question run, and no
prompt, evidence, ordering, breadth, completeness or configuration change in this entire phase has
moved a reasoning row. 8 GB cannot hold a 4B model at float32, and quantising it would break the
equal-dtype rule that makes the comparison valid.

## Artefacts

`scripts/d1_experiment.py` (`install_h4_complete_sections`, arm `h4`) ·
`scripts/h4_verify.py` (§5 gate) ·
`artifacts/diagnostics/d1_experiment/armh4.json` (full rows: raw output, delivered answer, prompt
hashes, token counts, EOS, repair state) · `artifacts/diagnostics/d1_experiment/arm0.json` (baseline,
reused frozen — same deterministic path, bit-identity established on 32 control rows in this phase) ·
`logs/d1_h4.log`. Commit `9ee19d4` (arm + gate).
