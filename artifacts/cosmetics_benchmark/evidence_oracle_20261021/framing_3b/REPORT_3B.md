# Step 3B: question-framing experiment, report (Qwen3-1.7B MLX 4-bit, 2026-10-21)

**Conclusion: INCONCLUSIVE.**
- The specific-provision framing changed the model's behaviour sharply but met the frame-triggered threshold on only two
  of its three parts: answers 4 of 8 against at least 5; PASS/PARTIALLY PASS 4 of 8 against at least 3; 0 fabrications.
- It is clearly not a capability-limit indication (at most 1 of 8 answers).

## 1. Paired wording (paired_wording.json)
**Rule, applied to all 8:** name every section the verified key cites, then give the original question verbatim.

| Question | Original (A) | Framed (B) |
|---|---|---|
| COS-700.18-Q1 | We use chloroform as an extraction solvent for a botanical extract, and traces remain in our cream. Is the cream adulterated under the chloroform rule? | Explain how 21 CFR 700.18 applies: *(original)* |
| COS-740.12-Q1 | We're launching an all-over body deodorant spray marketed to women for 'everywhere freshness.' Does it need a special caution? | Explain how 21 CFR 740.12 applies: *(original)* |
| COS-720.4-Q3 | We sell one permanent hair dye in 12 shades and one lipstick in 8 shades where only the color additive amounts differ. How many Form 2512 statements, and how should ingredients be listed? | Explain how 21 CFR 720.4 applies: *(original)* |
| COS-70.3-Q3 | We make a brow tint, a lip gloss and a coal-tar-based permanent hair dye. How do FDA's color additive definitions treat 'area of the eye', 'externally applied' and the hair dye exemption? | Explain how 21 CFR 70.3 applies: *(original)* |
| COS-80.10-Q1 | We're submitting a 2,000-pound batch of a straight color for certification. What fee do we pay, and how must we pay it? | Explain how 21 CFR 80.10 applies: *(original)* |
| COS-73.2725-Q1 | We're developing a blue eye shadow and want to use ultramarine blue as the colorant. May we, and what restrictions, certification or labeling apply? | Explain how 21 CFR 73.2725 applies: *(original)* |
| COS-74.2317-Q1 | We're a 12-person contract filler formulating a tinted body butter. Our supplier offers D&C Red No. 17. Can we use it, is there a use limit, and does the color need FDA certification? | Explain how 21 CFR 74.2317 and 21 CFR 70.3 apply: *(original)* |
| COS-700.15-Q1 | Our antimicrobial deodorant bar formula includes tribromsalan (TBS) at 0.25%. Can we sell it? | Explain how 21 CFR 700.15 applies: *(original)* |

**Checked before inference (preview.json, no model):**
- The original-framing prompts reproduce Step 3's recorded prompts byte for byte (8/8).
- The system prompt and the evidence (citations and texts) are identical across framings (8/8).
- The framed prompts actually sent equal the preview (8/8).

## 2. Model and runtime
- **Model:** Qwen/Qwen3-1.7B, MLX 4-bit g128, revision 21457c6f51ed54a7c16e988c0844db973815c137. Asserted in
  run/run_meta.json before the first question.
- **Runtime:** mlx 0.32.3, mlx-lm 0.32.0; greedy decoding, thinking off.
- **Harness and packets:** the recovered harness (oracle_run.py c9bfee3e…) and byte-identical packets (1cc6d2a8…).
- **Run:** one run of 8 questions, 0 errors or timeouts. Database read-only, write counters unchanged. The literal-OR
  switch was not set.

