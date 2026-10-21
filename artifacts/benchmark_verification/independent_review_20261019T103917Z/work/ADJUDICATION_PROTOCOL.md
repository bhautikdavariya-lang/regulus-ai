# Adjudication (re-review) protocol

You are the re-reviewer for rows whose first-pass decision proposes a correction, is not High
confidence, is unresolved, or disagrees with a blind second review. You see the first-pass result
(and the second-pass result where one exists). **Do not defer to either.** Re-read the official text
yourself, check every claimed error and omission, and decide. All rules of
`work/REVIEW_PROTOCOL.md` still apply (read it first) — sources, evidence format, verbatim quotes,
no ISO text, read-only audit. This file adds calibration rules so that all 300 rows are judged to
the same standard.

## 1. Materiality — when is an omission enough for PARTIALLY_CORRECT?

Column J is a list of *key answer elements* used by a tester to grade an answer. It is not meant to
reproduce the regulation. An omission is **material** only if at least one of these holds:

- (a) the question explicitly asks for something J does not supply — a sub-question ("and who
  makes the decision", "and how is it selected", "within what timeframe", "how long"), a number,
  a deadline, a responsible party;
- (b) G omits a section that governs an element J itself asserts, or that the question explicitly
  asks about (the completeness gate scores "all governing sections surfaced"); a section that is
  merely related, peripheral, or a further cross-reference is not enough;
- (c) J omits a condition, exception or qualifier without which one of J's own elements is
  misleading as stated (e.g., J states unconditionally what the regulation makes conditional).

**Not material:** J abbreviates the list inside a correctly cited section; J omits optional extra
detail, examples, or nice-to-have context; the question is broad ("what requirements apply") and J
names the principal requirements of the right section(s). A key with only non-material gaps is
VERIFIED_CORRECT — record the gaps as issues of type `precision` or `other` so the SME can still
see them, and leave `proposed_corrected_answer` empty or mark it optional.

## 2. Errors take precedence

Use VERIFIED_INCORRECT if any element of G, H or J is demonstrably wrong, even if the rest is
right and even if there are also omissions. "Wrong" includes:

- the citation for the question's principal topic is the wrong section/paragraph (G1 scores
  every citation to the paragraph), or a cited section/range includes sections that do not exist;
- a wrong number, period, deadline, threshold, party, or term of art;
- a requirement J attributes to the regulation that the regulation does not contain (including
  guidance, case law, preamble or another part presented as this regulation's requirement);
- stating as current a provision that was removed or changed (temporal error).

Imprecise wording that a qualified reviewer would read as the same requirement is **not** an error
(type `precision`). A citation to the right section without paragraph pinpoint is not an error.

## 3. Status taxonomy for behavioural rows

- **VERIFIED_UNANSWERABLE** is for rows whose *principal* expected answer is a decline, a premise
  correction, or an out-of-scope flag, and you verified it: negative controls; temporal traps that
  ask what a removed Part 820 section requires (premise: the section currently imposes
  requirements); false-premise rows; must-decline conduct rows; out-of-scope rows. Give
  `unanswerable_basis`. Every positive statement inside the key (routing to 820.10(a), "11.200
  addresses both", "three years", etc.) must also be verified; if one is wrong → VERIFIED_INCORRECT;
  if a material part is missing (rule 1) → PARTIALLY_CORRECT.
- Rows whose principal expected answer is a substantive Title 21 answer (including a plain "No"
  answer to a yes/no question, e.g. "Does FDA require certification?") get the ordinary statuses,
  even if they also expect a scope flag.

## 4. ISO clause rows (column H not "—")

- H clause **numbers** corroborated by FDA's own text (21 CFR 820.10/820.35/820.45/4.4 or the QMSR
  preamble) → fine. Numbers supported only by general knowledge → the row cannot be
  VERIFIED_CORRECT on that basis: use NEEDS_EXPERT_REVIEW unless an error/omission elsewhere makes it
  VERIFIED_INCORRECT or PARTIALLY_CORRECT. A clause number that FDA text shows to be wrong or
  incomplete for the question (e.g., 4.4(b)(1) names clauses H omits) is an H error/omission.
- Clause **titles** (column I) that FDA text does not confirm do not change the status, but set
  `expert_review_required: true` with reason "confirm ISO clause title(s) against controlled copy".
- "1 through 8 (entire standard)" for whole-standard questions is acceptable unless FDA text shows
  otherwise; FDA incorporating Clause 0/Introduction elements is a `precision` note.

## 5. Precision conventions already decided

- "820.X is [Reserved]" for a section inside Subparts C–O (removed; subpart reserved): `precision`,
  not status-affecting. 820.20–820.30 are inside the reserved range "§§ 820.20-820.30".
- QMSR effective date 2026-02-02 (89 FR 7496); "compliance date" for the effective date:
  `precision`. "89 FR 7523" as the regulatory-text pinpoint of the rule beginning at 89 FR 7496:
  `precision`.
- Focus-label (column C) mistakes are not part of the key; mention them in `issues` only.

## 6. Proposed corrections

- `proposed_corrected_answer`: a complete replacement for J, in the same terse key-element style,
  every element supported by an evidence quote you give. Not a regulation dump: keep it to what a
  grader needs. Empty when J needs no change.
- `proposed_sections`: the complete corrected G (all governing citations). Empty when G is right.
- Every VERIFIED_INCORRECT / PARTIALLY_CORRECT row needs evidence for the error or the omission
  **and** for the corrected statement.

## 7. Confidence

High = the decision follows directly from text you quoted, no judgment call left. Medium = the
text is clear but materiality/interpretation involved a judgment. Low = you are unsure; then set
`expert_review_required: true`.

## Output

Same JSON schema as the review protocol, plus three keys per row:

- `adjudication`: "confirmed" (first-pass status kept) | "overturned" (status changed) |
  "modified" (status kept, correction/evidence changed)
- `rereview_note`: 1-3 sentences — what you checked, what changed and why, and how you resolved
  any disagreement with the second review.
- `prior_statuses`: e.g. "pass1=PARTIALLY_CORRECT; pass2=VERIFIED_INCORRECT"

Write one JSON array to the path you are given, one object per assigned row, in the given order.
Validate it parses and contains each assigned ID exactly once.
