# Independent benchmark verification — reviewer protocol

You are verifying rows of the Regulus AI Acceptance Benchmark Rev 02 (300 questions) as a senior
FDA regulatory affairs specialist. The goal is **regulatory correctness of the answer key**, not
making any model pass. Do not assume the existing key (citation column G, ISO column H, answer
elements column J) is right. Investigate each row independently.

This is a read-only audit. Write **only** your assigned output file. Never modify anything else in
the repository. Never commit. Never reproduce ISO 13485 text (copyrighted); clause numbers and
titles only.

## Row fields you receive (verbatim from the workbook)

- `question_id`, `domain`, `focus`, `question_type`, `difficulty`, `question` (F)
- `expected_citation_draft` (G) — the key's citation, or a behavioural instruction for traps
- `iso_clause_draft` (H) — "—" = not ISO-scored; "None" = correct answer names no ISO clause;
  otherwise the expected ISO 13485:2016 clause(s)
- `iso_clause_title` (I), `key_answer_elements` (J) — what a correct answer must contain

The benchmark scores answers on: citation exact (every citation correct to section/paragraph),
fabricated citation, substantive 0-2, completeness 0-2 ("all governing sections surfaced"),
scope discipline, ISO clause concordance (rows where H is not "—").

## Sources (official text cached locally — use these first)

Cache root: `SOURCES=artifacts/benchmark_verification/independent_review_20261019T103917Z/sources`

| Path | What | Authority / date |
|---|---|---|
| `$SOURCES/ecfr_2026-10-14/part-<N>.txt` | Full official eCFR text of Title 21 parts (current; eCFR "up to date as of 2026-10-15") | eCFR (Office of the Federal Register / GPO), fetched 2026-10-19 from `https://www.ecfr.gov/api/versioner/v1/full/2026-10-14/title-21.xml?part=<N>` |
| `$SOURCES/ecfr_2026-01-31/part-820.txt`, `part-4.txt` | Part 820 (old Quality System regulation) and Part 4 as in force on 2026-01-31, i.e. pre-QMSR | eCFR point-in-time |
| `$SOURCES/ecfr_2026-02-02/`, `ecfr_2026-02-03/`, `ecfr_2026-02-04/` | Part 820 on those dates (see note on QMSR date below) | eCFR point-in-time |
| `$SOURCES/usc_title21/21usc<sec>.txt` | FD&C Act sections from the official U.S. Code (2024 edition, govinfo). Mapping: 201=321, 402=342, 403=343, 415=350d, 418=350g, 501=351, 503=353, 510=360, 513=360c, 520=360j, 575=360ddd, 604=364, 605=364a, 606=364b, 607=364c, 608=364d, 609=364e, 761=379aa-1, 801=381, 805=384a, 900=387, 904=387d, 905=387e, 906=387f, 910=387j, 911=387k | U.S. Code via govinfo.gov |
| `$SOURCES/federal_register/2024-01709.txt` | QMSR final rule, 89 FR 7496–7525, published 2024-02-02, effective 2026-02-02 (regulatory text starts ~89 FR 7522–7523; preamble discusses ISO clause mapping) | Federal Register |
| `$SOURCES/federal_register/2025-21955.txt` | QMSR technical amendments, 90 FR 55978, published 2025-12-04, effective 2026-02-02 | Federal Register |
| `$SOURCES/federal_register/2024-13190.txt` | Medical gas CGMP rule (amends Part 4 among others), 89 FR 51738, published 2024-06-18, effective 2025-12-18 | Federal Register |

Each eCFR section starts with a line `=== § <number> | <heading>`; subparts start with `##### SUBPART`.
Use `grep -n` / `awk '/^=== § 111.10 /,/^=== § 111.12 /'` to read sections.

**Need a part or date not cached?** Run (from the repo root):
`/usr/bin/python3 -I /private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/0308d86a-ae81-4e40-957f-b8e7f5d842f8/scratchpad/tools/fetch_ecfr.py $SOURCES <YYYY-MM-DD> <part> [<part> ...]`
and US Code: `/usr/bin/python3 -I .../tools/fetch_usc.py $SOURCES "FDCA <n>=<usc section>"`.
eCFR version history for a part: `curl -s --compressed "https://www.ecfr.gov/api/versioner/v1/versions/title-21.json?part=<N>"`.
Federal Register search API: `https://www.federalregister.gov/api/v1/documents.json?conditions[term]=...` (works with curl).

