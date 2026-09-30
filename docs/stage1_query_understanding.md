# Stage 1: Query Understanding, Multi-Reference Parsing and QueryPlan

Stage 1 replaces the first-reference-only parser with a query-understanding
layer that extracts every CFR reference in a question, normalises it,
expands ranges and lists into atomic requirements, and records the result
as a `QueryPlan`. Retrieval, grounding, generation and evaluation are
unchanged: they still consume `classify()` exactly as before. The plan is
recorded in the pipeline's metadata for inspection and will be consumed by
retrieval in Stage 2.

## 1. Responsibilities

The parser answers "what did the user ask for?" and nothing else:

* it does not consult the database (`21 CFR 820.999` parses like any other
  reference; existence is decided later);
* it does not retrieve, generate or judge sufficiency;
* it does not call the model. Everything is regular expressions and small
  rules, so it is deterministic, fast and reproducible.

## 2. Where the code lives

| File | Role |
|---|---|
| `src/regulus/retrieval/references.py` | the single authoritative scanner: `CfrReference`, `scan_references()`, `parse_cfr_references()`, range expansion, continuation resolution, bare-number safety rules |
| `src/regulus/retrieval/query.py` | classification API; `parse_cfr_reference()` now returns the first reference in text order via the scanner; `QueryClassification.references` exposes all of them; `CfrReference` is re-exported so existing imports keep working |
| `src/regulus/planning/plan.py` | `Requirement`, `QueryPlan`, `plan_query()`, plan kinds |
| `src/regulus/grounding/identifiers.py` | `extract_identifiers()` (multi-reference view; the Stage 13 gate still uses `extract_identifier()`) |
| `src/regulus/rag/pipeline.py` | records `metadata["plan"]`; no behavioural change |
| `scripts/plan.py` | debug tool: prints the trace question → mentions → ranges → requirements, or the plan as JSON |
| `tests/test_query_plan.py` | Stage 1 tests |

## 3. Recognised forms

Explicit forms (unchanged from Stage 5, now found everywhere in the text,
not just first):

    21 CFR 820.10(b)(1)     21 C.F.R. § 820.10     21 CFR part 820
    § 820.10(b)(1)          section 820.10(b)      part 820

Bare forms (new):

    820.10(b)(1)            820.10

Ranges (new; the connector may be `through`, `thru`, `to`, `-`, `–`, `—`):

    820.10(b)(1) through (b)(4)        820.10(b)(1)-(b)(4)
    § 820.10(b)(1) through § 820.10(b)(4)
    21 CFR 820.10(b)(1) through 820.10(b)(4)
    820.10(b)(1)-(4)                   (shorter end point inherits "(b)")

Lists and continuations (new; connectors `,`, `;`, `and`, `or`, `&`):

    820.10(b)(1), (b)(2), (b)(3)       820.10(b)(1) and (b)(4)
    820.10(b)(1) and (2)               820.10(b)(1), (b)(2), and 820.10(b)(4)
    § 820.10(b)(1), § 820.10(b)(2), and § 820.10(b)(4)

Multiple complete references, in any mix of forms and sections, are all
kept in text order.

## 4. Normalisation and de-duplication

Every form of the same provision resolves to one `CfrReference` whose
`canonical` label is `"21 CFR 820.10(b)(1)"` and whose `key` is the tuple
`(title, part, section, paragraph_path)`. The original text is kept in
`raw`. Duplicate mentions collapse to the first occurrence and are listed in
the scan notes; a parent (`(b)`) and its children (`(b)(1)`) are different
provisions and are both kept.

## 5. Range expansion

A range expands when both end points are paragraphs of the same section, at
the same depth, under the same parent, and the final tokens are the same
kind. The kind is decided by depth, following the eCFR nesting
(a) → (1) → (i) → (A) → (1) → (i), so `(g) through (i)` at depth 1 is the
letters g, h, i while `(a)(1)(i) through (iv)` at depth 3 is roman. A range
that cannot be expanded (different sections, reversed, above
`MAX_RANGE_EXPANSION` = 50) keeps its two end points and records why in the
notes. Section-level ranges (`820.10 through 820.30`) are deliberately not
expanded without the database.

## 6. Bare-number safety

A bare dotted number with paragraph tokens is always a reference. A bare
dotted number alone is a reference unless a cue marks it as something else:

* before it: `pH`, `version`, `v`, `rev`, `clause`, `step`, `phase`,
  `figure`/`fig.`, `table`, `item`, `chapter`, `ISO`, `IEC`, `ASTM`, `ANSI`,
  `USP`, `ICH`, `no.`, `#`, `$`, `€`, `£`, `part`;
* after it: `%`, `percent`, `mg`, `mcg`, `kg`, `ml`, `mm`, `cm`, `ppm`,
  `hours`, `days`, `weeks`, `months`, `years`, `minutes`, `seconds`,
  `million`, `billion`, `degrees`, `fold`, `times`, `units`, `inches` and
  similar;
