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

## 3. Focus control (`regulus.retrieval.section_index.focus`)

The page's Focus control is either **Cosmetics** (the deployment default) or **All of 21 CFR**. It sets, per request,
how a question that names no product domain is read.

This matters because 90 of the 300 acceptance questions name no provision and no domain. A cosmetics prior would limit
them to cosmetics sections, so the acceptance benchmark runs with `REGULUS_DEPLOYMENT_SCOPE` unset.

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

## 5. Known data defect

21 CFR 82.3's definitions are stored under a reserved-range row ("(a)-(f) [Reserved]"). As a result:

- (g) is stored as "(a)(g)";
- (n) is stored as "(a)(k)(n)";
- and so on for the rest of the section.

A repair and its exact rollback, for the user to apply, are in
`~/regulus_eval_runs/programme_20261026/db_repair/82.3_paths_{fix,rollback}.sql`. Four other sections show the same
pattern and need review before any repair: 105.3, 164.120, 202.1 and 310.201.
