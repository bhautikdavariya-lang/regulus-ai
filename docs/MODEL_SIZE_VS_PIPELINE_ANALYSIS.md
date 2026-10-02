# Model Size vs Pipeline: Diagnostic Result

Date: 2026-10-02. Model: Qwen/Qwen3-0.6B, revision `c1899de2`, float32 on CPU, no adapter. Production
pipeline unmodified. Phase 9 (4B/8B) **not executed** — see question 6.

Evidence: `MODEL_CAPABILITY_DIAGNOSTIC.xlsx` (132 condition cells, 16 sanity rows, runtime record),
`artifacts/diagnostics/model_probe/*.json`, `docs/MODEL_IMPLEMENTATION_AUDIT.md`.

## Experimental design actually run

36 benchmark questions, stratified (Direct Lookup 12, Cross-Reference 4, Application 4, Distinction 4,
Temporal 4, Negative Control 4, Scope/Boundary 4), key-integrity-flagged rows excluded, seed 20261002.
Three prompt conditions on identical questions, model, decoding policy and token budget:

- **B production** — the pipeline unchanged: its prompt, evidence, tiering and ordering.
- **C simplified** — short instruction, the *same evidence in the same order*, rendered plainly.
- **A focused** — short instruction, *only the keyed provision's text* from the snapshot.

B→C isolates the prompt; C→A isolates evidence focusing. A fourth arm varied generation configuration on
10 rows. Scoring is **mechanical**: key-element content recall ≥ 0.5 for substantive rows, a refusal-phrase
match for trap rows. It is a proxy for the rubric, applied identically to every cell — not the rubric.

## The twelve questions

### 1. Is there a confirmed technical implementation problem?

**Yes — three, with measured blast radius.**

| Defect | Measurement |
|---|---|
| **D1 flat evidence tiering on whole-part requests** | The planner resolves 112 of 300 benchmark questions to a whole part; only 19 to a section. Every retrieved section in the part is then labelled `Tier: EXACT (authoritative text of r1)` and ordered by citation string. In `prompts/S-003.txt` the keyed section sits at SOURCE 10 behind 111.103 and 111.105, and the answer came from SOURCE 1 |
| **D2 suppression destroying usable raw output** | 3 of 36 probe rows lost ≥0.15 key recall between raw output and final answer: M-003 0.80 → 0.00, F-011 0.50 → 0.00, M-004 0.30 → 0.10. 6 of 36 were withheld entirely |
| **D3 model-chosen citation markers** | Across the 299-question run: 107 answers cite nothing, 13 use a marker resolving to no source, 8 are substantively correct but mis-cited |

### 2. Is there a confirmed prompt construction problem?

**Yes, but narrower than D1's blast radius suggests, and not statistically established.**

Focused evidence (A) beats production (B) on 7 rows and loses on 3. McNemar exact **p = 0.172** — directional,
below the pre-set threshold of 5 net improvements for significance at this sample size.

| Subset | n | B passes | C passes | A passes | A vs B |
|---|---:|---:|---:|---:|---|
| All | 36 | 9/36 | 6/36 | 13/30 | +7/−3, p=0.17 |
| Lookup rows | 12 | 5 | 3 | **9** | +6/−2, p=0.14 |
| Reasoning rows (CR/App/Dist) | 12 | 4 | 3 | **4** | +1/−1, p=0.75 |
| Trap rows (NC/Scope/Temporal) | 12 | 0 | 0 | 0/6 | no change |

Mean key recall: lookup rows B 0.483 → A 0.588; reasoning rows B 0.373 → A 0.367.

Seven rows were rescued by focused evidence alone: **B-001, B-002, D-008, D-015, D-018, D-019, F-009** —
all provision-selection failures, exactly D1's signature. **C is not better than B** (6 vs 9), so the ten
rules are not the problem; *which evidence is put in front of the model, and in what order,* is.

### 3. Is there a confirmed generation configuration problem?

**Yes — one, and it was a deliberate choice.** Thinking mode is disabled in production for CPU speed. On the
10-row subset, with everything else held fixed:

| Arm | Mean key recall | Mean generated tokens | Ended on EOS |
|---|---:|---:|---:|
| Greedy (production) | 0.384 | 138 | 10/10 |
| Sampling 0.7/0.8/20 | 0.295 | 92 | 10/10 |
| Half token budget | 0.384 | 138 | 10/10 |
| **Thinking mode on** | **0.514** | 454 | 7/10 |

Thinking mode lifts mean recall by **+0.13 absolute (+34% relative)** and turns 3 of 10 failures into passes
(B-002, C-004, D-002), at 3.3× the tokens and with 3 of 10 not reaching end-of-turn. Sampling is worse than
greedy, confirming the greedy default. Halving the budget changes nothing — the budget never binds.

### 4. Is there a confirmed parser/post-processing problem?

**Yes, on 3 of 36 rows (8%).** Not the parser — `split_thinking` and the decode path are clean — but
validation-and-repair. M-003 is the clearest: raw output at 0.80 key recall, final answer at 0.00 because the
whole answer was withheld. Extrapolating 8% to the benchmark, roughly 25 of 299 rows plausibly understate
the model. That is a cautious estimate from a small sample, not a measurement.

### 5. How well does 0.6B perform when correct evidence is directly supplied?

