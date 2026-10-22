# Capacity comparison: pre-registration (read-only, in-process settings only)

Written before any candidate was run. No code, prompt, configuration, database or index changes. Candidates are
`ContextPolicy` values (or the budget charge) overridden in the harness process only. No model and no embedding model
are run.

## Candidates (each differs from production in one dimension only; same ordering "tier", same reserve)
- **T4800:** `max_total_chars` 3,600 → 4,800 (+1 source's worth).
- **T6000:** `max_total_chars` 3,600 → 6,000 (+2 sources' worth).
- **H3600, packing:** budget unchanged at 3,600, but each source block is charged for its text plus a compact header
  ("SOURCE n" + Citation line) instead of the full rendered header (Corpus, Heading, URL lines). This measures what more
  efficient headers alone would admit; the rendered prompt is not changed here.

## Fixed acceptance criteria (each candidate, against production on the same inputs)
- **K1.** Required paragraphs in context, 100 cosmetics questions: 0 lost. Gains are reported.
- **K2.** 352-row baseline: 0 keyed targets lost, and the summary counts (identifier and plain-language in context) are
  not lower.
- **K3.** Guidance retention: 0 guidance passages present in the production context are removed (100 questions).
- **K4.** Ordering unchanged: the selected sources are a superset of production's, in the same relative order. No
  category is moved ahead of another.
- **K5.** Cost: estimated input growth reported at 4 chars per token. Using the Step 6 fit of 2.155 ms per input token,
  the added prefill must be ≤ 1.5 s on the largest context. Contexts stay within the hard ceilings.

**Reporting:** gains in required paragraphs and keyed targets are reported per question. Added material is reported by
corpus, but its relevance is not judged in this read-only step.

**Decision:** a candidate that meets K1–K5 is eligible to be proposed as the next authorized experiment. A candidate
that fails any of them is not. This step recommends; it changes nothing.