**FDA guidance / fda.gov pages:** curl is blocked by fda.gov. Use the WebFetch tool. WebFetch returns a
model-processed rendering, so a quote obtained that way is NOT machine-verifiable: record its
`check_level` as `webfetch` and do not rest a High-confidence decision on a WebFetch quote alone.
WebSearch may be used to find official URLs; never cite a non-official site as authority unless
no primary source exists (then say so and lower confidence).

**ISO 13485:2016:** the text is not available and must not be reproduced. Clause identity can be
corroborated only by FDA's own published text (e.g., 21 CFR 820.10, 820.35, 820.45, 4.4(b)(1), or
the QMSR preamble in `federal_register/2024-01709.txt`, which names clauses). If a clause number or
title in H/I can be supported only by your general knowledge, say so explicitly
(`iso_assessment: "unverified_general_knowledge"`) — that is not verification.

### Known source facts (already established — cite the files, do not re-litigate)

- QMSR: 89 FR 7496 (published 2024-02-02), effective **2026-02-02** per the Federal Register. The eCFR
  point-in-time system dates the new Part 820 text from 2026-02-04 (on 2026-02-02 and 2026-02-03
  it still serves the old QS regulation). Treat 2026-02-02 as the legal effective date; mention the
  eCFR display date only if a row turns on it.
- Current Part 820 structure: Subpart A = 820.1, 820.3, 820.5 [Reserved], 820.7, 820.10;
  Subpart B = "§§ 820.20-820.30 [Reserved]", 820.35, 820.40 [Reserved], 820.45;
  "Subparts C-O [Reserved]". The eCFR version history marks 820.50 through 820.250 (and 820.20,
  820.22, 820.25, 820.30, 820.180–820.198 etc.) as *removed*. So for a section in Subparts C–O,
  "820.X is [Reserved]" is imprecise wording (the section was removed; its subpart is reserved).
  Record that as an issue of type `precision`; it is not by itself a reason to downgrade a key
  whose substantive routing is correct. 820.20 and 820.30 *are* inside the reserved range
  "§§ 820.20-820.30".

## What to establish for every row

1. What the question asks; whether it is clear, has a false premise, or is ambiguous.
2. Whether it asks about current law, historical law, or law on a date. Current = eCFR 2026-10-14.
3. Whether each citation in G governs the question (right section, right paragraph); whether a
   governing section is missing; whether a cited section does not exist or is reserved.
4. Whether each element in J is supported by the text — correct requirement, correct numbers
   (time limits, retention periods, frequencies), correct responsible party, mandatory vs
   recommended (guidance is nonbinding; "should" in guidance ≠ requirement).
5. Whether J omits a material requirement, exception, condition, definition, or part of the
   question (e.g., the question asks "and who decides" but J does not say).
6. For H not "—": whether the ISO clause(s) are right, with the evidence tier above.
7. Rubric fairness: would a substantively correct, well-cited answer be scored correctly by this
   key? (e.g., if G cites the wrong section, a correct answer citing the right one would get L=0.)
8. For negative controls / traps / must-decline rows: confirm the premise really is unsupported
   (search the relevant part(s) thoroughly — absence in one section is not absence in the part;
   absence from the local cache is not proof a requirement does not exist anywhere), and that the
   key's required behaviour is correct.

## Status — exactly one per row

- `VERIFIED_CORRECT` — G and J are adequately supported by official text you read; no material
  error or material omission; (if H applies) clause identity corroborated by FDA text.
- `VERIFIED_INCORRECT` — a demonstrable factual error in G, H or J (wrong section, wrong number,
  wrong party, requirement that does not exist, existing thing declared nonexistent, etc.).
  If a row has both an error and an omission, use VERIFIED_INCORRECT.
- `PARTIALLY_CORRECT` — substantially right but omits a material requirement, qualification,
  exception, governing section, or part of the question.
- `AMBIGUOUS_QUESTION` — the question itself supports several reasonable readings with different
  correct answers. (Do NOT use this where the ambiguity is the tested behaviour and the key
  correctly expects the platform to ask for clarification — that key can be verified.)
- `INSUFFICIENT_EVIDENCE` — the sources you could access do not establish the expected answer
  (e.g., it depends on a guidance document you could not read reliably).
- `NEEDS_EXPERT_REVIEW` — a regulatory interpretation, historical question, ISO clause identity
  that only the controlled copy can settle, or other specialist judgment you cannot settle.
