# SME key review: operating plan for the 300-question benchmark

Preparation for human review. Nothing here decides a row, and no gate moved:
the benchmark hash is unchanged, no locked key exists, and scoring and
training both still refuse.

## 1. Readiness of the existing workflow

The workflow was audited by using it the way a reviewer would, one row at a
time, across five representative questions. It was sufficient in structure —
states, append-only decisions, sign-off, gating, versioning — and **deficient
in one respect that would have dominated the operation**.

### Defect found: packets carried no provision text

An SME judging "does 21 CFR 111.1 require what column J says?" was given the
citation and the automated finding, but not the provision. To answer, they
would have had to leave the tool and navigate eCFR by hand — for all 300
rows, twice over, since substance and completeness are both judged against
the text. That is slow and, worse, it invites judging from memory.

**Fixed.** Packets now carry the eCFR text of every provision the draft key
cites, from the read-only snapshot. The CFR is a US Government work, so
quoting it is unproblematic; ISO text is never included, and a test asserts
that nothing in the packet pipeline can return it.

### Second gap: absence claims had no absence evidence

Fifteen rows ask the reviewer to accept "NO SUCH REQUIREMENT / LIMIT /
GUIDANCE / SUBPART". The packet offered nothing to reason from, which amounts
to asking someone to prove a negative from memory.

**Fixed.** For negative controls the packet now carries a targeted search of
the named part for the question's subject terms, with the caveat printed
beside it: an empty or partial result is *consistent* with the claim and does
not establish it — the requirement may be worded differently or sit elsewhere.

### Third gap: no way to work offline

`packet` served one row at a time. Added `batch`, which writes every packet
of a domain, question type or the ISO set to a JSON file.

Nothing else was changed. The state machine, gate, versioning and audit
trail were already sufficient.

## 2. The 300 rows by work required

Every row needs **F substantive** and **G completeness** — 300 and 300. Those
are the floor. The table is the work *beyond* them.

| Work beyond F+G | Rows |
|---|---|
| — none (F+G only) | **221** |
| E ISO clause, crosswalk disagrees | 23 |
| E ISO clause, crosswalk silent | 16 |
| A citation, unresolvable from the key | 24 |
| D absence claim, not a section lookup | 15 |
| D absence claim, unresolvable | 2 |
| A citation, contradicted | 1 (X-004) |
| C temporal, unresolvable | 1 |

By count of extra dimensions: **221 rows F+G only · 76 rows one extra · 3 rows
two extra** (category H: `M-030` citation+ISO, `PB-008` temporal+ISO,
`NC-014` citation+absence).

The 24 "citation unresolvable" rows are not defects: they are the negative
control, temporal and scope rows whose column G is a *declaration* rather than
a citation, so there is nothing for a citation check to resolve.

## 3. Evidence availability, by authority

| Evidence | Source | Status for review |
|---|---|---|
| CFR section/paragraph existence | eCFR snapshot 2026-09-03, 65,341 live records | **Sufficient**, in the packet |
| CFR provision text | same | **Sufficient**, now in the packet |
| Reserved / removed status | `is_reserved`, reserved-range records, crosswalk `resolution_status` | **Sufficient** for Part 820; thinner elsewhere |
| ISO clause *identity* | internal clause index, 88 clauses, titles only, **no text** | Sufficient to check a clause number exists |
| ISO clause *mapping* | internal approved crosswalk, 189 rows | **Evidence only — NOT authority** |
| What an ISO clause requires | controlled ISO 13485:2016 | **Not held. Reviewer must consult it** |
| FDA guidance existence | guidance tables present, coverage unassessed | Treat as unverified until checked |
| Substantive meaning | the provision's text plus the reviewer | **Judgment, never a lookup** |

The distinction that must not blur: the crosswalk was approved *inside this
project*. Where it disagrees with the workbook's draft key, neither wins on
authority — the controlled standard decides. Every ISO packet prints this.

