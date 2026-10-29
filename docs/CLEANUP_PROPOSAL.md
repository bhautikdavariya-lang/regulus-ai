# Switch cleanup proposal: deleting the rejected switches

Status: **proposal only, nothing is deleted.** Written 29 Oct 2026 against `rc-2026-10-29` (bb7543b). All line numbers
refer to that commit. Do this after the 30 Oct results, and only once they are approved.

## 1. Scope

There are six switches that were measured, rejected and are off. None of them is in `DEFAULT` or in the full300c or
full300d bundles. `src/regulus/rag/switches.yaml` records them with status `rejected`.

| Switch | What it did | Why it was rejected (evidence) | Replaced by |
|---|---|---|---|
| CV1 | MiniCheck entailment checks each cited sentence; weak sentences go back to the model | 27 Oct: MiniCheck-RoBERTa offline on 106 scored answers, AUC 0.58. At threshold 0.2 it flags 36 of 51 PASS answers vs 38 of 47 PF/FAIL, because applied reasoning reads as "unsupported". It was not reused for FD1 (29 Oct). | FC2 / FD1 (targeted rule checks) |
| NAV1 | The model reads the subpart's table of contents and names the further sections the question needs | LEDGER 28 Oct 17:25: 6 of 60 missing provisions recovered; 66 sections added, 51 not in the key. v2 at 17:56: +17 complete, but 81 of 92 added sections not in the key, so it was held out. Third miss under the stop rule. | HQ1 (index-time questions), MS2 |
| NAV2 | NAV1's table of contents also lists the 15 closest sections outside the subpart | Same run as NAV1 v2 (81 of 92 additions not in the key); it cannot work without NAV1 | — |
| RR1 | Round-robin budget across the requested sections | LEDGER 28 Oct 16:10: it halved S-018's 111.210 list (PASS lost), and full300b was restarted without it | RR2 |
| MS3 | A section MS1 cannot fit whole brings its best paragraph family | LEDGER 28 Oct 16:10: it added an irrelevant 111.3 definition to S-013 (PASS lost), and full300b was restarted without it | PL1 (same mechanism, triggered by size) |
| XP1 | A provision in another part that the promoted provision cites | LEDGER 29 Oct 13:15: E1 (MS1 4 / 10,000 + XP1) lost F-020's key 117.405 (a PASS) and failed the no-loss gate. XP1 also brought 112.4 into F-020. | XC1 (other-part candidates only) |

**Why delete:** each of these is about 15-160 lines of dead code on the hot paths (`SectionPromoter.resolve`,
`reranked_companions`, `_answer_once`, `_per_section_order`). Each one makes those functions harder to read, and each
is one more way a stale run script can switch something on by accident. Switching one on today is silent: an unknown or
deleted code in `REGULUS_VALIDATOR_PRECISION` is ignored without a warning (see section 5.3).

**Why it is safe:** all six are off in `DEFAULT` and in every run since 28 Oct 16:05. Code behind a switch that is off
does not execute, so deleting it cannot change an answer. The verification in section 6 checks this, and does not
assume it.

## 2. Code paths that would go

### 2.1 CV1 (Chain-of-Verification with MiniCheck)

| File | Lines | What | Action |
|---|---|---|---|
| `src/regulus/rag/pipeline.py` | 447 | Comment `# CV1: ... ; FR1: facts-first prompts` | Reword to cover only FR1 (FR1_PROMPT stays: BN2 and RS2 use it) |
| `src/regulus/rag/pipeline.py` | 448-449 | `CV1_MIN_SUPPORT` (env `REGULUS_CV1_MIN_SUPPORT`), `_CV1_SENTENCE` | Delete |
| `src/regulus/rag/pipeline.py` | 861-883 | `RagPipeline.claim_support()` | Delete (its only callers are in `verify_claims`) |
| `src/regulus/rag/pipeline.py` | 885-926 | `RagPipeline.verify_claims()` | Delete |
| `src/regulus/rag/pipeline.py` | 2034-2038 | Call site in `_answer_once`; writes `generation_info["claim_verification"]` | Delete. No recorded run carries that field (checked across all of `cos50_20261027/*.jsonl`) |
| `src/regulus/rag/entailment.py` | whole file (88) | `EntailmentChecker`, `entailment_checker()`, MiniCheck model pin | Delete. Its only importer in the repository is `claim_support` |
| `src/regulus/rag/validator_switches.py` | 182-185 (docstring) | CV1 paragraph | Replace with one line: "CV1 (27 Oct) MiniCheck CoVe - measured AUC 0.58, removed <date>" |

