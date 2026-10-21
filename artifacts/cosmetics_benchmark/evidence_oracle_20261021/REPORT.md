# Evidence-oracle experiment: decision report (Qwen3-1.7B MLX 4-bit, 2026-10-21)

**Decision: Result B, generation errors persist.**
- With verified, sufficient evidence, 0 of 9 failing questions improved, and the model still declined every general
  question.
- Next priority: answer generation, not retrieval/context selection or citation/validation.

## 1. Objective and sample
**Objective:** separate retrieval and selection failures from answer-generation failures by giving the same model, for
the same question, verified evidence in place of retrieved evidence.

**Sample (12):** COS-710.5-Q1, 70.50-Q2, 70.3-Q3, 700.18-Q1, 82.101-Q1, 82.1321-Q1, 740.12-Q1, 720.4-Q3, 80.10-Q1,
73.2725-Q1, 74.2317-Q1 and 700.15-Q1. The reasons for each are in PREREGISTRATION.md (sha256 8fde7a21…, fixed 07:32:54Z,
before any inference):
- 3 controls;
- 6 wrong despite some evidence;
- 3 with missing or ranked-out evidence, 3 with ranking or selection problems;
- 3 needing careful interpretation;
- 1 from Part 73.

**Reuse:**
- Condition B is the Step 3 run of 04:58Z. Its files were recovered from the session transcript; the pre-registered
  checklist is byte-identical to its recorded hash 66354f8a….
- B was re-run once as a restoration. All 12 raw outputs, the delivered texts and the token counts are identical to
  Step 3's (restoration_check.json).
- Condition A was not re-run.

## 2. Model and runtime
- **Model:** Qwen/Qwen3-1.7B, MLX 4-bit g128, revision 21457c6f51ed54a7c16e988c0844db973815c137, on mlx 0.32.3 /
  mlx-lm 0.32.0. Greedy decoding, thinking off.
- **Verification:** asserted in run/run_meta.json before the first question. Condition A's responses name the same model.
- **Application path:** Condition A ran the production app (serve_ui /api/ask, Step 6 arm A). Condition B ran the same
  RagPipeline, generator, prompt template, validator and repair, with a retriever that returns only the packet.
- **Other differences:**
  - B raises the context limits to the hard ceilings (24 sources, 4,000 and 9,000 chars) to deliver whole packets.
  - The tokenizer files are byte-identical in both conditions.
  - The literal-OR switch was never set.

## 3. Evidence packets
- **Source:** 67 rows from the live, read-only eCFR database (snapshot 2026-09-03), with each row's sha256 in
  packets/packets.json.
- **Checks:**
  - every row matches Step 3's packet text, and the row and character counts are identical;
  - each row matches the corpus snapshot or the 20 Oct prompt text wherever either holds it.
- **Nothing was repaired.** Two stored rows are truncated, and their missing elements are excluded from scoring:
  - 740.12(b) has no caution wording;
  - 73.2725(b) has no specification limits.
- **Delivery:** the pipeline delivered the whole packet in 11 of 12 questions. For COS-82.1321-Q1 it left out 82.1050 as
  optional, because the exact-citation evidence was complete; that row is a non-core element.

## 4. Question-level comparison (same model; A = pipeline evidence, B = verified packet)
| Question | A | B | Same evidence / same answer | Notes |
|---|---|---|---|---|
| COS-710.5-Q1 | PARTIALLY PASS | PARTIALLY PASS | yes / yes | Omits the cancellation element (R3) |
| COS-70.50-Q2 | PASS | PASS | yes / yes | The PASS comes from the validator's repair appending 70.50(a)–(c) verbatim; the model's own text only paraphrased what each paragraph covers |
| COS-82.1321-Q1 | PARTIALLY FAIL | PARTIALLY FAIL | yes / yes | Restates 82.1321; never says it sets no use restriction (R2) |
| COS-70.3-Q3 | PARTIALLY FAIL (Step 6: PASS) | FAIL | no / no | The model declined in both conditions; A's text is the pipeline's "definitions quoted" fallback |
| COS-700.18-Q1 | FAIL | FAIL | no / yes | Identical decline; 700.18(b) residue exemption in both |
| COS-82.101-Q1 | PARTIALLY FAIL | PARTIALLY FAIL | no / no | B adds the subpart B limits (comp 0 → 1) but lists them beside the C/D limits without saying which apply |
| COS-740.12-Q1 | FAIL | FAIL | no / yes | Identical decline; A's evidence lacked 740.12(b) (decline defensible), B's did not |
| COS-720.4-Q3 | FAIL | FAIL | no / yes | Identical decline with 24 packet rows |
| COS-80.10-Q1 | FAIL | FAIL | no / yes | Identical decline; the fees and payment method were in the packet |
| COS-73.2725-Q1 | FAIL | FAIL | no / yes | Identical decline: A's evidence was all 1271.90, B's the 73.2725 rows |
| COS-74.2317-Q1 | FAIL | FAIL | no / yes | Identical decline |
| COS-700.15-Q1 | FAIL | FAIL | no / yes | Identical decline; 700.15(b) (any level is adulterated) in the packet |

**Classes:**
- generation failure persists: 10;
- acceptable in both: 2 (710.5, 70.50-Q2);
- evidence-sensitive improvement: 0;
- citation/validation problem: 0;
- inconclusive: 0.

