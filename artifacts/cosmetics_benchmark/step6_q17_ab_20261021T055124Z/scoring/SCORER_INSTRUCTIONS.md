# Scoring instructions (fixed before scoring; identical for every batch)

You score answers of a regulatory question-answering system about U.S. FDA cosmetics regulations against a
VERIFIED answer key. Read ONLY this file and your assigned packet file. Do not open any other file in this
directory tree (in particular never `blind_map.json`, `arm_*` folders, `responses/` or `results.jsonl`): the
scoring must be blind to which system produced which answer.

## What an item is
Each question block shows the question, the verified key (expected citation + key answer elements, plus any audit
note), and one or two ITEMS. An item id ends in `#1` (one answer) or `#X` / `#Y` (two different answers to the same
question; their order is random and the letters mean nothing). Score every item on its own merits against the key.
Never compare X with Y to decide a score, and never guess where an item came from.

For each item you see: how it was delivered (GENERATED, WITHHELD by the validator, or a FALLBACK text), the
answer text the user saw, what each [n] marker points to, and which of the key's sections were in the evidence
the system had.

## Rubric (the main Regulus benchmark's Scoring Rubric, applied as written)
- **ce — Citation accuracy (1/0).** 1: every regulatory citation in the response is correct to the section, and to
  the paragraph where the response asserts a paragraph-level requirement. 0: any citation is to the wrong section
  or paragraph, OR the response gives a correct explanation with no citation at all. Use MARKERS to see what each
  [n] points to. A response with no substantive content scores 0.
- **fab — Fabricated (1/0; 1 is bad).** 1 when the response (i) cites a CFR section, guidance, docket or statute
  provision that does not exist, or (ii) asserts that the user's product or situation is subject to a binding
  requirement or restriction that no applicable law imposes - an invented requirement, including one imported from
  an unrelated regulatory program and stated as applying to the user (bank Instructions rule 3: "Where the
  regulation is silent ... the key says so. Any invented requirement scores Fabricated = 1"). A garbled
  restatement of a real applicable provision, or a recommendation upgraded to "must", is scored under Substantive,
  not as fabrication. Withheld answers and declines score 0.
- **sub — Substantive correctness (0/1/2).** 2: the substance is correct and would survive review by a qualified
  regulatory professional; no misstatement of a requirement. 1: directionally right but incomplete in a way that
  could mislead, oversimplifies a conditional requirement, or states a recommendation as a requirement. 0:
  substantively wrong, states a requirement that does not exist, or would lead a user to a non-compliant action.
- **comp — Completeness (0/1/2).** 2: all governing sections/elements in the key are surfaced. 1: the primary section
  is surfaced but related governing sections named in the key are missing. 0: a material governing requirement
  is omitted such that a user acting on the answer would be out of compliance.
- **scope — Scope discipline (1/0).** 1: stayed within Title 21 or flagged when outside it; no legal advice, no
  guaranteed outcome. 0: gave a legal opinion, guaranteed a regulatory outcome, or answered a non-Title-21 question
  as though it were FDA law.

## Conventions (the same as the 20 Oct scoring of this question set)
- No substantive answer delivered (a withholding notice, the sentence "The available regulatory sources do not
  provide enough information to answer this", or a fallback without the key's substance) on a question the key
  answers: ce 0, fab 0, sub 0, comp 0, scope 1. Say in `why` whether the key's sections were in the evidence.
- Score what the user saw. A withheld item is scored as the notice, not as the draft behind it.
- Where the key's answer is that the regulation does not impose what was asked, an answer that conveys exactly that
  (subject restated, no such requirement) can score full marks; a generic "not enough information" decline does
  not convey it unless that is the key's whole answer.
- `not_evaluable: true` only if the key or the item genuinely does not permit a fair judgment (say why). A decline,
  a withheld answer or a wrong answer is evaluable - never use this flag for them.

Calibration (three 20 Oct verdicts on this question set, with a different system):
- COS-710.5-Q1 {ce 1, fab 0, sub 2, comp 2, scope 1}: "Correct and complete for 710.5: a new Form FD-2511 'should'
  be submitted within 30 days of a change, and a new form is needed to cancel when the establishment changes its
  name; correctly cited. Keeps the provision's advisory 'should'."
- COS-70.3-Q3 {ce 1, fab 0, sub 1, comp 2, scope 1}: correct sections cited, but omits the eyebrow element of 'area
  of the eye' and drops the patch-test condition of the hair-dye exemption - an oversimplified conditional requirement.
- COS-70.19-Q2 {ce 0, fab 0, sub 0, comp 0, scope 1}: no answer delivered (withheld); the key's fees, payment method
  and relief provisions were not provided.

## Output
Write ONE JSON file at the path your task names: an object keyed by item id (every item in your packet, nothing
else), each value exactly
`{"ce": 0|1, "fab": 0|1, "sub": 0|1|2, "comp": 0|1|2, "scope": 0|1, "not_evaluable": false|true, "why": "<1-3 sentences: which key elements are present, missing or wrong, and any citation problem>"}`.
Identical answer texts must receive identical scores. Then reply with only: the file path and the number of items.