* a cue on one end of a connected pair (`pH 6.5 to 7.5`) excludes both ends;
* numbers glued to other digits or dots (`1.2.3`, `7.5.8`) are never
  references.

Plain integers are never references (`20 records`, `in 2024`). Every mention
records its `form` (`cfr`, `symbol`, `section_word`, `part_word`, `bare`,
`continuation`) so later stages can treat a bare section-only mention more
cautiously than an explicit one.

## 7. Continuations

A paragraph-only fragment such as `(b)(2)` continues the nearest earlier
reference only when the text between them is a list or range connector.
Ordinary words break the chain, so `... require (a) documentation` does not
create `820.10(a)`. A fragment shorter than the previous path inherits the
missing parent levels when the token kinds agree: `820.10(b)(1) and (2)` is
`(b)(2)`, while `820.10(b)(1) and (c)` is `(c)`.

## 8. QueryPlan

```
QueryPlan
  question              as received
  normalized_question   whitespace-normalised; scan spans refer to this
  query_type            existing QueryType (EXACT_CFR, GUIDANCE_SEARCH, GENERAL_REGULATORY_SEARCH, EMPTY)
  kind                  single_provision | range | multi_provision | multiple_reference | general | unknown
  requirements          ordered tuple of Requirement
  docket, guidance_requested
  scan                  ReferenceScan: mentions, ranges, resolved references, notes
  notes

Requirement
  id ("r1"...), order, reference (CfrReference), raw, origin
  origin: explicit | continuation | range_expansion
  properties: canonical, key, title, part, section, paragraph_path, level
```

Both are frozen dataclasses with `to_dict()`; `QueryPlan.explain()` renders
the trace shown by `scripts/plan.py`.

Example:

```
$ python scripts/plan.py "What does 21 CFR 820.10(b)(1) through (b)(4) require?"
question: 'What does 21 CFR 820.10(b)(1) through (b)(4) require?'
query_type: EXACT_CFR   kind: range
mentions: 2
  [0] cfr           '21 CFR 820.10(b)(1)'            -> 21 CFR 820.10(b)(1)
  [1] continuation  '(b)(4)'                         -> 21 CFR 820.10(b)(4)
ranges: 1
  21 CFR 820.10(b)(1) through 21 CFR 820.10(b)(4): expanded to 4
requirements: 4
  r1  21 CFR 820.10(b)(1)          origin=explicit         raw='21 CFR 820.10(b)(1)'
  r2  21 CFR 820.10(b)(2)          origin=range_expansion  raw='21 CFR 820.10(b)(1) through (b)(4)'
  r3  21 CFR 820.10(b)(3)          origin=range_expansion  raw='21 CFR 820.10(b)(1) through (b)(4)'
  r4  21 CFR 820.10(b)(4)          origin=continuation     raw='(b)(4)'
```

## 9. Backward compatibility

* `parse_cfr_reference(text)` keeps its signature and returns the first
  reference **in text order**. Before Stage 1 it preferred the "21 CFR" form
  over "§" regardless of position; a question naming both forms in the
  other order now yields the earlier one.
* `classify()` keeps its signature and fields; `references` was added.
* `CfrReference` keeps its fields; `canonical`, `key` and
  `paragraph_tokens` were added.
* Bare "820.10" is now a reference. One existing test that asserted the
  opposite was updated with a comment; no other test changed.
* Because `LexicalRetriever.run()` still calls `classify()`, questions that
  previously ran a general search and now parse as EXACT_CFR (bare
  references) run the exact-lookup leg as well. This is the intended
  direction, but it also means a bare decimal that slips past the cues
  triggers an exact lookup that returns nothing, adds a "no live record"
  note, and, with the grounding gate on, a refusal. Stage 3 will use the
  mention `form` to treat bare section-only mentions more leniently.
* Retrieval still uses only the first reference; multi-reference retrieval
  is Stage 2.

## 10. Known limitations

* "subsections (b)(1) through (b)(4) of 820.10" (fragments before the
  section) yields only `820.10`; the "of <section>" form is not resolved.
* "to" between two paragraphs of one section is always a range, so
  "compare (b)(1) to (b)(4)" expands to four provisions. Over-inclusion is
  harmless for retrieval but is not a comparison plan.
* Section-level ranges and multi-letter paragraph tokens (`(aa)`) are not
  expanded.
* Cue lists are finite; an unlisted unit after a bare decimal ("2.5 units of
  X" is covered, "2.5 vials" is not) produces a false reference.
* Continuations follow list connectors only; a fragment after ordinary
  words is ignored even when a human would attach it.
* The plan carries no intent (define, compare, why); that belongs to the
  planner work of later stages.

## 11. Boundary with Stage 2

Stage 1 ends at the `QueryPlan`. Retrieval (`LexicalRetriever.run()`), the
`RagPipeline` flow, ranking, context construction, the grounding gate and
citations are unchanged and still act on the first reference. Stage 2 will
add a plan-driven retrieval entry that runs exact retrieval for every
requirement, tags results with the requirement they satisfy, and makes the
text legs and fallback conditional on the plan.
