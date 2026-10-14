# Measurement Audit Phase 2K: grammatical parsing for negation and qualifier detection (feasibility)

**Recommendation: NO SAFE OPTION YET. Leave production unchanged.**

- **No parser could be run here.** No part-of-speech tagger or dependency parser is installed or cached, and installing one was not authorised.
- **The best fallback still regresses a permanent test.** That fallback is JR: relative clauses on both sides, with determiner and adverb handling. It handles "that is not the subject" correctly, reads qualifiers far more precisely than JBQ or JBQP2, and keeps every control. But it turns the currently passing permanent test **RC6** (73.3110(c)(1), "levels exceeding" vs "do not exceed") into a **false support**. The same happens for a synonym inversion ("levels above"). Adopting it would change one of the seven tests' outcomes, which this phase may not do.

Investigation only: no production code, test, fixture, benchmark file, frozen answer or scoring rule changed (§9). No package was installed or model downloaded. No 300-question run.

## 1. Feasible parsing approaches and environment constraints

**Installed in `.venv`** (`pip list`, import checks): `transformers 5.17.0`, `torch 2.14.0`, `tokenizers 0.23.2`.
- **Not installed:** spaCy, NLTK, Stanza, Flair, TextBlob, benepar, SuPar, Trankit.
- **Cached models** (`~/.cache/huggingface/hub` and the project `models/`): only `BAAI/bge-small-en-v1.5` (an embedding model, which has no grammatical output) and `Qwen/Qwen3-0.6B` (a generative LLM), plus its LoRA adapter.
- **No token-classification, POS or parser model** is cached.

| Approach | Available now? | Licensing / distribution (verify at authorisation) | CPU runtime / memory (typical, not measured here) | Clause boundaries and negation role | "levels exceeding X" vs "packaging requirements" | Known failure modes on regulatory text |
|---|---|---|---|---|---|---|
| spaCy + `en_core_web_sm` | **no** (package and model download needed) | library MIT; the small English model is distributed under MIT (confirm the current model card) | fast (thousands of words/s), small model (~tens of MB) | dependency labels: `relcl` (relative clause), `acl` (participle modifier), `neg` attached to its head verb, `compound` | yes in principle: `exceeding` → `acl` of "levels"; "packaging" → `compound` of "requirements" | long sentences with enumerations "(1) … (2) …", coordinated relative clauses, PP attachment, passive and copular relatives ("that are not the subject"); errors grow with sentence length |
| Stanza (UD) | **no** | code Apache-2.0; models trained on UD treebanks (EWT is CC BY-SA 4.0) | heavier (torch, hundreds of MB), slower on CPU | full UD dependencies including `acl:relcl`, `advmod` neg | yes in principle | same as above; slower on 4,000+ character context sources |
| benepar (constituency) | **no** | MIT; needs spaCy + a parsing model | heavy | constituency SBAR/RRC boundaries, not negation attachment as such | via the NP/VP structure | long legal sentences; model size |
| NLTK perceptron POS tagger | **no** (data download needed) | Apache-2.0 | light | **POS only**: no clause boundaries, no negation scope | partly (VBG vs NN is unreliable for "packaging", "labeling", "testing") | gerund/noun ambiguity is exactly its weak point |
| UDPipe 2 | **no** | code MPL-2.0; many UD models **CC BY-NC-SA** (non-commercial), a likely blocker | light | UD dependencies | yes in principle | as above |
| Qwen3-0.6B as a tagger | cached | — | slow on CPU | — | — | **excluded:** a generative model making grammatical judgements breaks the standing "no LLM judge" constraint, and it is unverified as a tagger |
| BGE-small embeddings | cached | — | — | none | none | **excluded:** no grammatical output |
| **Restricted `that/which/who` fallback (JR)** | **yes (offline copy)** | — | measured: +4% per comparison | relative clauses only, by pattern | only when the claim also uses a relative pronoun | §3–§4 |