## 4. Recommended batching

Eight batches, ordered so that the reviewer's frame of reference stays fixed
within a batch and the hardest work is done when calibration is freshest.

| # | Batch | Rows | Why grouped |
|---|---|---|---|
| 1 | Calibration set (drawn across domains, §8) | 20 | Establishes criteria before volume |
| 2 | Part 820 / ISO-bearing | 43 | One standard, one crosswalk, one mental model; needs the controlled ISO copy to hand |
| 3 | Negative controls | 22 | Absence reasoning is a distinct discipline; batching prevents drift between "absent" and "not applicable" |
| 4 | Scope & platform behaviour | 22 | Judged against scope rules, not provisions |
| 5 | Food chain (111 · 117 · 101 · 108–123 · Part 1 · 507) | 87 | Adjacent parts, shared vocabulary |
| 6 | Drug chain (210/211 · 201/207 · 50–312 · 600–680) | 53 | Same |
| 7 | Device chain excluding 820 (807/814/812/860 · 803/806/7 · 801/809/830) | 30 | Same |
| 8 | Remainder (tobacco · cosmetics · radiological · combination) | 23 | Small domains, no shared frame |

Reasoning, in priority order as instructed — correctness, consistency,
auditability, then efficiency:

* **Correctness.** Grouping by regulatory part keeps one body of law in view
  at a time. Mixing 21 CFR 111 with 21 CFR 820 invites importing a
  requirement from the wrong regime.
* **Consistency.** The ISO and negative-control batches concentrate the two
  kinds of judgment most at risk of drifting, so a single criterion is applied
  across all of them in one sitting.
* **Auditability.** Batch boundaries follow the workbook's own domain labels,
  so a later reader can map decisions back to the contract's structure.
* **Efficiency** is what remains: batch 2 is the only one needing the
  controlled ISO copy open, and batches 5–7 are the volume, which is largely
  F+G against text now in the packet.

## 5. Packet quality after the fix

Checked against the five representative rows:

| Row | Class | Packet now carries |
|---|---|---|
| S-001 | straightforward citation | 111.1's full text, paragraph by paragraph — the substantive judgment can be made from the packet |
| M-021 | ISO conflict | 820.35(a) text, the draft clause 8.2.2, the crosswalk's 4.2.5, and the statement that the controlled standard decides |
| NC-004 | absence claim | what Part 211 *does* say about quality-control-unit approval, plus the caveat that this does not prove absence |
| X-004 | contradicted citation | the contradiction, the sections that do resolve, and the missing 4.106–4.110 |
| any row | substantive/completeness | column J beside the provision text, with the reminder that this is a judgment |

Still missing, deliberately, and not fabricated: the controlled ISO text, FDA
guidance documents for the guidance-absence rows, and the Federal Register
notices behind the reserved provisions. Those are external consultations and
are named as such in the packet.

## 6. Reviewer protocol

For each row, in order. Nothing here requires knowing how the software works.

1. **Read the question and the draft key.** They are the contract's words.
2. **Read the provision text in the packet.** If the key cites nothing
   resolvable, the key is a declaration — go to step 4.
3. **Is the citation right?** Correct to the section, and to the paragraph
   wherever the answer asserts a paragraph-level requirement.
4. **If it is wrong, what should it say?** Record the correction. The original
   is kept automatically; you are not editing the workbook.
5. **Is the substantive expectation right?** Does the provision actually
   require what column J says — `correct`, `partially_correct`, `incorrect`.
6. **Is the completeness expectation right?** Does the key name every
   governing provision the question reaches — same three values.
7. **What evidence did you use, and why did you decide that way?** One
   sentence each. Both are mandatory; the system refuses a decision without a
   rationale.
7a. **If column J itself is wrong** (it states something the provision does not),
   record CORRECTED with `--corrected-key-elements "..."` and at least one
   `--evidence` reference. The workbook's J is kept beside yours. Your J
   reaches the locked key only for rows that end VERIFIED. See
   `docs/benchmark_key_integrity_investigation.md` §8.
