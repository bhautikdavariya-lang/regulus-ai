# ASSISTED REVIEW — NOT VERIFIED — reviewer rubric

This rubric governs the *assisted* first pass over the Regulus acceptance
benchmark (REV02, 300 questions, workbook sha256 `c009d5f9c649…`). The output is
a set of **proposals** for a human SME. It is never an SME decision, it is never
written to the authoritative decision store, and it must never be consumed by
scoring or training.

## Sources and their weight

| Source | Weight |
|---|---|
| eCFR text in the evidence file (snapshot 2026-09-03) | Primary. The only thing you may use to support a substantive element. |
| `automated` findings | Mechanical lookups (existence, paragraph resolution). Not a legal conclusion. |
| `same_subpart_sections`, `outgoing_cross_references` | Leads for completeness only. A heading is not text. |
| Column G / J of the benchmark | **The claim under test. Never evidence that it is right.** |
| Your general knowledge | **Not evidence.** You may name it as a research lead in `needs_research_items`, never as support. |

## Per-row procedure

1. **Citation correctness.** Does G name the provision(s) that answer F? Right section; and right paragraph where F asks about a paragraph-level requirement.
2. **Provision existence.** From `cited_provisions[].state` / `paragraph_exists`.
3. **Applicability.** Does the cited provision actually address the subject and the regulated party F asks about (read its text and heading)?
4. **Substantive correctness.** Split J into its elements (split on `;` and obvious conjunctions). For each element, find text in the cited provisions that states it. Record a **verbatim quote of at most 200 characters, copied exactly from the evidence text** (quotes are machine-checked against the evidence; a quote that is not found verbatim invalidates the row).
   * `SUPPORTED` — the text states it (faithful paraphrase is fine).
   * `PARTIALLY_SUPPORTED` — the text states a narrower/broader/qualified version; say what differs.
   * `NOT_FOUND_IN_EVIDENCE` — nothing in the evidence states it. Say whether the text was truncated.
   * `CONTRADICTED` — the text says otherwise. Quote it.
5. **Completeness.** Does G name every provision needed to answer F as asked? Flag an omission **only** with concrete evidence: a J element that is found only in a provision G does not cite, or cited text that expressly routes the question to another provision. Do not flag merely because related sections exist.

## Judgments (the SME system's vocabulary)

* `substantive_judgment`: `correct` (all elements SUPPORTED) · `partially_correct` (any PARTIALLY_SUPPORTED / NOT_FOUND, none CONTRADICTED) · `incorrect` (any CONTRADICTED on a core element).
* `completeness_judgment`: `correct` · `partially_correct` (a governing provision is evidently omitted) · `incorrect` (the cited provision is not the governing one).

## Proposed decision

* `ACCEPTED` — citation correct and existent, substantive `correct`, completeness `correct`.
* `CORRECTED` — the citation is wrong or incomplete **and the evidence file itself shows what it should be** (e.g. the J elements are in a different paragraph/section that appears in the evidence). Give `proposed_corrected_citation`. The SME system can only correct the citation or ISO clause, not column J.
* `REJECTED` — the question itself is unusable as written (irreparably ambiguous, or its premise is wrong in a way no citation fix repairs). Rare; explain.
* `NEEDS_RESEARCH` — anything the evidence cannot settle: an element not found where the text is truncated or missing, an element that appears wrong but the right answer is not in the evidence, or conflicting evidence. List exactly what must be checked.

When in doubt between ACCEPTED and NEEDS_RESEARCH, choose NEEDS_RESEARCH. Certainty that the evidence does not carry is the failure this review exists to prevent.

## Confidence

* `HIGH` — every element quoted, citation plainly governing, nothing to interpret.
* `MEDIUM` — paraphrase or scope interpretation involved, or completeness arguable.
* `LOW` — the proposal rests on a reading a qualified reviewer could reasonably dispute.

## Output schema (one object per row)

```json
{
  "question_id": "S-001",
  "citation_correctness": "correct | incorrect | partially_correct | not_applicable | undetermined",
  "provision_exists": "yes | no | partial | not_applicable",
  "applicability": "applicable | not_applicable | undetermined",
  "elements": [
    {"element": "J fragment", "support": "SUPPORTED", "cite": "111.1(a)", "quote": "verbatim ≤200 chars", "note": ""}
  ],
  "substantive_judgment": "correct | partially_correct | incorrect",
  "completeness_judgment": "correct | partially_correct | incorrect",
  "completeness_note": "",
  "proposed_decision": "ACCEPTED | CORRECTED | REJECTED | NEEDS_RESEARCH",
  "proposed_corrected_citation": null,
  "rationale": "one or two sentences",
  "evidence_refs": ["eCFR 21 CFR 111.1(a) (snapshot 2026-09-03)"],
  "confidence": "HIGH | MEDIUM | LOW",
  "uncertainty": "what could make this wrong, or empty",
  "evidence_conflict": false,
  "needs_research_items": []
}
```

Never reproduce ISO 13485 text. You may name a clause by number and title only.
