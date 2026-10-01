# Stage 8: Generation Control (the 21 CFR 830.20 runaway)

Dates: 2026-09-30 to 2026-10-01. No training, no model change, no database or benchmark change.

## Diagnosis

The question was "What does 21 CFR 830.20 address?". **Reproduced live:** the model answered correctly for four
sentences, then repeated "The UDI must be presented in two forms on the device label and device packages …" with
citation numbers [5], [6] … [13], for 1,216 tokens (173 s). Validation then withheld the whole answer.

**The root cause was not duplicate retrieval.** The prompt held 8 distinct passages with 0 duplicate texts. It
was a combination:

| Layer | Finding | Fixed? |
|---|---|---|
| **Context assembly** | An off-target guidance chunk (about 21 CFR 801.40) was in the prompt, and the looped sentence came from it. The Stage 6 safeguard treated §830.20's lead-in ("A unique device identifier (UDI) must:") as an incomplete fragment, although (a)–(c) were all present as exact evidence. | yes: a fragment whose chain (its lead-in, or its own subparagraphs) is present counts as complete |
| **Prompt construction** | The question verb became the topic ("focus: address"). | yes: question verbs (address, govern, concern, establish, …) are not focus terms |
| **Repetition guard** | The Stage 7 stop compared sentences verbatim. Each copy carried a different citation number, so no two copies were identical and the guard never fired. **This is why it ran away.** | yes: sentences are compared with citation markers, "SOURCE n", list bullets, case and spacing removed, in the generation stop and in the validator alike |
| **Citation assembly** | The model invented markers [9]–[13] with 8 sources. | model behaviour; repair already strips invalid markers. The pipeline never creates them. |
| Chunking, reranking | not involved | — |

## Changes kept

- `inference/repetition_text.py` (torch-free): normalised sentence comparison and `drop_duplicate_sentences`.
  `inference/repetition.py` stops generation at the 3rd copy of a sentence, using exactly the validator's test.
  The test is monotonic, so it never stops text that would have passed.
- **Loops:** the answer is rejected as degenerate, and the existing repair applies: the requested provision
  verbatim where quoting is allowed, otherwise withheld. The raw output is kept.
- **Non-looping answers:** an identical sentence said twice is said once (UI-01: two list items that appeared
  twice).
- **Context:** `selection.completed_by_protected_children` (lead-in chain rule).
- **Prompt:** `planning/shape.py` question verbs.
- **Evidence consolidation** (`selection.consolidate_evidence`, `RagConfig.evidence_consolidation="on"`;
  fingerprint version 6):
  - content-free "[Reserved]" rows are dropped, unless the reserved row *is* the requested provision;
  - identical text is merged only when it is the same provision, or a non-CFR guidance chunk;
  - near-duplicate merging is for guidance chunks only;
  - different provisions are never merged (§830.20(a) and (b); 117.180(d) and 507.53(d); 111.155(a) and
    111.160(a)).

  Measured on 379 questions: 94 [Reserved] rows removed in 33 questions, 0 merges. This corpus has no duplicated
  passages; it has identical wording in distinct provisions, which correctly stays.

## Changes measured and REVERTED

| Change | Evidence | Decision |
|---|---|---|
| System-prompt rule "state each requirement once; cite supporting sources together; stop when answered" | Full live run (`stage8_generation_control_20261001T040254Z`, identical evidence): degenerate outputs 4 → 1 and major citation failures 8 → 4, **but 3 protected PASS questions failed** (S5-062, S5-070, S5-084) and AS-03 too | reverted. The 0.6B model trades one property for another (as in Stage 6). |
| Show the text before a loop ("retain the valid prefix") | S5-061 and BM-S-001 then showed meaningless prefixes ("A unique device identifier is required to contain."); lexical validation passed them | reverted. For this model the prefix of a loop is not a reliable answer. |
| Remove near-duplicate (not identical) sentences | A real restatement scored 0.84 overlap; two *distinct* requirements worded alike scored 0.83 | not adopted: no threshold separates them |

## Targeted evaluation: the 12 questions (`artifacts/generation_control/targeted_final2_20261001T045400Z`)

Abbreviations:
- **Dup:** duplicate evidence items in the prompt.
- **Rep raw/final:** highest number of copies of one sentence, in the raw output / in the shown answer.
- **Review:** developer review, not SME review.
- **Only-own:** the answer cites only the requested provision's own text (cross-references the regulation itself
  contains, such as "part 803", are not counted as off-target).

