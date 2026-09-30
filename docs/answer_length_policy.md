# Adaptive answer length

> Generate the shortest answer that is still complete, accurate, and directly
> responsive to the question. Do not elaborate unnecessarily, and never omit
> material information or cut a complete answer short because it exceeds a
> preferred length.

In a regulatory system the two halves of that sentence are not equally
dangerous. A verbose answer wastes a reader's time. A severed one drops a
condition, an exception or a scope limit and is then wrong in a way that
looks right. So this policy is built so that **brevity can never be enforced
at the cost of completeness**: shortness is asked for in the instruction,
where the model can trade it off against correctness, and never imposed by a
limit, which the model cannot.

## The one distinction that matters

| | **Preferred length** | **Hard ceiling** |
|---|---|---|
| What it is | a style request in the prompt | a guard against a model that never stops |
| Where it lives | rule 10 of `GROUNDED_SYSTEM_PROMPT` | `answer_length.max_new_tokens` |
| Value | no number at all | 2048 tokens |
| Effect on a complete answer | none — the model decides | none — it is never reached |
| Effect when violated | a slightly long answer | generation is cut off, and said so |

Between them sits a third thing, the **per-question allowance**: how many
tokens *this* question is allowed. It is not a target either. The model stops
at its own end-of-turn token; the allowance only decides when it would be
severed instead. **Raising it does not make ordinary answers longer** — the
measured mean output is about 105 tokens against allowances of 256 to 1,696.
It only stops long answers being cut.

## How the allowance is derived

`GenerationBudget.tokens_for()` takes the largest of three quantities and
then applies the ceiling:

1. **A structural allowance** — `base + per_unit × units (+ range bonus)`,
   where units are the satisfied requirements, or the required sources when
   one requirement spans many rows (a whole section). This scales with how
   many provisions were asked about.
2. **An evidence-derived allowance** — the EXACT source text the answer is
   grounded in, in tokens, times `evidence_multiple`. This is the part that
   makes the policy genuinely adaptive rather than a bigger constant: a
   grounded answer restates authoritative text, so the text actually
   retrieved is a real measure of how much the answer may legitimately need.
   Four dense paragraphs get room for four paragraphs of answer without
   anyone choosing a number. It is capped at `evidence_cap_fraction` of the
   ceiling so that a whole-section question is summarised rather than
   transcribed.
3. **A floor** (`min_tokens`, 256) so that even a one-provision answer keeps
   room for the conditions and exceptions that come with it.

Only EXACT text counts toward (2). Structural and supporting sources are
context the answer should not be reproducing, so letting them inflate the
allowance would be paying for verbosity.

### What that does, measured on the live corpus

| Question | Exact sources | Evidence chars | Old allowance | New allowance |
|---|---|---|---|---|
| `820.10(b)(2)` — one provision | 1 | 197 | 128 | **256** |
| `820.10(b)(2)` and `(b)(4)` | 2 | 336 | 192 | **416** |
| `820.10(b)(1)` through `(b)(4)` | 4 | 732 | 352 | **800** |
| `820.10` — whole section | 12 | 2,388 | 448 | **1,696** |
| `820.10(b)` — parent paragraph | 1 | 223 | 384 | **896** |
| A general question | 0 | 0 | 160 | **384** |

The old 448 in the whole-section row is not a coincidence: it was the old
hard ceiling. The ceiling was setting the answer length, which is precisely
the failure this policy removes. The widest allowance the new policy can ask
for is 1,760, comfortably under the 2,048 ceiling, so the ceiling is once
again only a guard.

## Why the ceiling is 2048 and why that is deliberate

* **Context is not the constraint.** The model's window is 40,960 tokens and
  the retrieval context is hard-capped at 9,000 characters, so a prompt runs
  to roughly 2,600 tokens. There is no context reason for any ceiling below
  about 38,000.
* **Generation speed is the constraint.** Measured at **1.86 tokens/second**
  on this CPU-only machine, 2,048 tokens is about 18 minutes in the
  pathological worst case.
* **That cost is accepted on purpose.** The ceiling is only reached by a
  model that will not stop; a normal answer is about a minute. Paying for a
  rare pathology is the right trade against severing legitimate answers,
  which is the failure this work exists to remove.
* **It sits above every allowance the policy can request** (1,760), which is
  what keeps "the answer hit its allowance" and "the answer hit the ceiling"
  two distinguishable events. The validator reports which one happened.

### Adjusting it safely

Lower `answer_length.max_new_tokens` only if you would rather cut a long
answer than wait for it, and keep it above `base_tokens + per_unit_tokens ×
max_units + range_bonus_tokens` (currently 1,760) — otherwise the ceiling
starts deciding answer length again and the distinction above collapses.
Raise it freely on faster hardware. One knob, one file:

```yaml
answer_length:
  policy: adaptive          # or "fixed" to restore the pre-adaptive behaviour
  max_new_tokens: 2048      # the ceiling; NOT a target length
```