## 3. Paired results (primary: the model's own raw output; A = the restored original-framing outputs)
| Question | A | B raw | B declines core? | Citations (B) | Fabrications | Required elements in B (R1 = application to the user) |
|---|---|---|---|---|---|---|
| COS-700.18-Q1 | FAIL (decline) | PARTIALLY FAIL | yes, after stating both rules | ce 0 (rule attributed to (a), it is in (b)) | 0 | R1 ✓ R2 ✓ R3 ✗ |
| COS-740.12-Q1 | FAIL (decline) | **PASS** | no | correct, supported | 0 | R1 ✗ R2 ✗ R3 ✓ (quoted, not applied) |
| COS-720.4-Q3 | FAIL (decline) | PARTIALLY FAIL | yes | ce 0 ((d)(1)–(3) mis-numbered) | 0 | R1 ✗ R2 ✗ R3 ✓ R4 ✓ |
| COS-70.3-Q3 | FAIL (decline) | **PASS** | no | correct, supported | 0 | R1 ✗ R2 ✗ R3 ✓ |
| COS-80.10-Q1 | FAIL (decline) | **PARTIALLY PASS** | no | correct; one marker partly supported | 0 | R1 ✗ ($900 not computed) R2 ✓ R3 ✗ |
| COS-73.2725-Q1 | FAIL (decline) | PARTIALLY FAIL | yes, after stating (a)–(e) | correct inline | 0 | R1 ✗ R2 ✓ R3 ✓ |
| COS-74.2317-Q1 | FAIL (decline) | **PASS** | no | correct, supported | 0 | R1 ✗ R2 ✗ R3 ✓ R4 ✓ |
| COS-700.15-Q1 | FAIL (decline) | PARTIALLY FAIL | yes, after stating (a)–(c) | correct inline | 0 | R1 ✗ R2 ✓ |

- **Delivered answers:** the validator appended verbatim provision text for 4 questions (700.18, 720.4, 73.2725,
  700.15). Each stays PARTIALLY FAIL and still declines the core question.
- **Abstention:** all 8 declines in A, and the 4 core-question declines in B, were inappropriate. The evidence supported
  an answer every time.
- **Tokens and time (A → B):**
  - mean output tokens 23.8 → 241.2;
  - mean input tokens 1,194 → 1,223;
  - mean wall time 2.20 s → 5.49 s.

## 4. Against the pre-registered thresholds
| Threshold | Required | Observed |
|---|---|---|
| FRAME-TRIGGERED: answers | ≥ 5 of 8 | **4 of 8** (not met) |
| FRAME-TRIGGERED: PASS or PARTIALLY PASS | ≥ 3 of 8 | 4 of 8 (met) |
| FRAME-TRIGGERED: fabrications | 0 | 0 (met) |
| CAPABILITY-LIMIT: answers | ≤ 1 of 8 | 4 of 8 (not met) |

**Observed but outside the thresholds:**
- Contentless declines: 8/8 → 0/8.
- The other 4 gave correct provision content and then declined the core question.
- The model applied the rules to the user's facts (checklist R1) in only 1 of 8. The 3 rubric PASSes are accurate,
  cited restatements that leave the application implicit.

## 5. Disagreements and deviations
- **Scoring:** 2 blind scorers and 2 adversarial verifiers. There were 5 disagreements on 4 items, all adjudicated blind
  before un-blinding (scoring/adjudication.json):
  - one checklist entry;
  - one conditions rating;
  - one citation-support rating;
  - one completeness score (comp 1 → 2).
  None changed a category. Not expert-validated.
- **Wording, corrected before inference:** the template lost the word "question" (it leaked into the planner's focus
  terms), and the rule changed from "primary section" to "every key section" (naming only 74.2317 dropped the packet's
  70.3(v) row).
- **Frame components (disclosed):** besides the question wording, provision tier and requested-provision lines, the
  pipeline's provision mode also changes the answer-plan lines, the ANSWER FORMAT line and the token ceiling
  (384 → 416–1,696; no output hit it). The earlier report expected only the provision and tier lines to differ. No
  variant isolates these components, as the brief allows none.
- **Corrected interim statement:** during the run I said 6 of 8 outputs contained no decline, based on a string match on
  the exact rule-9 sentence. On reading, 4 of 8 decline the core question in other words. The scores above use the full
  reading.

## 6. Conclusion
**INCONCLUSIVE.** The specific-provision frame removes the contentless decline and gets accurate, cited provision
content in 8 of 8, with no fabrications. But the model declines or leaves unanswered the user's actual question in most
cases. Half end with a decline even after the content.

## 7. Next action (limited to what this result justifies)
**No further framing or prompt variants.** This was fixed in advance for an inconclusive result.

The evidence is now enough for an owner decision that is not another experiment. With this framing, Qwen3-1.7B MLX 4-bit:
- reliably restates the correct provisions with correct citations;
- applies them to the user's situation in 1 of 8.

The decision is whether a "cited provision restatement" answer mode is acceptable for the product, or whether answering
applied questions requires a model-selection review outside the current 1.7B-only constraint.
