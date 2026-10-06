# Stage A — the mechanical validators cannot carry a correctness verdict

Stage A deliverable 3. Reproduce with `python3 scripts/stage_a_proxy_check.py`; figures from
`artifacts/stage_a/proxy_check.json`, row detail in `artifacts/stage_a/proxy_rows.jsonl`.

The known example — M-003 scoring ~0.80 content recall and PASS while contradicting the governing
applicability rule — is not an outlier. Scored over all 300 acceptance rows against the frozen
rubric, it is the normal case.

---

## 1. What was measured

Two mechanical judgements, each compared against the frozen substantive rubric
(`regulus_substantive_rubric_v1`) over the 299 scored rows of run
`acceptance_rev02_20261001T083958Z` (the 1 ERROR row is excluded: no answer exists to judge).

**PROXY** — the content-recall proxy, reimplemented exactly as `scripts/d1_experiment.py` applies it
(lines 291–411): bag-of-words recall of the benchmark's Key Answer Elements after stop-word removal,
pass at ≥ 0.50, with trap rows instead passed by a refusal regex. This is the metric that produced
the pass counts in phase D1.

**GATE** — the production grounding validator's own final state, `validation_final == "valid"`:
whether the pipeline judged the text it was about to show to be supported by its evidence.

## 2. Result

| | PROXY | GATE |
|---|---|---|
| Calls PASS | 69 | 230 |
| Rubric PASS | 10 | 10 |
| **False passes** | **59** | **225** |
| False passes as a share of its own passes | **85.5%** | **97.8%** |
| False fails (rubric PASS it rejects) | 0 | 5 |
| Agreement with the rubric | 80.3% | 23.1% |

Against substantive correctness alone (N=2, ignoring citation and completeness), the proxy still
posts 55 false passes out of 69 — **79.7%** — and also rejects 4 of the 18 substantively correct
answers.

Both branches of the proxy fail, so this is not an artefact of one scoring mode:

| Proxy mode | Rows | Calls PASS | Rubric PASS | False-pass share of its passes |
|---|---|---|---|---|
| `substantive_recall` | 251 | 51 | 5 | **90.2%** |
| `trap_refusal` | 48 | 18 | 5 | **72.2%** |

Scoring the proxy on the **raw** model output rather than the delivered answer does not help: 64
passes, 55 of them substantively wrong (85.9%), while rejecting half of the substantively correct
answers.

## 3. Why the proxy fails — the mechanism

A bag-of-words recall score is computed from the words a correct answer would contain. A wrong
answer about the same subject contains almost all of those words, because the question supplies
them. The metric therefore measures *topicality*, and topicality is exactly what every answer in
this corpus has: retrieval puts the right part in front of the model, so the model writes about the
right subject and gets the rule wrong.

Worked cases, highest recall first:

- **M-027, recall 1.00, N=1.** Perfect recall. The first sentence is correct; the rest is not.
- **U-007, recall 0.88, N=1.** Right criterion, wrong consequence.
- **S-010, recall 0.80, N=0.** Never states the 111.55 requirement at all. Returns adjacent
  production-control language, which shares the key elements' vocabulary.
- **M-003** (the original example). Question and wrong answer share their content words, so recall
  is ~0.80 while the answer asserts the opposite of 820.1(a)(2). Phase D1's H4 arm confirmed the
  mechanism directly: 820.1(a)(2) was supplied verbatim — *"The provisions of this part do not apply
  to manufacturers of components or parts of finished devices"* — and the model answered that they
  **are** subject to Part 820. Recall scored it a pass in both arms.

The structural point: **recall cannot see negation, applicability or attribution.** "X applies to Y"
and "X does not apply to Y" have near-identical word bags, and applicability is what a regulatory
answer is for.

The trap branch fails differently. It passes a row when a refusal regex matches, so (a) a hedge that
never states the premise is false passes, and (b) the 11 Temporal/Version rows are mis-specified at
the metric level: those rows require a correct substantive redirect to the provision that now carries
the requirement, not a refusal, so the metric rewards the wrong behaviour on 11 of its 48 trap rows.

## 4. Why the production gate is not a correctness signal either

The gate is not broken at its own job. `validation_final == "valid"` asserts that the sentences shown
can be matched to spans in the supplied sources — it never claims the answer is responsive or right.
The failure is one of **use**: it has been read as a quality signal, and it cannot be one. 97.8% of
the answers it validates fail the rubric.

Two specific consequences, both measured:

1. **Richer evidence makes the gate more permissive, not more accurate.** More supplied text means
   more sentences find a matching span. Phase D1's H4 arm saw withholding fall from 3/3 to 1/3 while
   substantive accuracy improved on 0 of 3 rows — two wrong answers reached the user *because*
   validation passed. Any change that raises the gate's pass rate must be assumed to have lowered
   the safety net until substantive scoring says otherwise.
2. **As a citation check its sensitivity is 38%.** Of the 189 delivered answers that carry a citation
   and were hand-scored L=0, the gate's support codes fire on only 72. It misses 117, and fires on 8
   rows that scored L=1. See [STAGE_A_CITATION_GROUNDING.md](STAGE_A_CITATION_GROUNDING.md) §5.

## 5. What this invalidates

- **Every pass count in phase D1**, including Arm 0's 8 of 20. Those counts were produced by the
  proxy. The D1 *refutations* are unaffected where they rest on direct measurement — keyed presence,
  keyed rank, paragraph coverage, token budgets — because those are observations, not scores. Any D1
  statement of the form "N rows passed" is void.
- **Any comparison of runs by validated-answer rate**, which moves with evidence volume.
- **Any dashboard pass rate** fed by either metric.

## 6. What the metrics may still be used for

- **Triage.** Ranking rows by recall is a reasonable way to choose which answers a human reads first;
  it was used that way in the D2 review, and only that way.
- **Regression detection on the gate's own terms.** A sudden change in the rate of
  `low_overlap_with_cited_source` is a signal that something in retrieval or generation moved. It is
  not a quality verdict.
- **The withholding decision.** The gate's purpose is suppressing ungrounded text, and on this run
  it suppressed 46 answers, of which the D2 review found none that should have been shown. Keep it.

## 7. Rule

No system change, model change or experiment conclusion may be justified by a span-support or
content-recall score. Comparative claims require scoring under `regulus_substantive_rubric_v1`, and
hand scoring is the only implementation of that rubric that currently exists — which makes a
blind-scoring harness a prerequisite for the next comparative experiment, not an optimisation.
