# Follow-up questions, answer layout and the composed fallbacks (26 Oct 2026)

This document covers what was added on 26 Oct 2026. It describes how each piece decides what it does, how it was
measured, and how to switch it off. Everything here is deterministic: no part of it asks the model to decide.

## 1. Follow-up questions (`regulus.rag.conversation`)

### What the server reads

The UI server reads a conversation's earlier turns from its chat store (`ConversationStore.prior_turns`). The browser
never supplies them.

- Each turn is reduced to its question and its stored **anchor**: the provisions the turn was resolved to.
- An anchor holds promoted 21 CFR sections, FD&C Act sections, named sections, or whole parts.
- Companions are never stored. They are re-derived for each question from its own words.
- Only answers with status `ok` count.
- A stored anchor is sanitized on read (`Anchor.from_dict`).

### When a question is anchored

A question is **anchored** to the most recent anchor when it depends on the conversation. Any one of these is enough:

| Signal | Example |
|---|---|
| A pronoun before any subject of its own | "Can we use *it* in an eye shadow?" |
| A pointer | "paragraph (b)", "this section" |
| An elliptical or tag form | "What about …", "…, right?" |
| A fragment | "Is there an exemption?" |
| A subject it shares with the conversation | at least 20% of its subject words, or 3 of them |
| Its own ranking puts an anchored section in the top 3 | only for questions that are not self-contained |

A question is **not** anchored, and is answered on its own, in these cases:

- it names its own provision;
- it names a color additive that the anchored sections do not list;
- it is a definition question ("What is a cosmetic?");
- nothing ties it to the conversation.

In each of these cases the model is not shown the earlier question.

### How an anchored question is answered

- Section promotion uses method `conversation`. There is no ranking and no picker call.
- Companions come from the question's own words. For example, "eye shadow" adds 70.5(a) and 70.3(s).
- Pointers are written out as the primary anchored section: "this section" becomes "21 CFR 74.2708".
- The prompt shows the earlier question as context only (`GenerationPackage.earlier_question`).
- The claim and figure checks treat facts the user stated earlier as given.
- The color-listing composer accepts a color named earlier in the conversation. The products it judges are still
  the follow-up's own.

### Measured

| Check | Result |
|---|---|
| 1,000 dev bank follow-ups (resolution only) | 56% anchored; 91% of those to a section the verified key cites |
| Self-contained questions from another part, asked after a parent | 2.2% wrongly anchored |
| 1,140 generic follow-ups across every 300-question domain | 100% anchored to their section or part |
| Questions asked on their own | 238/238 recorded answers replay byte-identical |
| 64 follow-ups, blind A/B | 22 PASS / 27 FAIL (old code) → 29 PASS / 14 FAIL (follow-ups plus the switches below) |

The A/B was scored by one scorer, and the switches were tuned on those same rows. The overnight run of 1,000 dev
follow-ups is the real measure.

### Switching it off

Pass no `context` to `RagPipeline.answer`. Every question is then answered on its own, exactly as before.

## 2. Answer layout (`regulus.rag.presentation`, `result["presentation"]`)

The delivered text is split into four parts, and its wording is never changed:

- the direct answer, with a Yes / No / Permitted verdict where the text gives one;
- what the regulation says, one point per provision;
- notes and limits;
- the sources.

A withheld or declined answer reads plainly and lists the provisions consulted. The page also adds:

- a follow-up context line;
- the eCFR date;
- "not legal advice";
- up to three suggested follow-ups, built from the answer's anchor.

The layout is for display only. The answer that is copied, stored, evaluated and scored is unchanged. Checked on 191
recorded answers: no sentence lost.

## 3. Every question is read against all of Title 21

The page has no topic selector (removed 26 Oct afternoon). A user asks anything, and a question that names no
product domain is read against all of Title 21. A question that names a cosmetic product or programme is still read
as a cosmetics question.

- Why: 90 of the 300 acceptance questions name no provision and no domain. A cosmetics prior limited them to
  cosmetics sections: with it, 63 of the 300-question key sections were candidates; without it, 136. The cosmetics
  bank lost 1 candidate (179 → 178).
- `REGULUS_DEPLOYMENT_SCOPE` is unset in `configs/ui.env.example`. An API client may still name a focus
  (`regulus.retrieval.section_index.focus`); the page never does.

## 4. Composed fallbacks: answers built from the database text

These live in `regulus.rag.validator_switches`. Each is a separate switch.

