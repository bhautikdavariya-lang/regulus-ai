# ASSISTED REVIEW — NOT VERIFIED — second pass

The first pass left these rows at NEEDS_RESEARCH or CORRECTED, usually because the
answer appeared to sit in a section the key does not cite, and only that section's
heading was in the evidence. The full eCFR text of those sections has now been
retrieved read-only from the same 2026-09-03 snapshot and is in
`supplemental_sections` for each row.

For each row, re-decide it under `tools/REVIEW_RUBRIC.md` (all its rules still
apply), using `original_evidence` **and** `supplemental_sections`. Start from
`first_pass_proposal` and change only what the new text actually settles.

* If the supplemental text shows where a J element lives and the citation should
  add or swap that section, propose `CORRECTED` with the full corrected citation.
* If the supplemental text shows the element is in the cited text after all, or is
  a harmless cross-reference the citation already reaches, the row may become
  `ACCEPTED`.
* If the supplemental text **contradicts** a J element, record `CONTRADICTED`,
  quote it, and set `evidence_conflict: true`. The SME system can correct only
  the citation or ISO clause, not column J. So a wrong J element leaves the row at
  `NEEDS_RESEARCH` (or `REJECTED` if the row cannot be salvaged), with a
  `key_elements_issue` note that says exactly what J gets wrong.
* If the supplemental text does not settle it (for example it is statute or
  guidance, which is not held), keep `NEEDS_RESEARCH` and keep the items specific.

Quotes: copy verbatim, 200 characters at most, from `original_evidence` or
`supplemental_sections` of the same row. Quotes are machine-checked.

Output one JSON array with one object per row, in file order, in the rubric
schema plus two fields:

```json
"key_elements_issue": "empty, or what column J states that the regulation text does not support",
"pass2_change": "what changed from the first pass and which supplemental section settled it, or 'no change' and why"
```