8. **If you cannot settle it, say so** — `NEEDS_RESEARCH` with what is needed.
   Parking a row is a legitimate outcome and blocks sign-off until resolved,
   which is the intent.

```bash
python scripts/review_benchmark_key.py packet S-001
python scripts/review_benchmark_key.py decide S-001 --state ACCEPTED \
    --reviewer "Name, Title" --rationale "111.1(a) states the subject persons" \
    --substantive correct --substantive-rationale "matches (a) and (b)" \
    --completeness correct --completeness-rationale "111.1 is the only governing section"
```

## 7. Special cases

### X-004 — do not correct it here

The draft key reads **"21 CFR 4.100 through 4.110"**. The snapshot's Part 4
holds 4.1, 4.2, 4.3, 4.4, 4.100, 4.101, 4.102, 4.103, 4.104, 4.105 — it ends
at 4.105.

What the SME must establish, in this order:

1. Does 21 CFR 4.106–4.110 exist in the *current* eCFR? The snapshot is dated
   2026-09-03; confirm against the live source before concluding.
2. If they do not exist, was the range a drafting slip for 4.100–4.105, or
   does the intended answer lie elsewhere (Part 4 Subpart B postmarket safety
   reporting)?
3. Does the corrected range still satisfy the question — postmarket safety
   reporting for a combination product applicant — and column J's elements
   (reporting by constituent part, five-day and malfunction reporting, shared
   responsibilities)?
4. Record CORRECTED with the range you determine, or NEEDS_RESEARCH.

### ISO conflicts — 23 rows

The draft key and the internal crosswalk name different clauses; both clause
numbers exist. Example: M-021 maps 820.35(a) to **8.2.2 Complaint handling**
while the crosswalk maps the section to **4.2.5 Control of records**.

* The source to consult is the **controlled copy of ISO 13485:2016(E), third
  edition, 1 March 2016**, as incorporated by reference at 21 CFR 820.7(b).
* The internal crosswalk is a project artifact approved internally. It is
  **evidence of an internal position, not authority for what the standard
  requires**, and it maps at *section* granularity while the key often speaks
  at *paragraph* granularity — which explains many of the 23 without either
  side being wrong.
* Record the clause the standard supports. Do **not** copy standard text into
  the rationale; identify the clause by number and title only. Reproducing the
  text would itself be a scope-discipline failure under the workbook's rules.
* Eight further rows read column H as `None`, meaning the correct answer names
  no clause. A section-level crosswalk cannot settle that; confirm the
  question's answer genuinely reaches no clause.

### Absence claims — 15 rows

Before accepting "no such requirement/limit/guidance/subpart", establish:

1. **Scope of search.** Which part or parts would carry the requirement if it
   existed. The packet searches the part the question names; satisfy yourself
   that is the right place to look.
2. **Wording.** The packet searched for the question's subject terms. A
   requirement worded differently would not surface — search the synonyms
   yourself before accepting.
3. **Adjacent instruments.** For "NO SUCH GUIDANCE", check the FDA guidance
   database directly; the packet does not establish guidance absence. For
   "NO SUCH SUBPART", check the part's subpart structure.
4. **The false-premise distinction.** Four rows say FALSE PREMISE and one says
   REPEALED PROVISION about provisions that *do* exist as reserved. Those are
   not absence claims; the judgment is whether the premise holds, not whether
   the section is there.
5. Record what you searched in the rationale. An absence accepted without a
   recorded search is the weakest link in the benchmark.

## 8. Reviewer consistency

Deliberately light. Four mechanisms, no statistics beyond counting.

1. **Calibration set of 20 rows**, drawn before the main run: 5 straightforward
   citation, 5 Part 820/ISO, 4 negative control, 3 temporal, 3 scope. The
   reviewer decides these first; a second reader reviews the same 20
   independently. Compare, discuss the disagreements, write the resolved
   criteria down, and only then start batch 2.
