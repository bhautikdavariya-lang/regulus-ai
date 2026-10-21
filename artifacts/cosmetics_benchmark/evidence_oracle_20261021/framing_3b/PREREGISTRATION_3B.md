# Step 3B framing experiment: pre-registration (written before any Step 3B inference)

## Conditions (same 8 general questions; same model, packets and harness)
- **A (original framing):** the restored evidence-oracle outputs (../run/answers.jsonl), verified byte-identical to
  Step 3. All 8 are declines, and their raw output equals their delivered output.
- **B (specific-provision framing):** the same harness, ../recovered_step3/oracle_run.py (sha256 c9bfee3e…), and
  byte-identical packets (packets/packets.json, 1cc6d2a8…). Only the question text changes.

## Wording (paired_wording.json, sha256 c46d609e…)
- One rule for all 8: name every section the verified key cites (criteria.json `cite`), in key order, before the
  original question, which is left verbatim:
  - `Explain how 21 CFR <s1> applies: <question>`
  - `Explain how 21 CFR <s1> and 21 CFR <s2> apply: <question>` (COS-74.2317-Q1 only, whose key cites 74.2317 and 70.3).
- **No answer content, no new facts:** the named citations are those already carried by the packet rows.
- **No pressure to answer:** nothing tells the model to ignore uncertainty or to avoid abstaining.
- **Two corrections made before any inference, each found by the checks below:**
  - the word "question" was removed from the template, because it leaked into the planner's focus terms;
  - "primary section only" was replaced by "every section the key cites", because naming only 74.2317 made selection
    drop the packet's 70.3(v) row.

## Verified before inference (preview.json, sha256 c1c389a8…; no model loaded)
- The original-framing prompt rendered by the harness logic equals the prompt recorded in Step 3, byte for byte (8/8).
- The system prompt is identical (8/8).
- The evidence is identical: the same citations and texts (8/8).
- Each framed question plans as exactly the named provision(s), with no template word in the focus terms.
- **Other differences:** none, apart from what this pipeline renders automatically for a requested provision:
  - the QUESTION line;
  - the REQUESTED PROVISIONS lines (r1/r2);
  - the evidence tier label (SUPPORTING → EXACT);
  - the answer-plan lines (shape, focus, conditions to keep, sub-requirements);
  - the ANSWER FORMAT line (general synthesis line → provision-focused line);
  - the token ceiling: 384 → 416, 576 (×5), 736, 896, 1,696.
- **Protocol deviation (disclosed):** the earlier report expected the prompts to differ only in the provisions block and
  the tier lines. The plan, format line and token ceiling also change, because they are how this pipeline frames a
  provision request. No variant isolates them, as the brief allows none. Decoding is unchanged (greedy, thinking off).

## Scoring (fixed now)
- **Primary object:** the model's own raw output, before any validator repair or fallback. The decision is about the
  model's decline behaviour, and provision-mode repairs can append verbatim provision text, as with COS-70.50-Q2 in the
  evidence-oracle report. The delivered answer is recorded and reported separately.
  - For A, raw = delivered for all 8.
- **Rubric and checklist:** the same rubric (Step 6 SCORER_INSTRUCTIONS.md, unchanged) and checklist
  (criteria.json 66354f8a…).
- **Blindness:** scored blind by 2 scorers, then 2 adversarial verifiers. Disagreements are recorded and adjudicated
  before un-blinding.
- **"Answers":** the raw output is not a decline (the rule-9 sentence or an equivalent refusal) and gives substantive
  content.
- **Decision thresholds (unchanged):**
  - FRAME-TRIGGERED: at least 5/8 answer AND at least 3/8 reach PASS or PARTIALLY PASS AND 0 fabrications;
  - CAPABILITY-LIMIT INDICATION: at most 1/8 answer;
  - INCONCLUSIVE: anything else, or anything that cannot be evaluated fairly.