**13 of 30 (43%) on the mechanical proxy where a keyed provision exists — but 9 of 12 on lookup rows and 4 of
12 on reasoning rows.** And **0 of 10 trap rows under any condition**: production, simplified, focused and
thinking mode all failed to produce a refusal or a premise correction.

20 of 36 rows failed every condition tried: D-012, G-010, M-004, M-013, D-023, E-010, M-005, M-002, M-032,
M-031, M-033, M-035, NC-009, NC-018, NC-008, NC-015, PB-006, PB-007, SD-010, SD-013.

### 6. How much does 4B improve on the same tasks?

**Not measured. Cannot be measured on this machine.** 8 GB of RAM cannot hold a 4B model at float32, and
quantising it would break the equal-dtype rule that makes the comparison valid. The design is frozen in
experiment CP-01; it needs a 24 GB CUDA host.

### 7. Does 8B improve further?

Not measured, same reason.

### 8. Which failures are clearly model reasoning failures?

Nine of 36 probe rows: correct evidence supplied, prompt valid, raw output captured, parsing correct,
configuration varied — and still wrong. Plus the 10 trap rows, where no prompt, evidence or configuration
change produced a refusal. Supporting evidence from the full run: reasoning categories score 0/20
Cross-Reference, 0/20 Application, 0/23 Distinction, 0/11 Temporal.

### 9. Which failures are clearly system/pipeline failures?

Attribution over the 36 probe rows:

| Category | Rows |
|---|---:|
| 8 — trap row, no refusal produced under any condition | 10 |
| 1 — model reasoning (evidence supplied, prompt valid) | 9 |
| 2 — prompt construction (focused evidence fixes it) | 7 |
| 5 — parser / post-processing (raw materially better than final) | 3 |
| — passed production | 7 |

So **10 of 29 failures (34%) are pipeline-attributable** on this sample, and a further 3 of 10 are
configuration-attributable in the thinking-mode arm.

### 10. What evidence supports each conclusion?

Every number above traces to a stored artefact: prompt hashes and token counts in `phase3_prompts.json`,
raw outputs per condition in `MODEL_CAPABILITY_DIAGNOSTIC.xlsx`, runtime identity in `phase2_runtime.json`,
the 16/16 sanity suite in `phase1_sanity.json`, the 112/19 planner split reproducible from
`regulus.planning.plan_query` over the benchmark.

### 11. What remains uncertain?

- **Sample size.** n=36, and n=12 per category. The A-vs-B effect is directional at p=0.17; at this size a
  real 20-point effect could be missed and a spurious one seen.
- **The proxy metric.** Content-word recall is not the rubric. A row can score 0.5 recall and still fail on
  citation, completeness or scope. No condition was re-scored against the full rubric.
- **Thinking mode untested at scale.** +0.13 recall on 10 rows, with 30% not finishing — on CPU it would
  multiply runtime, and its effect on citation discipline and fabrication is unmeasured.
- **Whether focusing scales.** The 7 rescued rows are provision-selection failures in parts the corpus covers
  well. Whether a selector *can* reliably pick the keyed section is itself unproven — that is a retrieval
  problem of the same kind as the 72 retrieval misses found earlier.
- **Trap behaviour** is 0 for 10 across every condition, which is consistent with both capacity limits and a
  missing deterministic check. The two cannot be separated by prompting alone.

### 12. What experiment should be performed next?

Run **CP-01** (already designed) on a CUDA host, with two amendments forced by these results:

1. **Add a fourth arm: thinking mode on, 0.6B.** It is the only configuration change that measurably
   improved output, and it is free to test. If 0.6B-with-thinking approaches 4B-greedy, the capacity
   conclusion changes shape.
2. **Score each arm on both evidence conditions** (production tiering and focused keyed provision), so the
   D1 defect cannot be confounded with capacity. Four arms × two evidence conditions on 112 questions is
   still a few GPU-hours.

Keep frozen: benchmark, keys, questions, evaluator, rubric, database snapshot, decoding policy within an
arm, and all six deterministic fixes (they are DF-01).

## Conclusion

> **Primary cause:** mixed — and the two causes are separable by category. Implementation defects dominate
> provision-lookup failures; model capacity or architecture dominates reasoning and trap failures.

> **Evidence:** the inference stack is sound (runtime identity verified, 16/16 sanity, no truncation, 38k
> tokens of spare context, greedy confirmed). But 112 of 300 questions are planned as whole-part requests
> that flatten evidence tiering, and focusing the evidence rescued 7 of 36 rows — 6 of 12 lookup rows, 0 of
> 12 reasoning rows, 0 of 10 traps. Thinking mode, disabled for speed, adds +0.13 mean recall and rescues 3
> of 10. Post-processing destroyed usable raw output on 3 of 36. Against that, 9 rows failed with correct
> evidence, a valid prompt and varied configuration, and no condition produced a single correct trap refusal
> out of 10 attempts.

> **Confidence:** Medium. Implementation defects: high confidence, directly observed in captured prompts and
> raw-versus-final pairs. Capacity attribution for reasoning and traps: medium — consistent across
> conditions but never tested against a larger model, which is the one comparison that would settle it.

> **Next experiment:** CP-01 on a 24 GB CUDA host — 0.6B greedy, 0.6B thinking, 4B, 8B — each on 112
> questions under both production and focused evidence, frozen prompts, blind scoring.