2. **Explicit criteria, written before volume.** The discussion above produces
   one page: what counts as paragraph-level, when completeness requires naming
   a cross-referenced recordkeeping section, what evidence suffices for
   absence.
3. **Mandatory rationales**, already enforced — a decision without one is
   refused. They are the audit trail and the consistency check.
4. **Periodic re-check.** After each batch, re-review 3 rows drawn from the
   previous batch without looking at the earlier decision. A changed decision
   is a signal to pause and re-read the criteria, not an error to hide.

No model adjudicates, overrides or scores a reviewer's decision.

## 9. Quality control

Assignment by objective characteristics present in the artifacts, not by a
judgment about which questions matter more — the project defines no such
ranking.

| Treatment | Rows | Objective trigger |
|---|---|---|
| **Second review** | 23 | ISO conflict: two sources disagree |
| **Second review** | 15 | absence claim: a negative is being asserted |
| **Second review** | 1 | X-004: automated contradiction |
| **Second review** | 11 | temporal/version rows: a wrong answer here is a citation failure by rule |
| **Second review** | any row decided CORRECTED | the key is being changed |
| **Escalation** | any row where the two reviewers disagree after discussion | unresolved conflict of authority |
| **Escalation** | any row the reviewer marks NEEDS_RESEARCH twice | cannot be settled with available sources |
| **Single review** | the remainder (~230) | no conflicting source, no absence assertion, no key change |

Second review is a genuine independent decision recorded by a second
reviewer, not a rubber stamp: the system records both, and the review history
keeps them.

## 10. Workload estimate

Planning figures, not a prediction. They assume the provision text is in the
packet — without that fix every line roughly doubles.

| Work | Rows | Per row | Total |
|---|---|---|---|
| Straightforward (F+G against text in the packet) | 221 | 4–8 min | 15–29 h |
| ISO conflicts (controlled standard consulted) | 23 | 10–20 min | 4–8 h |
| ISO where the crosswalk is silent | 16 | 8–15 min | 2–4 h |
| Absence claims | 15 | 10–20 min | 2.5–5 h |
| Citation declarations needing judgment | 24 | 5–12 min | 2–5 h |
| X-004 and escalations | ~5 | 20–40 min | 1.5–3.5 h |
| **First pass** | **300** | | **27–55 h** |
| Calibration (20 rows, two readers, discussion) | | | 3–5 h |
| Second reviews (~70 rows) | | 4–8 min | 5–9 h |
| **Total for one SME plus a second reader** | | | **35–69 h** |

Roughly **one to two working weeks** of SME time. The spread is wide on
purpose: it is dominated by how long the ISO consultations take and by how
many rows come back NEEDS_RESEARCH, neither of which is knowable in advance.

## 11. Engineering fixes made

Only what safe review required:

* provision text in packets, from the read-only snapshot, eCFR only;
* absence-search evidence for negative controls, with its caveat;
* `batch` export for offline review;
* six tests covering the above, including that ISO text can never appear.

No speculative architecture. The state machine, gate, versioning and audit
trail were already sufficient and were not touched.

## 12. State of the gates

| | |
|---|---|
| Benchmark hash | `c009d5f9c649…`, 76,773 bytes — **unchanged** |
| Locked keys on disk | **none** |
| SME decisions recorded | **0** |
| Sign-offs | **0** |
| Rows with an accepted expectation | **0 of 300** |
| Scoring | **BLOCKED** — no locked key for this benchmark version |
| Training | **BLOCKED** — `train_model.py` exits 3 |
| Baseline | frozen, 300 rows, sha `c009d5f9c649` |
| Test suite | 772 passed, 26 deselected |

The 300-question benchmark is **not verified**. This document prepares the
review; it does not perform it.