**Even a correct parse would not close every gap.** A parser can label "do not exceed" as a qualifier, but it cannot tell that "levels **above** 0.003 percent" (DX7) or "levels **exceeding**" contradicts it. That needs a **quantity-bound** comparison (≤ vs >), which is a semantic step, not a grammatical one.

## 2. Evaluation set and provenance

Three parts:
1. **The seven permanent tests (RC1–RC7)**, unchanged.
2. **The 15 Phase 2I real-text checks**, unchanged.
3. **A new Phase 2K diagnostic set** (`work/diagnostics.json`) of 11 decision items and 5 extraction probes. Evidence is **verbatim** eCFR text from the read-only snapshot (`work/real_texts_2k.json`: citation, snapshot 2026-09-03, `content_sha256`). Claims are **constructed** and labelled. Two extraction probe texts (EX2, EX3) are constructed and labelled; the others are verbatim sentences.

| ID | Category | Evidence (verbatim) | Constructed claim / probe | Expected |
|---|---|---|---|---|
| DX1 | correct claim, negated relative | 1141.1(b) "…do not apply to manufacturers or distributors of cigarettes that do not manufacture…" | "…do not apply to distributors of cigarettes that do not import…" | no conflict |
| DX2 | genuine negated rule | 1141.1(b) | "…**apply** to manufacturers of cigarettes that do not manufacture…" | conflict, not credited |
| DX3 | multi-sentence, genuine | 113.40(a)(6) "…A bottom crate support shall be used… Baffle plates shall not be used…" | "Baffle plates **shall be used**…" | conflict |
| DX4 | multi-sentence, unrelated negation | 113.40(a)(6) | "A bottom crate support shall be used in vertical still retorts." | no conflict |
| DX5 | passive negated duty | 1114.5 "…may not be introduced… until…" | "…may be introduced … before FDA issues…" | conflict |
| DX6 | multi-sentence, unrelated threshold | 1.379(a) (2 sentences) | restates the 2nd sentence (10 additional days) | no conflict |
| DX7 | threshold, synonym | 73.3110(c)(1) "levels that do not exceed 0.003 percent" | "levels **above** 0.003 percent" | conflict, not credited |
| DX8 | threshold, comparative | 1.379(a) "a period that may not exceed 20 calendar days" | "a period **longer than** 20 calendar days" | conflict, not credited |
| DX9 | "not the subject", inverted | 312.110(b)(3) "Drugs … that are not the subject of an IND are exempt…" | "…that **are** the subject of an IND are exempt…" | conflict, not credited |
| DX10 | "not the subject", faithful | 212.40(c)(1)(ii) | faithful restatement | no conflict |
| DX11 | "-ing" noun vs a related negated relative | 800.12(a) "…that is not packaged in a tamper-resistant package…" | "Tamper-evident packaging requirements apply to contact lens solutions…" | no conflict |
| EX1–EX5 | extraction probes | 211.137(a) "stability testing"; "good manufacturing"; "tamper-evident packaging"; 211.137(a) "To assure that a drug product…"; 312.110(b)(3) "that are not the subject" | — | no qualifier key from an "-ing" noun, a complement "that", or the determiner "the" |

## 3. Comparative claim-level results

Production = K0 (the identity copy reproduces production exactly). Results are at **claim level**: support basis, conflicts and final status, with a relevant question.

| Measure | Production | JBQ | JBQP2 | **JR** (restricted fallback) | JRC (conservative presence check) |
|---|---|---|---|---|---|
| Seven tests (`--runxfail`) | 4/7 (RC1–RC3 fail) | 6/7 (RC6 false support) | **7/7** | 6/7 (**RC6 false support**) | 6/7 (RC3 false support) |
| 15 real-text checks | 9 | 13 | 14 | 13 | 13 |
| Diagnostic decisions (11) | 7 | 8 | 8 | 8 | 7 |
| Extraction probes (5) | n/a | 4 (reads `the`) | **0** (reads `test`, `manufactur`, `packag`, `the`) | **5** | 5 |
| Genuine-contradiction (19) / reading (6) | 19 / 6 | 19 / 6 | 19 / 6 | 19 / 6 | 19 / 6 |
| Real-negation preservation (44) / invented-condition (18) | 44 / 18 | 44 / 18 | 44 / 18 | 44 / 18 | 44 / 18 |
| 33 relative-clause cases removed | 0 | 33 | 33 | 33 | 33 |
| Phase 2D tests (240) | pass | pass | pass | pass | **2 fail** (D-007 para17 safe support lost) |
| Claim / answer / score changes, 170 frozen row-runs | 0 | 0 | 0 | 0 | **2 claim** (D-007 s3, both aligners) |