| Switch | Fires on | Answer |
|---|---|---|
| Q1 | an answer that cannot be shown (withheld, or the model declined) on a **confidently** identified provision | that provision's paragraphs most relevant to the question, verbatim, followed by a note that they are not applied to the reader's facts |
| FP1 | a confirmation question attributing to the provision a figure no supplied text states ("paid $150 … correct?") | "No. The figure … does not appear in …", followed by the paragraphs that state figures of that kind |
| RS1 | a records question about sections whose full text has no record-keeping language | "… sets no recordkeeping requirement", followed by what the section requires |
| QM1 | a former Quality System regulation section (820.30, 820.100 …) or an ISO 13485 clause that does not exist | the section is not in the current eCFR; the live part 820 text is quoted; the ISO 13485:2016 clause on that subject is given by number and title only, with its basis (`data/reference/qmsr_v1.json`) |
| D1 | an explicit request for the meaning of terms | the requested provisions' paragraphs that define every term |

**What counts as confident identification:**

- a provision the question names itself;
- the conversation's anchor;
- an exact color-additive name;
- an FD&C Act section the question names.

The picker's choice among candidates does not count.

**Paragraph choice.** The paragraphs quoted are ranked by meaning (`regulus.rag.quote_selection`, bge-small). Shared
words break ties.

**Validation.** Every grounding check still applies. The shape-completeness findings do not, because these answers cover
one point on purpose. The live evaluator shows them NOT FULLY EVALUATED, never PASS or FAIL
(`regulus.accuracy.review.QUOTED_FALLBACKS`).

### Precision on the bank keys

| Switch | Result |
|---|---|
| FP1 | fires on 56 false-premise follow-ups; all 56 keys say "No" |
| RS1 | fires on 49 records follow-ups; 47 keys say the section prescribes no records. The other 2 ("what must our request record?") no longer fire |
| D1 | 1 change in 315 replayed answers (COS-82.3-Q1: withheld, now both definitions quoted) |

### Status

These switches are off by default. The overnight run of 26–27 Oct runs with them on. If it confirms the A/B, they are
turned on in `VALIDATOR_PRECISION`'s default.

## 5. Data repairs (26 Oct)

**Reserved-range paragraph paths: repaired.** Some sections had their paragraphs stored under a reserved-range row
("(a)-(f) [Reserved]"), so 82.3(g) was stored as "(a)(g)" and 82.3(n) as "(a)(k)(n)". The paths were rewritten in the
database:

| Section | Rows |
|---|---|
| 82.3 | 8 |
| 105.3, 164.120, 202.1 | 23 |

Each repair has an exact rollback in `~/regulus_eval_runs/programme_20261026/db_repair/`. 310.201 shows a different
pattern and is left as stored until it is reviewed.

**FD&C Act store: 17 → 44 sections** (3,543 paragraphs), from the official U.S. Code 2024 edition (govinfo). The raw
files are in `data/raw/statute_fdca`. The parser accepts an en dash in headings ("§360e–3"). Recorded answers replay
byte-identical with the larger store. Citing an Act section a promoted regulation names (ST1) is behind a switch and off:
the Act text rarely fits the evidence budget.

## 6. Rejected on 26 Oct

- **Speculative decoding (MLX draft model):** outputs differed from the plain model's and were slower (27 s → 41 s on
  the same questions). Reverted.
- **Removing the live evaluator for speed:** it takes 0.15 s per answer (0.74 s at most) after a 20–140 s answer. Kept.

## 7. Added on 26 Oct afternoon

Each is a general rule behind a switch, replayed on every recorded answer and blind-scored live before use.

| Switch | What it does | Measured | Tonight |
|---|---|---|---|
| PO2 | a question naming only a part outside the cosmetics programme ("under Part 211") is resolved to its section(s) inside that part | 19 dev questions: PASS + PARTIALLY PASS 1 → 3; 3 partly-correct answers became withheld; no PASS lost | on |
| `REGULUS_PARAGRAPH_DENSE_SCOPE=title21` | the reranker reads every part of Title 21, so its veto of a wrong pick works outside cosmetics | 34 recorded 300-question picks: 1 corrected (S-007), none changed otherwise | on |
| C2 | a condition stated in a cited paragraph's lead-in (its parent) or its child counts as stated in the cited source; a sibling does not | 397 recorded answers: 6 changed; FAIL → PASS 2, FAIL → PARTIALLY FAIL 3, none worse | on |
| SA1 | a general question is offered the 3 FD&C Act sections it is most about, as cosmetics questions are offered chapter VI | key Act section offered for 18 of 19 Act-keyed dev questions; live A/B with regulation-keyed controls | if its A/B passes |
| SP2 | the picker's second same-part regulation joins the first | 14 dev questions: 2 more PASS, but one answer took a wrong section and stated a wrong rule | off |

The paragraph index for all of Title 21 is prebuilt with `python -m regulus.retrieval.paragraph_dense` (69,476
paragraphs, about 20 minutes once, cached per part). A section added by SP2 is further evidence: an answer that
leaves it out is not withheld (`GenerationPackage.optional_labels`).

Not changed, on evidence: the claim check still withholds answers whose only problem is a low share of supported
words. Nearly all such sentences state an absence ("no provision authorizes ..."), the false-denial pattern, and
several were wrong.