**Pre-registered rules:**
- improved: 0 of 9;
- persisting with a sufficient packet: 9;
- control drops: 1 (COS-70.3-Q3, a pipeline-fallback artefact, not a change in the model's behaviour).

## 5. Aggregate by dimension (A / B)
| Dimension | A | B |
|---|---|---|
| Categories PASS / PP / PF / FAIL | 1 / 1 / 3 / 7 | 1 / 1 / 2 / 8 |
| Regulatory correctness, sub 2 / 1 / 0 | 2 / 3 / 7 | 2 / 2 / 8 |
| Completeness, comp 2 / 1 / 0 | 2 / 2 / 8 | 1 / 3 / 8 |
| Citation exact (ce = 1); citations supported | 5; 5 of 5 | 4; 4 of 4 |
| Conditions and exceptions kept (yes / partly / no) | 3 / 1 / 1 | 2 / 2 / 0 |
| Fabrications | 0 | 0 |
| Declines; appropriate given that evidence | 7; 4 yes, 3 no | 8; **0 yes, 8 no** |
| Mean input / output tokens | 1,413 / 64 | 1,177 / 86 |
| Mean wall time (not directly comparable) | 3.99 s (HTTP round trip via serve_ui, incl. live evaluator) | 3.12 s (pipeline.answer) |

**Abstention:**
- In A, 4 of the 7 declines were defensible: the retrieved evidence did not support an answer.
- In B, all 8 declines came with a packet that supported an answer.
- In 7 of the 9 pairs with different evidence, the model's decline sentence was byte-identical across conditions.

The decline does not depend on the evidence.

## 6. Examples
- **Persistent failure (decline despite sufficient evidence): COS-700.15-Q1.** The packet holds 700.15(b): a cosmetic
  containing a halogenated salicylanilide "at any level" is adulterated. The question asks whether 0.25% tribromsalan is
  permissible. Both conditions: "The available regulatory sources do not provide enough information to answer this."
- **Persistent failure (restates, does not answer): COS-82.1321-Q1.** Both conditions quote 82.1321's conformity to
  74.1321(a)(1) and (b), citing [1] correctly, but never state the answer, which is that 82.1321 places no restriction on
  lipstick use.
- **Partial gain without a category change: COS-82.101-Q1.** With the verified packet the answer gives the subpart B
  limits from 82.5 (lead 0.001%, arsenic 0.00014%). It also lists the subpart C/D limits, never says FD&C Blue No. 1 is
  subpart B, and omits 82.50.
- **No answer was corrected by verified evidence.**

## 7. Limitations and uncertainty
- **Small sample:** 12 questions is diagnostic, not proof. It is not extrapolated to the 100.
- **Uninformative pairs:** 3 of 12 had identical evidence in both conditions (exact-citation questions), so they say
  nothing about evidence sensitivity. The informative contrast rests on 9.
- **Scoring:**
  - The scoring is AI-assisted (4 blind scorers, 2 adversarial verifiers) against a pre-registered checklist. It is not
    expert-validated.
  - Of 24 items, 1 was disputed; I adjudicated it blind, and it affected only checklist entries (scoring/adjudication.json).
  - Condition A's joint scores agree with Step 6's independent blind verdicts on 11 of 12. COS-70.3-Q3 was PASS in Step 6
    and PARTIALLY FAIL here, for verbatim definitions that are never applied to the question.
- **Not fully blind:** each scorer saw the evidence its answer was given, so a careful scorer could infer which item had
  the packet.
- **COS-70.50-Q2's PASS** depends on the pipeline's deterministic repair, not on model-written content.

## 8. Recommended next engineering action (one)
**A single-factor diagnosis of the general-question decline. Diagnosis only; no production change.**
- **The pattern it tests:**
  - in this sample, 1.7B answered every question presented with a requested provision and EXACT-tier evidence (4 of 4);
  - it declined every general question ("REQUESTED PROVISIONS: none", SUPPORTING-tier evidence; 8 of 8), even with the
    verified packet.
- **The test:** in an offline harness only, render the same 8 general questions with the same verified packets, model and
  decoding, changing one thing — the packet's key section is presented as a requested provision with EXACT-tier evidence.
- **What it settles:** whether the decline is triggered by the general-question frame, or is a capability limit of the
  model.
- **Why this test:** earlier changes to parts of the frame (format line, tier wording, rule-9 wording) did not reduce
  declines. The complete frame swap has not been tested.

## 9. Acceptance criteria for that action (fixed before running it)
- **Validity:**
  - the model identity is verified;
  - the packets are byte-identical to packets/packets.json;
  - decoding is unchanged;
  - the prompt differs only in the REQUESTED PROVISIONS block and the tier/role lines;
  - one run, no retries, no changes after seeing outputs;
  - same rubric, checklist and blind scoring.
- **Frame-triggered** (a plan-level design becomes a candidate, for separate approval): at least 5 of the 8 give a
  non-decline answer, AND at least 3 of the 8 reach PASS or PARTIALLY PASS, with 0 fabrications and 0 critical errors.
- **Capability limit** (stop prompt and frame work on 1.7B; the next decision is a model-selection question for the
  owner): at most 1 of the 8 gives a non-decline answer.
- **Inconclusive:** anything between. No further variants.

## 10. Files, Git status, failures
- **Files:** written only under this folder:
  - recovered_step3/, packets/, run/, condition_b.jsonl, restoration_check.json;
  - scoring/ (packets, workflow_result.json, adjudication.json, blind_map.json, results.json);
  - tools/, PREREGISTRATION.md, REPORT.md.
- **Git:** no project file changed. HEAD 6f94938, nothing staged, 4 unpushed commits, tracked diff 3a246702… (unchanged
  from the start of this task; it includes the literal-OR code from the earlier task, switch off).
- **Failures:** none. 12/12 questions ran, 0 errors and 0 timeouts. Database read-only, write counters unchanged.
- **Memory:** before the run, the worker's 2,000 MB preflight would have failed (1,686 MB free). The run started only
  after the user closed applications (2,102 MB free).
- **Not done:** nothing committed or pushed. No production code, prompt, retrieval, validation or configuration change.