Environment overrides: `REGULUS_MAX_NEW_TOKENS`,
`REGULUS_ANSWER_LENGTH_POLICY`.

### What the configuration does **not** control

It does not tell the model to be brief. Nothing in `answer_length` is a
length preference — it is all headroom. Brevity is asked for once, in rule 10
of the grounded system prompt, where it is a style request the model can
trade off against completeness. That separation is the whole design: a number
in a config file cannot weigh "shorter" against "still correct", so it is
never given the chance to.

## What the instruction says

Rule 10 of `GROUNDED_SYSTEM_PROMPT`:

> Length: answer the question directly and completely, then stop. Use the
> minimum amount of text a complete and accurate answer needs. Leave out
> background the question did not ask for, repetition, filler, restatements
> of the question, and explanations of your own citations. Never drop a
> condition, exception, applicability or scope limit, effective date,
> cross-reference, required action or a distinction between subsections in
> order to keep the answer short, and never stop before the answer is
> complete. When completeness needs more detail, write more.

The per-shape `ANSWER FORMAT` lines fix the answer's **structure** — which
the validator, the citation builder and the Stage 6 training data all depend
on — and deliberately fix no length. They used to say "two to four plain
sentences" and "one to three plain sentences"; that is a preferred length
dressed as a format rule, and a model obeys it by dropping qualifiers. A
regression test asserts no sentence or word count ever reappears in the
system prompt or in any format line.

There is no second, competing system prompt. `RAG_SYSTEM_PROMPT` in
`regulus/rag/prompt.py` is untouched on purpose: it is not on the grounded
answering path, it renders training examples in the legacy format, and
editing it would change a dataset that is meant to reproduce byte for byte.

## Incomplete generation

Truncation is detected from the **end-of-turn token**, not from a token
count, so it is exact rather than inferred: `GenerationResult.finished` is
true only when the last token generated is an EOS id. A long answer that
finished properly is never called truncated, and a short answer that ran out
of budget always is.

When it happens:

1. The validator raises a `truncated` problem at error severity, naming
   which limit was reached — *this question's allowance* (raise it) or *the
   hard safety ceiling* (the model was not stopping).
2. The repair layer appends any requested provision the cut removed,
   verbatim from its exact source. This completes the answer from
   authoritative text and cannot duplicate or invent.
3. The answer is marked, visibly: *"(Incomplete: generation stopped at the
   token limit before this answer finished, so wording after this point is
   missing.)"* Truncation is never hidden and a severed answer is never
   presented as a finished one.

There is deliberately **no automatic re-generation**. A second pass at a
larger budget would double a 40–150 second answer for a case the widened
allowance has largely removed, and a continuation pass risks contradicting or
repeating the first. The order of preference in the design was: make the
budget large enough, keep the ceiling generous, detect reliably, and only
then consider retrying. The first three were enough.

## Evaluating it

Length alone says nothing. The Stage 5 harness already measures the things
that matter, and the dashboard shows them together:

| What to watch | Where |
|---|---|
| Completeness — every requested provision addressed | `multi_provision_accuracy`, `range_accuracy`, `completeness.all_addressed_raw` |
| Factual correctness | `correctness_raw` (never `correctness_final`, which is the repair layer) |
| Citation correctness | `citation_ok`, `exact_source_citation` |
| Incomplete generation | `truncated_count`, and the `truncated` validation code per question |
| Unnecessary verbosity | `avg_generated_tokens` read **beside** completeness, never alone |

The desired direction is more complete at similar length, not shorter. A fall
in `avg_generated_tokens` with a fall in completeness is the policy failing,
not succeeding. `policy: fixed` restores the previous behaviour so the two can
be evaluated against each other on the same benchmark.

How the answer is *organised* (synthesis, enumeration, focused, comparison)
is a separate concern handled by the answer shape; it never feeds the
allowance. See [adaptive_answer_shape.md](adaptive_answer_shape.md).

## Known limitations

* **The allowance is headroom, not a guarantee of quality.** It stops answers
  being cut; it does not make a 0.6B model more complete. If an answer omits a
  requirement while finishing well under its allowance, that is a model or
  prompt problem and widening the budget will not fix it.
* **A rambling answer is now allowed to ramble further** before anything stops
  it, up to the ceiling. The degenerate-repetition check catches loops, but
  only after generation, so a pathological answer costs more wall-clock time
  than it used to. The ceiling is the backstop and it is one config value.
* **`evidence_multiple` and `CHARS_PER_TOKEN` are estimates**, not
  measurements of this tokenizer. They are set so that mis-estimating makes
  the allowance larger rather than smaller.
* **Verbosity has no automatic metric.** "Unnecessary" is a judgment;
  `avg_generated_tokens` beside completeness is the closest proxy the harness
  has, and it needs a person to read it.