**Per diagnostic item:**
- **Production:** false support on DX2 and DX9 (descriptive); false conflict on DX4 and DX6.
- **JBQ / JBQP2 / JR:** DX7 is a false support (paraphrase); DX2 is a missed contradiction, not credited; DX4 is a false conflict (polarity, from a semicolon / multi-sentence unit).
- **JR** handles DX9 through a `qualifier_polarity` conflict on "subject", and DX8 through a strength conflict.
- **JRC:** false support on DX2, DX7 and DX9.

## 4. False-support and false-contradiction analysis

**False supports and partials on real text** (seven tests + 15 checks + 11 diagnostics; one item, 73.3110 participle, appears in both the tests and the checks):

| Candidate | False credits | Items |
|---|--:|---|
| Production | 4 | RC2/T2b (partial), RC3/T2c, DX2, DX9 (all are must vs must-not hidden by a shared negated relative clause) |
| JBQ | 2 | RC6/T5a, DX7 |
| JBQP2 | 1 | DX7 |
| JR | 2 | RC6/T5a, DX7 (both 73.3110 threshold inversions without a relative pronoun) |
| JRC | 4 | RC3, DX2, DX7, DX9 |

**False contradictions or conflicts:**
- **Production:** 6 on these sets (RC1/T1a–c, T3c, DX4, DX6), plus all 33 frozen cases.
- **JBQ, JBQP2, JR:** 2 each (T3c and DX4: semicolon or multi-sentence units).

**JR: what it fixes and what it breaks.**
- **Fixes:** all of production's false credits, all of production's relative-clause false contradictions, and the "that is not the subject" case.
- **Introduces:** one false-credit class: a **threshold qualifier inverted without "that/which/who"** ("exceeding", "above"). Production catches that class only by accident, and RC6 is a permanent test of it.

**JBQP2** catches RC6 but reads qualifiers out of nouns. Its extraction precision is 0/5 on the probes, and on the 374,496-pair probe it raised 282 conflicts, many from misread keys (`the` 60, `manufactur` 42; Phase 2J). **JR raised 115**, with keys that are real clause verbs (require, include, result, conform). A few noun keys remain: `product`, `drug`, `name`.

**JRC**, which keeps production's reading whenever the other side mentions the qualifier word, is **unreliable**. It treats the two sides asymmetrically and loses D-007's correct support from 211.115(a).

## 5. Regression and frozen-row results

- Full re-runs of all 170 frozen row-runs (both aligners): **0** claim, answer or score changes for JBQ, JBQP2 and JR. JRC: 2 claim changes (D-007 s3, the support lost).
- F-007, F-009 and the 203 labelled Phase 2C/2D instances are intact for every candidate except JRC (para17).
- The full suite on unchanged production, with the strict xfails, is unchanged from Phase 2J: 1837 passed, 3 xfailed, 1 skipped. The candidates were run with `--runxfail` to expose the real test outcomes.

## 6. Runtime and memory (measured)

`OP.compare` over the 2,103 unique recorded comparisons, median of 3 runs:

| Candidate | ms per comparison |
|---|---|
| Production | 0.521 |
| JBQ | 0.536 |
| JR | 0.540 (+4%) |
| JRC | 0.546 |
| JBQP2 | 0.557 |