| # | Question | Retrieval | Dup | Rep raw/final | Length | Time | Review: correctness / exact section |
|---|---|---|---:|---|---:|---:|---|
| 1 | Part 11 cover | complete | 0 | 1/1 | 2,735 ch | 55 s | correct; long; one near-identical restatement remains (style) |
| 2 | 11.10 | complete | 0 | 1/1 | 1,681 ch | 32 s | correct summary; drops "when appropriate" (qualifier warning) |
| 3 | 11.100 e-signatures | complete | 0 | 2/**1** | 548 ch | 11 s | duplicate removed; (b) missing (incomplete) |
| 4 | open vs closed systems | complete | 0 | 2/**1** | 1,044 ch | 25 s | **wrong definitions**: 11.3(b) definitions not retrieved for a part-level question (retrieval gap) |
| 5 | 11.10(c) | complete | 0 | 1/1 | 140 ch | 3 s | correct; exactly (c) |
| 6 | 314.90 address | complete | 0 | 1/1 | 587 ch | 17 s | content right; restates (b) as request contents (misreading) |
| 7 | 314.90 waiver contents | complete | 0 | 1/1 | 284 ch | 9 s | correct |
| 8 | 820.10 | complete | 0 | 1/1 | 1,719 ch | 49 s | mostly correct; one garbled sentence mixing (c)(1)/(c)(2) |
| 9 | 820.10(b)(3) | complete | 0 | 1/1 | 150 ch | 4 s | correct; exactly (b)(3) |
| 10 | **830.20 address** | complete | 0 | 1/1 | 462 ch | **13 s** (was 173 s) | **correct**: (a), (b)(1)–(3), (c); no repetition |
| 11 | 314.999 | not found | 0 | – | 183 ch | 0.1 s | correctly declined; nothing fabricated |
| 12 | Part 1400 AI labeling | not found | 0 | – | 185 ch | 0.0 s | correctly declined; nothing fabricated |

No answer repeats a requirement. No runaway; 830.20 takes 13 s instead of 173 s. Evidence uniqueness 12/12.

## Full diagnostic set (79), Stage 7 vs Stage 8

| | Stage 7 | Stage 8 |
|---|---:|---:|
| PASS | 49 | 49 |
| FAIL | 12 | 12 |
| NEEDS_REVIEW | 2 | 2 |
| UNVERIFIED | 13 | 13 |
| UNVERIFIED_WITH_FAILURES | 3 | 3 |

- **Protected Stage 4 PASS set:** 38/39; S5-101 has been FAIL since the Stage 6 review correction. No new
  regression.
- **Changed answers:** 2. UI-01 had a duplicated list item said once; BM-NC-003, whose [Reserved] rows were
  removed, is still withheld.
- **Final answers with a sentence repeated three or more times:** 0.
- **Determinism:** 10/10.
- **Result:** `artifacts/diagnostics/stage8_result_final_20261001T045933Z`. 78 questions are offline replays of
  the Stage 7 run (identical prompts); BM-NC-003 is live. See PROVENANCE.md.

## Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | No answer repeats identical requirements | **met**: 0 in 79 + 12; one near-identical *restatement* remains (Part 11, style) |
| 2 | No runaway generation | **met**: the stop now fires on loops with changing citation numbers; loops are rejected |
| 3 | Duplicate evidence consolidated before generation | **met**: [Reserved] rows removed; no duplicated passages exist in this corpus |
| 4 | Exact subsection questions answer that subsection | **met** for 11.10(c) and 820.10(b)(3) |
| 5 | Citations point to supporting evidence | met for 830.20, 11.10(c), 820.10(b)(3); invented markers are stripped |
| 6 | Invalid references produce no fabricated requirements | **met**: 314.999 and Part 1400 declined in < 0.2 s |
| 7 | Concise answers | met for single-provision questions (140–462 characters); part- and section-level answers remain long (1.7–2.7k characters) |
| 8 | Benchmark intact | **met**: unchanged; integrity hashes in Stage 7 |
| 9 | Existing tests pass | **met**: 1,243 passed, 1 skipped; the same 3 slow-tier failures that predate Stage 5 |

## Is training needed?

**Not for the runaway.** It was a pipeline defect (the guard, context and prompt construction) and is fixed
without training.

What remains in the 12 answers is the Stage 6 capability pattern:
- an incomplete enumeration (#3);
- a misread paragraph (#6);
- a garbled sentence (#8);
- a dropped qualifier (#2);

plus one retrieval gap (#4). Training the 0.6B model was already tried three times and regressed. The measured
next step is unchanged from Stage 7: the model ladder (4B/8B) on frozen evidence, then decide on fine-tuning for
the chosen model. **No overnight training was started.**