Outside the repository:
- `~/regulus_eval_runs/cos50_20261027/tools/entail_eval.py` imports `regulus.rag.entailment` and stops working. It is an
  offline evaluation tool whose result is already recorded, so archive it or pin it to `rc-2026-10-29`.
- The Hugging Face cache holds `models--lytang--MiniCheck-RoBERTa-Large` (1.3 GB) and `models--lytang--MiniCheck-Flan-T5-Large`
  (2.9 GB, downloaded 27 Oct, never wired in). Deleting the code frees nothing on its own. Deleting these two caches
  would free 4.2 GB on a disk that is 90% full. That is the owner's call, and it is not part of this change.

Tests: none. No test exercises CV1 or `regulus.rag.entailment`.

### 2.2 NAV1 and NAV2 (table-of-contents navigation)

These two go together: NAV2 only feeds NAV1's table of contents.

| File | Lines | What | Action |
|---|---|---|---|
| `src/regulus/rag/section_promotion.py` | 226-228, 230-238 | `NAV1_MAX`, `NAV1_MAX_CHARS` (env `REGULUS_NAV1_MAX`, `REGULUS_NAV1_MAX_CHARS`), `NAV1_TOC_LIMIT`, `NAV1_SNIPPET`, `NAV2_LIMIT`, `NAV1_MAX_TOKENS`, `NAV1_SYSTEM` | Delete. **Keep line 229** (`AU2_MIN_SCORE`), which sits between them |
| `src/regulus/rag/section_promotion.py` | 779-821 | `SectionPromoter.navigate_subpart()` (NAV1, with the NAV2 hook at 799) | Delete |
| `src/regulus/rag/section_promotion.py` | 823-839 | `SectionPromoter.part_neighbours()` (NAV2) | Delete |
| `src/regulus/rag/section_promotion.py` | 2098-2101 | Call site in `resolve()`, note `"navigated: ..."` | Delete |
| `src/regulus/rag/pipeline.py` | 484-485 | `OC1_NOTES` contains `"navigated: "`; the comment names navigation | Remove the entry (with XP1's, see 2.6) |
| `src/regulus/rag/pipeline.py` | 1640 | Optional-section note prefixes include `"navigated: "` | Remove the entry |
| `scripts/key_recall_eval.py` | 54, 90, 126 | Comment names NAV1; **imports `NAV1_SYSTEM`** and passes it to `ReplayGenerator` | Drop `NAV1_SYSTEM` from the import and the tuple. Without this the harness fails to import |
| `src/regulus/rag/validator_switches.py` | 79-83 (docstring) | NAV2 and NAV1 paragraphs | Replace with one line each |

Tests (`tests/test_section_promotion.py`) that would go:
- Fixtures `_SubpartToc` (650-656) and `_Nav` (658-664); no other test uses them.
- `test_nav1_adds_the_subpart_sections_the_model_names_from_the_table_of_contents` (667)
- `test_nav1_none_adds_nothing` (677)
- `test_nav2_lists_closest_sections_of_the_part_outside_the_subpart` (698)
- `test_nav1_v2_reads_list_numbers_and_rejects_invented_sections` (709)
- `test_nav1_v2_shows_each_sections_opening_words` (718)
- **Edit, do not delete:** `test_the_key_recall_harness_asks_decomposition_instead_of_taking_it_for_the_answer`
  (874-887) imports `NAV1_SYSTEM`. Drop it from the import and from the tuple at 885.

### 2.3 RR1 (round-robin budget)

| File | Lines | What | Action |
|---|---|---|---|
| `src/regulus/rag/selection.py` | 361-369 | The `if _switch("RR1")` branch of `_per_section_order` | Delete |
| `src/regulus/rag/selection.py` | 354 | The RR2 comment explains RR2 by RR1's failure | Keep as history ("RR1, removed, halved S-018's list") |
| `src/regulus/rag/validator_switches.py` | 87-88 (docstring) | RR1 paragraph | One line. The RR2 paragraph (75-76) keeps its reference to it |

Tests (`tests/test_selection_binding_first.py`):
- `test_rr1_requested_sections_share_the_budget_round_robin` (101-117) would go.
- `test_rr2_the_first_section_keeps_its_list_and_the_companions_share` (line 133) removes `"RR1"` from the switch set.
  This becomes a no-op, so simplify it to `VS.VALIDATOR_PRECISION | {"RR2"}`.

### 2.4 MS3 (paragraph family when a section does not fit)

| File | Lines | What | Action |
|---|---|---|---|
| `src/regulus/rag/section_promotion.py` | 627-640 | The `elif precision_fix("MS3") and path:` branch of `reranked_companions` | Delete. The `if chars + n <= MS1_MAX_CHARS` branch above it stays as it is |
| `src/regulus/rag/validator_switches.py` | 92-93 (docstring) | MS3 paragraph | One line, pointing to PL1 |

Tests (`tests/test_section_promotion.py`):
- Fixture `_BigSectionRows` (631-635); only `test_ms3` uses it.
- `test_ms3_a_section_too_large_to_add_whole_brings_its_best_paragraph_family` (637-647)

Interaction to keep in mind: with PL1 on, a section of at most `PL1_WHOLE_CHARS` (2,500) that still does not fit the
remaining MS1 allowance falls through to MS3 today. Once MS3 is gone it is simply skipped, which is what happens with MS3
off. No behaviour change.

### 2.5 XP1 (cross-part citations)

| File | Lines | What | Action |
|---|---|---|---|
| `src/regulus/rag/section_promotion.py` | 322-327 | `_XREF_SQL_PATH` (only `cross_part_citations` uses it) | Delete. `_XREF_SQL` (310) stays: MS2 (679) and companions (1470) use it |
| `src/regulus/rag/section_promotion.py` | 750-777 | `SectionPromoter.cross_part_citations()` | Delete |
| `src/regulus/rag/section_promotion.py` | 2094-2097 | Call site in `resolve()`, note `"cross-part: ..."` | Delete |
| `src/regulus/rag/section_promotion.py` | 649-650 | The XC1 docstring contrasts XC1 with XP1 | Keep as history |
| `src/regulus/rag/pipeline.py` | 484-485, 1640 | `"cross-part: "` in `OC1_NOTES` and in the optional-section prefixes | Remove the entries (with NAV1's) |
| `src/regulus/rag/validator_switches.py` | 77-78 (docstring) | XP1 paragraph | One line |

Tests (`tests/test_section_promotion.py`):
- Fixture `_XrefRows` (683-689)
- `test_xp1_adds_the_other_part_provision_the_promoted_paragraph_cites` (691-695)

Outside the repository: `run_full300d.sh` (line 8, `E1=1`) and `run_e1_recall.sh` (line 11) append `XP1`. After the
deletion they would silently run without it (section 5.3). Both are records of runs already made, so leave them, but
never re-run them as they are.

### 2.6 Shared edits

- `src/regulus/rag/pipeline.py:485` becomes `OC1_NOTES = ("reranked: ", "absence retrieval: ")` (see 5.5 for the
  dead `"paragraph companions: "` prefix).
  Remove both prefixes in the same commit as the second of NAV1 and XP1 to go, or in one commit for all six.
- The same file, lines 1640-1641: remove `"navigated: "`, `"cross-part: "` and `"paragraph companions: "` from the
  prefixes.
- Recorded runs: `"navigated: "` appears only in `recall_nav1.jsonl` and `recall_budget_nav.jsonl`, and `"cross-part: "`
  only in `recall_e1_var.jsonl`. All three are retrieval-only key-recall records. No answer run carries either note, so
  `--replay-promotions` of any answer run is unaffected.
- `src/regulus/rag/switches.yaml`: set `code: false` on the six entries and keep them. The registry is the record of what
  was tried; `tests/test_switch_registry.py` then checks that no code reads them any more.

### 2.7 Size

| | src lines removed | test lines removed | files deleted |
|---|---|---|---|
| CV1 | about 75 + entailment.py (88) | 0 | 1 |
| NAV1 + NAV2 | about 75 (+3 harness edits) | about 60 (+1 test edited) | 0 |
| RR1 | 9 | 17 (+1 test simplified) | 0 |
| MS3 | 14 | 17 | 0 |
| XP1 | about 40 | 13 | 0 |
| **Total** | **about 300** | **about 107; 8 tests removed, 2 edited** | **1** |

## 3. Proposed order

1. One commit per switch, in this order: RR1, MS3, XP1, NAV1+NAV2 (with the shared `OC1_NOTES` edit), CV1 (with
   entailment.py). Each commit is independently revertible, and the order goes from smallest to largest.
2. After each commit, run the unit suite with the worktree's `PYTHONPATH`. The four known failures must stay exactly the
   same (`test_answer_length_policy` test_e x2, `test_answer_validation` truncation note,
   `test_accuracy_scope_extension`).
3. A final commit sets `code: false` in `switches.yaml` and shortens the docstring paragraphs.

## 4. Before promotion, not deletion: PC1 is two switches

`PC1` gates two unrelated features:
- `pipeline.py:2048` (27 Oct, 8f194d7) appends the uncited paragraphs of a validated one-section answer, verbatim.
- `section_promotion.py:2016` (28 Oct, a919b9b) is the model cascade: a confident cross-encoder skips the language-model picker.

PC1 is in the full300c bundle, so both were on together. The ledger's only PC1 note ("cascade decided 0 of 10",
pf49b 1-10) is about the cascade. The appender has no measurement of its own. If tomorrow's results promote the bundle,
PC1 promotes both features.

Proposal: keep `PC1` for the cascade, which is the newer and documented meaning in the ledger. Give the appender a new
code (for example `PC2`), and add `PC2` to the switch string of every run that had `PC1`, so the recorded runs keep
their meaning. This is a rename, not a deletion. It needs a byte-identity check on the full300c cache with
`PC1,PC2` vs the old `PC1` before it lands.

## 5. Other hygiene the registry found (not part of the deletion)

1. **FS1 is undocumented.** `regulus.rag.conversation._stem` reads `FS1` (suffix-rule stemming, 9af4e43, 27 Oct). It is
   off, not in `DEFAULT`, and has no paragraph in the `validator_switches` docstring. The registry now records it as
   `experimental`.
2. **Reused labels.** Each of these is the same text used for two different things:
   - `P1` is a 26 Oct switch (practice silence), and also a 20 Oct comment label in `pipeline.py` (the hard-ceiling gap
     notice).
   - `E1` is a 23 Oct switch, and also the LEDGER's 29 Oct "E1 / E1b" retrieval experiments.

   Neither one changes behaviour, but both mislead whoever reads them. Rename the comment and the experiment labels when
   next touched.
3. **Unknown switch codes are ignored silently.** `validator_switches.enabled()` checks membership only. A typo, or a
   deleted code in a run script, runs without a warning. Proposal: at import, warn on stderr about any code in
   `REGULUS_VALIDATOR_PRECISION` that `switches.yaml` does not list or lists with `code: false`. It must only warn, so a
   recorded run is never refused.
4. **Duplicate code in PL1 and XC1.** PL1 (`reranked_companions`, 611-622), XC1 (`_cross_part_companion`, 643-667) and MS3 each carry the same
   "top-level paragraph family" query. After MS3 goes, a `_paragraph_family(section, path) -> (label, chars)` helper
   would remove the remaining duplicate. This is a refactor for after 30 Oct (docs/STAGES.md).
5. **A dead note prefix.** c32bf5c added `"paragraph companions: "` to `OC1_NOTES` and to the optional-section prefixes
   (pipeline.py:485, 1641), but nothing writes that note: PL1's paragraph families go out under `"reranked: "`. Remove
   it with the NAV1/XP1 prefixes in 2.6.
6. **A second wave of rejected switches, not proposed now.** The registry also marks these as `rejected`:
   - With figures recorded: SA1 (+3 / -2, no net gain), FS2 (+6 / -6), LM1 and FR1 (+3 / -2, 30% slower),
     BN2 (+1 / -1, 75% slower), QX1 (recovered nothing).
   - With only the 27 Oct release note "measured and left off" and no figures: RS2, E2B, C3, AR1.
   - FU3 already has no code.

   FR1's prompt is shared with BN2 and RS2, and the key-recall harness still asks QX1, so these need more care than the
   six above. Confirm the thin evidence before proposing them.

## 6. Verification when it is done

- Unit suite: same four failures, plus the eight deleted tests gone.
- `python scripts/switch_report.py --check` reports the registry as consistent, with the six marked `code: false`.
- Optional, with approval because it loads no model but reads the database: `scripts/impact_run.py` replay-only on the
  cached full300d questions, using the full300d switch string, expecting byte-identical answers to full300d. None of
  the six was on in full300d, so any difference is a deletion bug.