No candidate adds a model or memory. Parsers were **not measured**, because none is installed. A spaCy-small parse would typically cost about a millisecond per sentence or more, and context sources reach 4,800+ characters. Measure this at authorisation.

## 7. Recommendation: NO SAFE OPTION YET

- **PARSER FEASIBLE: not supportable.** No parser can be run in this environment without installation, which was not authorised. On paper, a dependency parse supplies the right distinctions (`relcl`/`acl`/`compound`/`neg`), but its accuracy on long regulatory text is unmeasured. It also would not resolve synonym or comparative threshold inversions (DX7, DX8), which need quantity-bound semantics.
- **RESTRICTED FALLBACK: not recommended.** JR meets the stated preconditions: its limitations are explicit, and "that is not the subject" is handled safely (DX9, EX5). But it **regresses RC6**, a currently passing permanent test, into a false support, and adopting it would mean changing that test's outcome. It also adds the synonym false support (DX7), on a numeric safety limit (a colour additive's maximum level).
- **Leave production unchanged.** Its known false credits remain, documented by the strict xfails RC2 and RC3, and by DX2 and DX9 here.

## 8. Exact limitations and proposed next phase

**Limitations:**
- The parser approaches are assessed **analytically only**. Licence and runtime notes are typical values to verify, not measurements.
- All claims in the decision sets are constructed edits of verbatim text. No real answer inverts a threshold qualifier.
- The frozen 33 cases rest on legacy-reconstructed evidence, and exact prompt evidence does not exist for them.
- Polarity is undefined for claims without a modal ("The requirements … apply …", DX2). That gap is pre-existing and separate.
- T3c and DX4 (a semicolon-joined or multi-sentence unit) are unaddressed by every candidate.

**Proposed Phase 2L** (two separate, narrowly scoped investigations; pick one):
1. **A quantity-bound operator**, offline. Compare the *direction* of bounds on the same quantity ("not exceed", "no more than", "at most", "up to" = upper bound vs "exceeding", "above", "more than", "longer than", "greater than" = beyond the bound). It is independent of clause structure. Then re-test **JR + bound operator** on RC1–RC7, the 15 checks and DX1–DX11; RC6, T5a, DX7 and DX8 are its targets. If it passes everything with zero frozen changes, it would be the first candidate to meet all criteria without a parser.
2. **Authorised parser evaluation**, offline. Install `spacy` and `en_core_web_sm` (or Stanza) in a **separate** environment, never production's. Measure tag and parse accuracy on the 33 cases, the 1,077-sentence corpus scan and the diagnostics, plus runtime on 4,800-character sources. Only then decide whether a parser dependency is justified.

## 9. Verification of no changes

| Item | Result |
|---|---|
| `src/`, `scripts/`, `tests/`, `web/` (305 files) | **identical** by SHA-256, start and end (`work/manifest_*.sha256`) |
| Seven tests and their expected outcomes; fixtures; benchmark questions/answers; frozen inputs; rubric and scoring | unchanged (`work/benchmark_manifest_*.sha256`) |
| Git status | identical, 63 lines (`work/git_status_*.txt`) |
| Packages / models | none installed or downloaded (read-only `pip list` and cache listing only) |
| Database | read-only connection, SELECT only |
| 300-question benchmark / production implementation | not run / not done |

## Artifacts (`work/`)

- **Data:** `real_texts_2k.json`, `diagnostics.json`.
- **Variants:** `make_variants_k.py` → `variants/{K0_identity, JBQ, JBQP2, JR, JRC}`.
- **Evaluation:**
  - `eval_diagnostics.py` → `diagnostics_*.json`;
  - `eval_real_controls.py` → `real_controls_*.json`;
  - `eval_controls_h.py` → `controls_result_*.json`;
  - `collect_h.py` / `diff_cf.py` → `h_cf_*.json`, `cf_diffs.json`;
  - `probe_and_time.py` → `probe_time_*.json`.
- **State:** `manifest_*.sha256`, `benchmark_manifest_*.sha256`, `git_status_*.txt`.