- `VERIFIED_UNANSWERABLE` — use ONLY where the key itself expects a decline / premise correction /
  out-of-scope flag, and you verified that expectation: the premise is demonstrably unsupported, or
  the question cannot be answered within Title 21 / the permitted scope. Say which in
  `unanswerable_basis` (`premise_unsupported` | `outside_scope` | `must_decline_conduct`). If any
  substantive claim inside such a key is wrong, use VERIFIED_INCORRECT instead; if it misses
  something material, PARTIALLY_CORRECT.

Do not mark VERIFIED_CORRECT because similar wording appears somewhere; the cited text must
actually support the element. Do not invent quotations, citations, dates or interpretations.

## Evidence rules (machine-checked afterwards)

- `quote` must be copied **verbatim** from a cached source file (copy with sed/awk/grep output,
  do not retype). Quotes from `ecfr_*`, `usc_title21`, `federal_register` files will be checked
  as exact substrings (whitespace-normalised) of the file named in `local_source_file`. A quote
  that fails the check invalidates the evidence item.
- Keep quotes short and pinpointed (one sentence or paragraph, ≤ 400 characters is ideal).
- Every VERIFIED_CORRECT, VERIFIED_INCORRECT, PARTIALLY_CORRECT and VERIFIED_UNANSWERABLE decision
  needs at least one evidence item that directly supports it. A correction needs evidence for the
  corrected statement. For an absence claim, give the evidence you have (e.g., the part's section
  list, the subpart structure, the text that says otherwise) and describe the search you ran in
  `search_performed`.
- `check_level`: `official_cached` (verbatim from a cached official file), `webfetch` (read via
  WebFetch from an official URL; not machine-verifiable), `general_knowledge` (labelled lead only,
  never sufficient on its own).

## Output

Write a single JSON file (UTF-8) at the path you are given: a JSON array with one object per
assigned row, in the order given, with exactly these keys:

```json
{
  "question_id": "S-001",
  "question_interpretation": "what is being asked, one or two sentences",
  "question_clarity": "clear | ambiguous | false_premise | out_of_scope | unanswerable",
  "temporal_scope": "current | historical | date_specific | not_applicable",
  "multi_provision": true,
  "status": "VERIFIED_CORRECT | VERIFIED_INCORRECT | PARTIALLY_CORRECT | AMBIGUOUS_QUESTION | INSUFFICIENT_EVIDENCE | NEEDS_EXPERT_REVIEW | VERIFIED_UNANSWERABLE",
  "unanswerable_basis": "premise_unsupported | outside_scope | must_decline_conduct | \"\"",
  "citation_assessment": "correct | incorrect | partially_correct | not_applicable",
  "answer_elements_assessment": "correct | incorrect | partially_correct | not_applicable",
  "iso_assessment": "not_applicable | corroborated_fda_text | unverified_general_knowledge | conflicts_with_fda_text | requires_controlled_copy",
  "issues": [{"type": "wrong_citation | missing_provision | unsupported_element | wrong_number | wrong_party | mandatory_vs_guidance | missing_exception | missing_question_part | temporal | false_premise_key | iso_clause | rubric_fairness | precision | ambiguity | other", "detail": "..."}],
  "explanation": "short decision rationale (2-5 sentences)",
  "proposed_corrected_answer": "replacement for J (and G/H if needed) — empty string if no change",
  "proposed_sections": "the correct governing citation(s), e.g. '21 CFR 111.10; 111.15(e)' — empty if G is right",
  "evidence": [{
     "quote": "verbatim text",
     "source_title": "e.g. 21 CFR 111.10 — What requirements apply for preventing microbial contamination...",
     "issuing_authority": "eCFR / Office of the Federal Register & GPO | FDA | U.S. Code (OLRC/GPO) | Federal Register",
     "identifier": "21 CFR 111.10(b)(1)",
     "location": "section/paragraph/clause/page",
     "url": "official URL",
     "local_source_file": "ecfr_2026-10-14/part-111.txt  (path relative to sources/, or empty for webfetch)",
     "date": "as-of / effective / publication date of the text, e.g. 'eCFR as of 2026-10-14'",
     "check_level": "official_cached | webfetch | general_knowledge",
     "supports": "what this quote establishes"
  }],
  "search_performed": "for absence/negative claims: what you searched and where; else empty",
  "confidence": "High | Medium | Low",
  "uncertainty_reason": "why not High, or empty",
  "expert_review_required": false,
  "expert_review_reason": "",
  "rubric_fairness": "fair | unfair | n/a — plus one sentence"
}
```

Validate your file parses (`python3 -c "import json;json.load(open(PATH))"`) and contains every
assigned ID exactly once before you finish. Your final message should list each ID with its status
in one line, plus anything you could not check.
