The ID lists are verified. One heuristic correction: COS-71.6-Q1 is a decline ("…not found in the available eCFR data") that my length filter misread as an assertion. Among the 74 questions with no required evidence, the corrected split is 34 withheld, 16 delivered declines and 24 delivered substantive answers.

The report follows.

Written for: you and your team, reviewing Step 2A before authorising Step 2B.

# Step 2A: Offline Failure Attribution, run `cosmetics100_20261020T124217Z`

**Scope.** This run used **Qwen3-0.6B on CPU, float32**. Nothing here measures the intended Qwen3-1.7B MLX model.

- **Evidence-stage findings** (corpus, retrieval, selection) come from code that never calls the language model. They probably apply unchanged to a 1.7B run of the same questions, but no such run exists to confirm it.
- **Generation and validator-trigger findings** are 0.6B observations.

**Method.**
- **Deterministic records:** for all 100 questions I joined the response files, the measurement records, the workbook, the bank's verified keys, the corpus snapshot, and an index of 32,398 database row keys found in saved artifacts.
- **My judgment:** I read every delivered answer and withheld draft against its key and the exact evidence text the model received. That judgment covers contradictions, omissions, draft classes and primary categories. It is my assessment as an AI, not an SME's, and no other model or LLM judge was used.
- **Workspace:** all scripts and outputs live in `/private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/ccb13d8a-5576-44ec-89de-8adef836ae63/scratchpad/s2a/`, outside the repo. `attribution_matrix.csv` there holds the full per-question notes.

---

## 1. Executive summary

**What the evidence establishes:**

1. **74 of 100 questions never had the required evidence in the model's prompt.**
   - 51: the required paragraphs never entered the retrieval candidate registry.
   - 3: they were retrieved, then dropped by the context budget.
   - 20: the key cites only the FD&C Act, and retrieval reads only CFR and guidance tables. 
   - Of the remaining 26, 17 had partial paragraph coverage and 9 had full coverage.
2. **The 51 misses are retrieval misses, not corpus gaps.** Corpus presence is established for 50 of them; only COS-80.37-Q1 is unknown.
3. **Selection lost required evidence in only 4 questions.** Step 1's figure of "8 retrieved then dropped" was wrong: 5 of those drops were 70.3(u) or 70.3(f), while the key needed 70.3(v), which was never retrieved. So budget and ordering levers cannot reach the dominant failure. Candidate generation is the bottleneck.
4. **Part 73: 9 of the 10 colour-additive questions got prompts made up entirely of 21 CFR 1271.90 (HCT/P) rows.**
   - They came from the AND full-text leg, which returned 32 hits. That suppressed the OR fallback and RC1 section coverage.
   - No Part 73 row appeared in any of their registries.
5. **When evidence was present, the 0.6B model still failed in most cases.**
   - Of the 26 questions with some required evidence, 20 answers or drafts misstated, mis-cited or omitted something in that evidence, and 3 degenerated into loops.
   - 14 of those 20 were delivered to the user.
6. **Withheld drafts (44):** 1 correct, 5 partial, 27 incorrect (one of them a decline), 11 degenerate. Withholding was justified for 39, partly justified for 3, and unjustified for 2.
   - 7 withholdings rested only on mechanical triggers: "If applicable" sentences echoed from the prompt's own instruction, or numbers the user typed.
   - 4 of those 7 drafts were wrong anyway, so relaxing those triggers alone would have delivered 4 wrong answers.

**Primary cause distribution (one per question, totals 100):**

| Primary category | Count | Confidence |
|---|---|---|
| RETRIEVAL_MISS | 48 | 36 high, 12 medium |
| CORPUS_GAP | 20 | medium (statute text is not retrievable; whether guidance covers MoCRA is unverified) |
| MULTIPLE_CAUSES | 8 | 2 high, 6 medium |
| GENERATION_ERROR_WITH_EVIDENCE | 7 | 5 high, 2 medium |
| EVIDENCE_INCOMPLETE | 5 | 2 high, 3 medium |
| ANSWER_INCOMPLETE | 4 | 3 high, 1 medium |
| EVIDENCE_SELECTION_DROP | 3 | high |
| GENERATION_FAILURE | 2 | high |
| VALIDATOR_FALSE_POSITIVE_CANDIDATE | 1 | high |
| INSUFFICIENT_EVIDENCE_TO_ATTRIBUTE | 1 | low |
| Recorded PASS (no failure) | 1 | high |

**What remains unknown:**
- The actual retrieval query strings. They aren't recorded, so the matching mechanism, including Part 73, is probable but not confirmed.
- How the 1.7B model behaves on these questions.
- Whether 80.37 exists in the database, and whether some sub-paragraph rows exist (for example 701.13(g)(1), 700.25(d), 701.3(r)).
- SME confirmation of both the original labels and my assessments.

---

## 2. Artifact inventory

**Search scope:**
- Project root: `artifacts/`, `data/` (`raw/` and `processed/` are empty), `audit/results/`, `logs/`, `docs/`, `models/`.
- `~/regulus_eval_runs/`.
- `~/.cache/uv`, used only to load openpyxl.
- Not searched: the live database (prohibited) and any other locations.

| Artifact | Path | Contents | Linked to IDs | Limitations |
|---|---|---|---|---|
| Workbook | `artifacts/cosmetics_benchmark/<run>/Regulus_…_124538.xlsx` | Labels, rubric scores, scorer explanations, delivered answers, timing, tokens | Yes | AI-scored. Summary formulas have no stored values. |
| Response files | `<run>/responses/<ID>.json` (100 files) | **Candidate registry** (citation, tier, method, score); selected and dropped evidence with reasons; **prompt evidence text** (≤1,200 characters per item); validator codes; generation stats; timings | Yes (filename) | Initial validator findings are stripped of their sentence and detail. |
| Measurement records | `<run>/ui_measurements/ui_20261020T124416Z_8270714b/measurement.jsonl` | **Raw model draft** (100/100); validator input and repair output (61/61 where repair ran); initial findings **with triggering sentence**; evidence snapshot with `prompt_verified`; top-8 ranking; model, config and code revision | Yes (via question text) | No full prompt text. Validator input is not exposed when no repair ran (40 questions). |
| Run summary | `<run>/results.jsonl` | One line per question | Yes | Summary only. |
| Scoring | `<run>/scoring/verdicts.json`, `batch_*.json`, `fabrication_review.json`, `cited_section_check.json` | Scorer rationale, fabrication review, DB check of 31 cited sections | Yes | AI-scored. |
| Run fingerprint | `<run>/run_log.jsonl`, `server_config_*.json` | sha256 of 228 files at run start and finish; model availability | Run-level | — |
| Reference key | `Regulus_QBank_Cosmetics_REV01.xlsx` | Verified key and key answer elements | Yes | "Key Verified = Y" on all 277 rows, but the reviewer is not identified. |
| **Corpus snapshot** | `data/evaluation/semantic/semantic_expanded_v1/generated/corpus.jsonl` | 28,882 items; eCFR snapshot 2026-09-03; **whole Parts 70, 73, 74, 82** plus drug and device parts | — | **No Parts 71, 80, 81, 700–740 or 1271.** |
| Saved row keys | Index built from: this run; other saved runs (`artifacts/`, `data/ui_measurements/`, `data/evaluation/results/`, `audit/results/`, `~/regulus_eval_runs/`); training datasets | 32,398 keys covering 6,903 sections | — | Proves a row existed; absence proves nothing. The training manifests record the **same database snapshot** (2026-09-03, 7,906 sections, read-only). |
| Code | `src/`, `scripts/` | Used to read mechanisms | — | The code on disk is byte-identical to the code that ran (fingerprint match). |

**Not found anywhere:**
- Retrieval query strings, and per-leg candidate lists before they were merged.
- The text of unselected candidates.
- The full prompt text: only the hash of the sources block and the system-prompt hash are kept.
- Trigram similarity values for filtered items.
- A database export of the section list.
- Any 1.7B run of this question set.
- SME review.

---

## 3. Complete attribution matrix (all 100)

**How each column maps to your Phase B fields:**
- **Ans:** D = delivered, W = withheld (field 3, and field 12 when W).
- **Ret/Prompt/¶:**
  - First part: is an expected section in the registry (field 4)?
  - Second part: is it in the prompt (field 5)?
  - Third part: are the required paragraphs present in full, in part, or not at all (field 6)?
  - "statute" means the key cites only the FD&C Act.
- **Corpus:** the weakest presence evidence among the expected sections.
  - `snap` = in the corpus snapshot.
  - `run` = row seen in this run's registries.
  - `other` = row seen only in other saved runs.
  - `train` = row seen only in training data built from the same snapshot.
  - `?` = no evidence.
- **Req. drop:** a required row dropped by selection, shown as row@rank and reason (field 7).
- **Irrel:** irrelevant or misleading evidence dominated the prompt, by my judgment (field 8).
- **Con/Om/Cit:** the answer or draft contradicts or misreads the evidence / omits a key element / has an unsupported or mis-mapped citation (fields 9–11). "–" means no relevant evidence existed to contradict.
- **Validator:** the initial error findings (field 13). 
  - Suffixes: `*` = fired on an "If applicable" sentence; `(q)` = the figure came from the user's question; `→rep.` = delivered after repair.
  - Codes: UC unsupported_claim, IC invented_condition, CNC condition_not_in_cited_source, UF unsupported_figure, DEG degenerate_output, TR truncated, ECHO prompt_echo, RWE refusal_with_evidence, PCM provision_citation_mismatch, INV invalid_citation, ENUM enumeration_incomplete, UP unsupported_premise.
- **Categories:** RM retrieval miss, CG corpus gap, ESD evidence selection drop, EI evidence incomplete, GE generation error with evidence, AI answer incomplete, CE citation error, VFP validator false-positive candidate, VCR validator correct rejection, GF generation failure, MC multiple causes, IE insufficient evidence to attribute.
- **Conf:** H high, M medium, L low.

**How the primary category was chosen:**
- **Earliest sufficient stage:** the earliest stage whose failure alone rules out a correct answer, in the order corpus → retrieval → selection → paragraph completeness → generation → validator.
- **Multiple causes:** MC when two independent causes would each be sufficient.
- **Correct rejections:** VCR is always secondary, because a correct rejection doesn't cause a failure.
- **Confidence levels:**
  - High = deterministic record plus an unambiguous reading.
  - Medium = depends on presence evidence from other runs or training data, paragraph-level inference, or a judgment on a partial draft.

| # | ID | Label | Ans | Ret/Prompt/¶ | Corpus | Req. drop | Irrel | Con/Om/Cit | Validator (initial errors) | Primary | Secondary | Conf | Evidence (short) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | COS-70.3-Q1 | PF | D | all/all/part | snap | — | N | Y/Y/N | — | GE | EI,AI | M | 70.3(f) in prompt (truncated 1200/2174 chars, core definition visible); (g) absent. Answer opens with a decline, recasts the (f) container clause as a requirement, never… |
| 2 | COS-70.3-Q3 | PF | D | all/all/full | snap | — | N | N/Y/N | — | AI | — | H | 70.3(s),(u),(v) all in prompt. Answer omits eyebrow/skin below it (present in (s)) and reduces (u) to 'caution label'. |
| 3 | COS-70.19-Q2 | FAIL | W | all/all/part | snap | — | Y | –/Y/N | DEG,TR,ECHO | MC | GF,EI,VCR | H | Draft is a prompt-echo loop ('SOURCE n [1] The available…'), repetition stop at 64 tokens. Only 70.19(j) of (i),(j),(p)-(r) in prompt; 88% off-domain chars. |
| 4 | COS-70.50-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UF(q),IC* | RM | VCR | H | 70.50 in corpus snapshot, absent from registry. Draft describes SEND study-data packaging from a guidance. Triggers: '721' (from the question) and an 'If applicable'… |
| 5 | COS-70.50-Q2 | PF | D | all/all/full | snap | — | N | Y/Y/Y | PCM →rep. | GE | CE | H | 70.50(a)-(c) all in prompt (EXACT_CFR). Model misstates (a) and its (b) sentence was cited to [1]=(a) (provision_citation_mismatch); repair appended verbatim (a)-(c), so… |
| 6 | COS-70.51-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/Y | TR →rep. | RM | GF | H | 70.51 in snapshot, not in registry; prompt 100% off-domain (dispute-resolution guidance, 14.100). Answer restates drug FDR guidance; truncated at 384/384 with repeats. |
| 7 | COS-70.55-Q1 | FAIL | W | some/none/none | snap | 70.55@11 budget | Y | –/Y/Y | UC | ESD | RM,VCR | H | 70.55 retrieved at registry rank 11, dropped soft_budget; 70.19(n) not retrieved. Draft says the firm can petition, never says FDA may run studies. Trigger… |
| 8 | COS-71.1-Q2 | FAIL | D | none/none/none | other | — | Y | –/Y/Y | IC* →rep. | RM | — | M | 71.1 not in registry; section exists per other saved runs, 71.1(c) row not independently confirmed. Prompt 100% off-domain; answer lists food/feed additive petition… |
| 9 | COS-71.6-Q1 | FAIL | D | none/none/none | run | — | Y | –/Y/N | — | RM | — | H | 71.6(a) row exists (this run's registries); not retrieved for this question. Answer declines and states the provision 'is not found in the available eCFR data' -… |
| 10 | COS-71.15-Q2 | PF | D | all/none/none | run | 71.15(b)(2)@11 budget; 71.15(b)(3)@12 budget | Y | –/Y/Y | INV,IC* →rep. | ESD | RM,CE | H | 71.15(b)(2),(b)(3) retrieved at ranks 11-12, dropped soft_budget; (b)(1),(c) not retrieved. Prompt: 2 guidance + 101.9(g)(10)(v)(C). Conclusion directionally right but… |
| 11 | COS-71.25-Q1 | FAIL | W | none/none/none | train | — | Y | –/Y/N | ECHO | RM | GF,VCR | M | 71.25 not in registry; row ecfr:71.25:(a) exists only in training data built from the same 2026-09-03 snapshot (medium). Draft echoes 'SOURCE 1 : …' blocks of 505(q)… |
| 12 | COS-71.26-Q1 | FAIL | D | none/none/none | run | — | Y | –/Y/Y | IC →rep. | RM | — | H | 71.26 row exists (this run's registries), not retrieved. Prompt: 80.35(a), 81.30(b)(2) and 2 guidance - none on exemption cancellation. Answer talks about mixture… |
| 13 | COS-71.27-Q1 | FAIL | D | none/none/none | run | — | Y | –/Y/N | — | RM | — | H | 71.27 exists (this run's registries), not retrieved; AND full-text returned 80.35 and 73.1 rows. Model declined - appropriate to the evidence it had. |
| 14 | COS-73.2085-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC | RM | VCR | H | 73.2085 in snapshot, not retrieved; all 8 prompt rows are 1271.90 (supporting, AND full_text). Draft applies HCT/P labeling to a face cream; unsupported_claim (12%… |
| 15 | COS-73.2095-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC,CNC* | RM | VCR | H | Same 1271.90 pattern. Draft says beta-carotene must be labeled as an HCT/P. unsupported_claim true positive; co-trigger condition_not_in_cited_source is an 'If… |
| 16 | COS-73.2180-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | — | RM | — | H | 73.2180 in snapshot, not retrieved. AND leg returned 0 so the OR fallback ran (Prussian Blue NDA guidance, EMC guidance, Part 347). Model declined. |
| 17 | COS-73.2250-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC,IC | RM | VCR | H | 1271.90 pattern. Draft: foundation 'must be labeled as an HCT/P'. unsupported_claim + invented_condition ('as appropriate') both fire on wrong content. |
| 18 | COS-73.2298-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC,IC* | RM | VCR | H | 1271.90 pattern. Draft applies HCT/P labeling to an eyeliner. |
| 19 | COS-73.2575-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | DEG,TR | RM | GF,VCR | H | 1271.90 pattern. Draft repeats an HCT/P sentence 3x; repetition stop at 336/384. |
| 20 | COS-73.2645-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC | RM | VCR | H | 1271.90 pattern. Draft: aluminum powder eyeliner labeled as HCT/P; unsupported_claim true positive. |
| 21 | COS-73.2646-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC | RM | VCR | H | 1271.90 pattern. Draft labels a bronze eye shadow as an HCT/P; unsupported_claim true positive. |
| 22 | COS-73.2647-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UC,CNC*,UC* | RM | VCR | H | 1271.90 pattern. unsupported_claim true positive; co-trigger is the 'If applicable … devices or persons' echo. |
| 23 | COS-73.2725-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/Y | — | RM | — | H | 1271.90 pattern, delivered (validator 'valid'): HCT/P labeling and donor testing stated for an eye shadow. The validator passed it because the sentences overlap the… |
| 24 | COS-74.2052-Q1 | FAIL | W | all/all/part | snap | — | N | N/Y/Y | CNC* | MC | VFP,CE,EI | M | 74.2052(c) in prompt, (e) absent. Draft gives the (c) use list verbatim (mascara, lipstick, GMP amounts) but never says hair gel is excluded, mis-cites [4]=720.4 as… |
| 25 | COS-74.2203-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | — | RM | — | H | 74.2203 and 70.5(a) in snapshot, neither retrieved. Model declined. |
| 26 | COS-74.2208-Q1 | FAIL | D | some/none/none | snap | — | Y | –/Y/Y | INV →rep. | RM | CE | H | 74.2208 not retrieved; required 70.3(v) not retrieved (registry held 70.3(u), dropped soft_budget - not a required paragraph). Answer invents a 520(e) physician… |
| 27 | COS-74.2254-Q1 | FAIL | W | some/none/none | snap | — | Y | –/Y/Y | UC | RM | VCR | H | 74.2254 and 70.3(v) not retrieved (70.3(u),(f) dropped - not required). Draft calls the color a flavoring and says no certification is needed; unsupported_claim true… |
| 28 | COS-74.2304-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | — | RM | — | H | 74.2304 and 70.3(v) not retrieved; prompt held 74.2052(c) (a different color) and 720.4. Model declined. |
| 29 | COS-74.2317-Q1 | FAIL | W | some/none/none | snap | — | Y | –/Y/Y | UF(q),UC | RM | VCR | H | 74.2317 and 70.3(v) not retrieved. Draft: 'does not require FDA certification' (wrong). unsupported_figure '17' comes from the question (FP); unsupported_claim fires on… |
| 30 | COS-74.2322-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | — | RM | — | H | 74.2322 and 70.5(a) not retrieved; model declined. |
| 31 | COS-74.2327-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | — | RM | — | H | 74.2327 and 70.5(a) not retrieved; model declined citing 74.2052(c). |
| 32 | COS-74.2340-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UF(q),IC* | RM | VCR | H | 74.2340 not retrieved. Draft says the calcium-lake eye shadow is permitted (key: not permitted). Both error findings are mechanical ('40' from the question; 'If… |
| 33 | COS-74.2602a-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/Y | — | RM | CE | H | 74.2602a and 70.3(v) not retrieved. Answer says 'does not require FDA certification … non-certificate color' (wrong), cited to 81.30(i); validator raised nothing. |
| 34 | COS-74.2708-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/Y | IC* →rep. | RM | CE | H | 74.2708 not retrieved. Answer (after repair removed two 'If applicable' sentences) invents a 520(e) physician restriction and supply-chain duties. |
| 35 | COS-74.2710-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | — | RM | — | H | 74.2710 and 70.5(a) not retrieved; model declined. |
| 36 | COS-74.2711-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | UF(q),UC | RM | VCR,CE | H | 74.2711 not retrieved. Draft conclusions (allowed; no numeric limit; certification required) happen to match the key but are cited to animal-food guidance, 720.4 and… |
| 37 | COS-80.10-Q1 | FAIL | W | all/all/part | run | — | N | Y/Y/N | UF(q) | MC | EI,VFP,GE | M | 80.10(a) in prompt; (c),(d) absent; (b) row ends 'shall be:' (its (b)(1)-(3) schedule rows exist but were not supplied). Draft states $0.45/lb, $288 minimum correctly… |
| 38 | COS-80.31-Q1 | PF | D | all/all/part | run | — | N | N/Y/N | — | EI | — | H | Only 80.31(a)(3) in prompt; (a),(a)(1),(a)(2) rows exist (this run) but were never retrieved; 80.31(b) (not required) dropped soft_budget. Answer omits exactly the two… |
| 39 | COS-80.37-Q1 | FAIL | D | none/none/none | ? | — | Y | –/Y/Y | INV,IC* →rep. | IE | — | L | 80.37 not retrieved and absent from every saved artifact; Part 80 is outside the corpus snapshot, so RETRIEVAL_MISS vs CORPUS_GAP cannot be settled offline. Answer… |
| 40 | COS-80.38-Q1 | FAIL | D | none/none/none | run | — | Y | –/Y/N | — | RM | — | H | 80.38(a),(b) rows exist (this run's registries), not retrieved; model declined. |
| 41 | COS-81.30-Q1 | FAIL | D | none/none/none | run | — | Y | –/Y/N | — | RM | — | M | 81.30 exists (this run's registries) but the (r) row is not independently confirmed; not retrieved. Model declined citing the lead guidance. |
| 42 | COS-82.6-Q1 | FAIL | D | all/all/part | snap | — | N | Y/Y/Y | INV →rep. | MC | GE,EI,CE | M | 82.6(a) lead-in and (a)(3) (sodium benzoate <=0.1% exception) in prompt; (a)(1),(a)(2) absent. Answer ignores (a)(3), describes food label color declaration from… |
| 43 | COS-82.50-Q1 | FAIL | W | none/none/none | snap | — | N | –/Y/N | DEG*,TR,IC*,UP* | RM | GF,VCR | H | 82.50 in snapshot, not retrieved (82.1050, 82.2050, 82.6(a) were). Draft's opening paraphrases the analogous subpart text correctly, then loops 'If applicable, the batch… |
| 44 | COS-82.101-Q1 | PF | D | all/all/full | snap | — | N | Y/Y/Y | — | GE | CE,AI | H | EXACT_CFR: 24 Part 82 sections supplied incl. 82.101 and 82.50. Answer points to 82.1104 (D&C Blue No. 4) for FD&C Blue No. 1, says subpart B is 'drugs and cosmetics'… |
| 45 | COS-82.203-Q1 | FAIL | W | all/all/full | snap | — | N | Y/Y/Y | DEG*,TR,UF,IC* | GF | GE,VCR | H | 82.203, 82.5, 82.50 in prompt (24 exact sources). Draft opens with the wrong color (74.1206, D&C Green No. 6) and loops on 'If applicable … § 82.203' to the repetition… |
| 46 | COS-82.304-Q1 | FAIL | W | all/all/full | snap | — | N | N/N/Y | DEG,TR,PCM*,IC* | GF | VCR | H | 82.304 and 82.50 in prompt. First sentences are correct (externally applied restriction; 74.1304(a)(1),(b)) though one says 'D&C Red No. 4'; then loops on D&C Red No. 31… |
| 47 | COS-82.1104-Q1 | FAIL | D | some/none/none | snap | — | Y | –/Y/Y | — | RM | — | H | 82.1104 and 70.3(v) not retrieved (70.3(u), not required, was dropped). Answer describes label declaration and OTC lip-protectant text (347.50). |
| 48 | COS-82.1205-Q1 | FAIL | W | some/some/part | snap | — | N | N/Y/N | RWE | GE | EI,VCR | M | EXACT_CFR: the single supplied source is 82.1205's one sentence, which answers the question (no restriction or limit). Draft refuses. refusal_with_evidence is a true… |
| 49 | COS-82.1206-Q1 | FAIL | D | some/none/none | snap | — | Y | –/Y/Y | IC* →rep. | RM | — | H | 82.1206 and 70.3(v) not retrieved (70.3(u) dropped, not required). Answer: label-declaration rules plus 720.4(c)(6). |
| 50 | COS-82.1254-Q1 | FAIL | D | none/none/none | snap | — | Y | –/Y/N | IC* →rep. | RM | — | H | 82.1254 and 70.3(v) not retrieved. Answer: food/animal-food label declaration, then a decline. |
| 51 | COS-82.1307-Q1 | PF | D | all/all/full | snap | — | N | N/Y/Y | PCM,ENUM →rep. | AI | CE,GF | M | 82.1307(a),(b) in prompt among 24 exact sources. Answer reproduces (a),(b) correctly, then 1,418 tokens of Part 82 text with misattributed labels (repaired, then… |
| 52 | COS-82.1317-Q1 | FAIL | W | none/none/none | snap | — | Y | –/Y/Y | IC*,UC | RM | VCR | H | 82.1317 and 70.3(v) not retrieved. Draft: food label declaration; 'If applicable, the color additives must be registered with the FDA' is itself an invented requirement… |
| 53 | COS-82.1321-Q1 | FAIL | D | some/some/part | snap | — | N | Y/Y/N | — | GE | EI | H | Sole source is the 82.1321 identity sentence; answer says it 'restricts the use … in lipstick' - contradicts the evidence. Validator: valid (one warning). 82.1050 absent… |
| 54 | COS-82.1327-Q1 | PF | D | some/some/part | snap | — | N | Y/Y/N | — | GE | EI | H | Sole source is the 82.1327 identity sentence; first sentence correct, second invents a use limit attributed to 82.1327. Validator: valid. 82.1050 absent. |
| 55 | COS-82.2050-Q1 | FAIL | W | some/some/part | snap | — | N | Y/Y/Y | CNC,IC* | MC | EI,GE,VCR | M | 82.2050 (externally applied only) in prompt; 70.3(v) (lips not external) absent. Draft says it can go in a lipstick 'unless restricted' - ignores the restriction that… |
| 56 | COS-700.13-Q2 | PF | D | all/all/part | run | — | N | Y/Y/Y | IC* →rep. | EI | CE,GE | M | 700.13(a) in prompt; (d)(1),(d)(2) rows exist (saved runs) but not retrieved; 700.13(b) (not required) dropped soft_budget. Answer omits the (d) consequences (absent)… |
| 57 | COS-700.14-Q1 | FAIL | W | all/all/part | run | 700.14(a)@1 filtered | N | N/Y/N | DEG*,TR,IC*,UC* | MC | ESD,GF,VCR | H | Required 700.14(a) was registry rank 1 and dropped with reason 'filtered'; only (b) reached the prompt. Draft's first sentence is right but non-committal, then loops 'If… |
| 58 | COS-700.15-Q1 | FAIL | D | all/all/none | run | — | N | N/Y/Y | — | EI | — | H | Only the 700.15(a) background paragraph was supplied; (b) (deleterious, adulterated at any level) and (c) absent. Decline is defensible on that evidence; it cites an… |
| 59 | COS-700.18-Q1 | FAIL | W | all/all/full | run | — | N | N/N/N | IC*,UC* | VFP | — | H | 700.18(b) in prompt. Draft restates the adulteration rule and the processing-solvent residue exclusion (the key) almost verbatim, cited [3]=700.18(b). Both error… |
| 60 | COS-700.25-Q2 | FAIL | W | all/all/none | run | — | N | –/Y/Y | UC | EI | VCR | M | 700.25(a) in prompt, (d) (exemption procedure) absent and not seen in any saved artifact; 700.25(b) (not required) dropped soft_budget. Draft never addresses the… |
| 61 | COS-700.35-Q1 | FAIL | W | none/none/none | other | — | Y | –/Y/Y | UC,IC* | RM | VCR | M | 700.35(a),(b) rows seen only in other saved runs; not retrieved. Draft says the product 'must not be labeled with sunscreen' (key: qualify the term). unsupported_claim… |
| 62 | COS-701.3-Q1 | FAIL | D | all/none/none | run | 701.3(b)@11 budget | Y | –/Y/Y | — | ESD | RM | H | 701.3(b) (type size) retrieved at rank 11 and dropped soft_budget; (a),(f) not retrieved. Prompt 100% off-domain (tobacco ingredient guidance, tampon 801.430); answer… |
| 63 | COS-701.3-Q4 | PF | D | all/all/part | run | — | N | N/Y/Y | — | EI | AI,CE | M | 701.3(m) in prompt; (r) (direct-mail option, half the question) absent and not seen in saved artifacts; 701.3(n) (not required) dropped soft_budget. Answer paraphrases… |
| 64 | COS-701.9-Q1 | FAIL | D | none/none/none | other | — | Y | –/Y/Y | — | RM | — | M | 701.9(a)(2) row seen in other saved runs and training data; not retrieved. Answer asserts full consumer labeling using prescription-drug type sizes and food bulk rules. |
| 65 | COS-701.12-Q2 | FAIL | D | none/none/none | other | — | Y | –/Y/N | — | RM | — | M | 701.12 seen in other saved runs ((a) only; (d) row unconfirmed); not retrieved. Model declined citing food rule 101.5(d). |
| 66 | COS-701.13-G1 | FAIL | W | all/all/part | run | — | N | Y/Y/Y | UC | MC | VFP,GE,EI | M | 701.13(e)(1) in prompt; (e) PDP/alternate-PDP row not supplied. Draft gives the boudoir/compact tear-away-tag alternative (correct) but turns 'capacity of one-fourth… |
| 67 | COS-701.13-Q1 | PF | D | none/none/none | run | — | Y | –/Y/Y | IC*,IC →rep. | RM | — | H | 701.13 rows (a),(f) exist (this run's registries); none retrieved for this question. Answer: two generic sentences from the food rule 101.7(i). |
| 68 | COS-701.13-Q3 | PP | D | none/none/none | run | — | N | –/Y/Y | — | RM | CE | M | 701.13 exists but the (g)(1) row is not seen in any saved artifact; not retrieved. The answer's correct propellant rule was taken from the analogous food rule 101.7(g)… |
| 69 | COS-710.2-Q1 | PF | D | all/all/full | run | — | N | Y/Y/N | — | MC | GE,CG | M | 710.2 ('should register within 30 days') in prompt; answer adds 'This deadline is binding' - contradicts the 'should'. The binding 60-day deadline is in FD&C Act… |
| 70 | COS-710.4-Q1 | PP | D | some/some/part | other | — | N | N/Y/N | — | AI | EI | H | 710.4 in prompt including 'should be given separately for each establishment as defined in § 700.3(j)'; the answer drops that sentence. 700.3(j) definition absent… |
| 71 | COS-710.5-Q1 | PASS | D | all/all/full | run | — | N | N/N/N | — | PASS | — | H | EXACT_CFR; the single source 710.5 restated almost verbatim with correct citation. |
| 72 | COS-720.3-Q1 | FAIL | W | none/none/none | train | — | Y | –/Y/Y | UF(q),IC* | RM | VCR | M | 720.3 row seen only in training data (same snapshot); not retrieved. Draft describes drug Forms 3988/3989. Both error findings mechanical ('2512' from the question; 'if… |
| 73 | COS-720.4-Q3 | PF | D | all/all/part | run | — | N | Y/Y/Y | — | AI | EI,CE | H | 720.4(e) in prompt includes 'except for the hair coloring preparations … a statement for each shade'; the answer quotes (e) but drops that exception, implying the 12… |
| 74 | COS-720.7-Q1 | FAIL | W | none/none/none | train | — | Y | –/Y/Y | UF(q),IC*,UC | RM | VCR | M | 720.7 seen only in training data; not retrieved. Draft invents 'FSPCA Form 2-B…2-I'. Triggers: '2512' (question), 'If applicable', unsupported_claim (true). |
| 75 | COS-720.8-Q1 | FAIL | D | none/none/none | other | — | Y | –/Y/N | — | RM | — | M | 720.8 rows seen in other saved runs; not retrieved. Model declined. Prompt includes a malformed row label '21 CFR 171.1(i)(ii)(iii)(b)(iv)(v)(2)'. |
| 76 | COS-740.11-Q1 | FAIL | D | none/none/none | train | — | Y | –/Y/Y | — | RM | — | M | 740.11 rows seen only in training data; not retrieved. Answer lists cigarette health warnings for an aerosol dry shampoo; validator passed it. |
| 77 | COS-740.11-Q2 | PF | D | none/none/none | train | — | N | –/Y/Y | — | RM | CE | M | 740.11(b) not retrieved (training data only). Conclusion right via analogous OTC-drug 369.21 and animal-food 501.17(b)(1) rules, cited to those; exemptions omitted. |
| 78 | COS-740.12-Q1 | FAIL | D | all/all/part | run | — | N | Y/Y/Y | IC* →rep. | GE | EI | H | 740.12(a) and (c) in prompt; answer says the product must use 'hygiene' to avoid misbranding - the reverse of (c). (b) caution text absent (row exists, not retrieved). |
| 79 | COS-740.19-Q1 | FAIL | W | none/none/none | run | — | Y | –/Y/Y | UC | RM | VCR | H | 740.19 exists (it reached the prompt for COS-700.35-Q1) but was not retrieved here. Draft states SPF drug labeling tiers; unsupported_claim true positive. |
| 80 | COS-FDCA201(i)-Q1 | FAIL | W | statute | — | — | Y | –/Y/N | UC | CG | — | M | Statute key (201(i)); retrieval reads only CFR and guidance tables. Draft is essentially a decline ('answer is not found in the available regulatory sources'); the sole… |
| 81 | COS-FDCA601-Q3 | FAIL | D | statute | — | — | Y | –/Y/N | — | CG | — | M | Statute-only key (601(e)-(g)); model declined. |
| 82 | COS-FDCA603-Q1 | FAIL | D | statute | — | — | Y | –/Y/Y | — | CG | RM | M | Statute key (603). The implementing regulation 701.9(a) exists in the corpus (saved runs) and was not retrieved. Answer declines, then twice asserts 'drums need full… |
| 83 | COS-FDCA605-Q1 | FAIL | D | statute | — | — | Y | –/Y/Y | — | CG | — | M | Statute key (605, 604(5)). Answer describes drug postmarketing reporting (3500A, 60 days, Form 2252) as the brand owner's duty. |
| 84 | COS-FDCA605-Q3 | FAIL | W | statute | — | — | Y | –/Y/N | DEG,TR | CG | GF,VCR | M | Statute key (605(f)). Draft echoes the question then a decline, three times, to the repetition stop. |
| 85 | COS-FDCA606-Q2 | FAIL | D | statute | — | — | Y | –/Y/Y | IC* →rep. | CG | — | M | Statute key (606(b)). Answer presents food 'small business' employee-counting guidance as cosmetic GMP rules. Prompt row '21 CFR 1107.12(2)(ii)(2)(2)(2)(4)' has a… |
| 86 | COS-FDCA607-Q2 | FAIL | W | statute | — | — | N | –/Y/Y | UF(q) | CG | VCR | M | Statute key (607(c), MoCRA listing). Draft answers with the voluntary Form 2512 rule of 720.4(e) and contradicts itself on whether 12 shades need separate forms; no… |
| 87 | COS-FDCA607-Q3 | FAIL | W | statute | — | — | Y | –/Y/Y | UC,IC* | CG | VCR | M | Statute key (607(f)). Draft describes food-facility U.S.-agent registration rules. unsupported_claim true positive; 'If applicable' co-trigger. |
| 88 | COS-FDCA609-Q1 | FAIL | W | statute | — | — | Y | –/Y/Y | DEG,TR | CG | GF,VCR | M | Statute key (609(a)). Draft repeats 'The eCFR regulation requires … name and contact office address' to the repetition stop. |
| 89 | COS-FDCA609-Q2 | FAIL | D | statute | — | — | Y | –/Y/N | — | CG | — | M | Statute key (609(b),(c)); model declined. |
| 90 | COS-FDCA613-Q2 | FAIL | W | statute | — | — | Y | –/Y/Y | IC*,UC | CG | VCR | M | Statute key (613(b)). Draft states food facility registration and renewal rules. unsupported_claim fires on a meta sentence; 'If applicable' sentences also invented. |
| 91 | COS-FDCA614-Q2 | FAIL | W | statute | — | — | Y | –/Y/Y | CNC | CG | VCR | M | Statute key (614(b)). Draft's first sentence matches the key ('does not stop'), then contradicts itself using food preemption-exemption petitions (100.1). Trigger… |
| 92 | UC-COS-006 | FAIL | W | none/none/none | other | — | Y | –/Y/Y | UF(q),UC | RM | CG,VCR | H | Key's CFR core (211.1(a), 211.67, 211.68(a), 211.160(b)(4)) is in the corpus snapshot and was not retrieved; 613 statute absent from corpus. Draft says requirements are… |
| 93 | UC-COS-009 | FAIL | W | statute | — | — | Y | –/Y/Y | UC | CG | VCR | M | Statute-only key. Draft says the exposure 'could lead to … suspension of the facility's registration' (directionally consistent with 607) but is ungrounded (cited to a… |
| 94 | UC-COS-011 | FAIL | D | statute | — | — | Y | –/Y/N | — | CG | — | M | Statute-only key; model declined. |
| 95 | UC-COS-013 | FAIL | D | statute | — | — | Y | –/Y/Y | — | CG | CE | M | Key: no codified storage requirement (support is statute 601(c)/608). Answer imports the IVD reagent storage rule 809.10(a)(5) ('temperature, light, humidity') as an FDA… |
| 96 | UC-COS-015 | FAIL | W | statute | — | — | Y | –/Y/Y | UC,IC*,UC* | CG | VCR | M | Statute/no-rule key. Draft states tobacco NTSO, produce-safety record and animal-quarters rules as storage requirements. |
| 97 | UC-COS-016 | FAIL | W | statute | — | — | Y | –/Y/Y | DEG,TR | CG | GF,VCR | M | Statute key (604/605). Draft cites COVID face-mask guidance and loops 'If the rash is due to the product's use…' to the repetition stop. |
| 98 | UC-COS-017 | FAIL | W | statute | — | — | Y | –/Y/Y | DEG,TR | CG | GF,VCR | M | Statute key (604/605). Draft cites 600.14 biologic deviation reporting and loops on contract-manufacturer sentences. |
| 99 | UC-COS-020 | FAIL | D | statute | — | — | Y | –/Y/Y | — | CG | — | M | Statute/no-rule key. Answer states food-plant sanitation (110.80) and biologics contract-manufacturing guidance as cosmetic rework requirements. |
| 100 | UC-COS-021 | FAIL | D | statute | — | — | Y | –/Y/Y | — | CG | — | M | Statute key (610/611/607). Answer restates the question; cites food recordkeeping guidance and a device MDR definition. |

---

## 4. Withheld-draft assessment (all 44)

Every withheld draft was assessable: the raw draft, the exact prompt evidence and the validator's findings are saved for all 44. Each draft is classed separately from its FAIL label.

| Draft class | Count | Question IDs |
|---|---|---|
| Substantively correct | **1** | COS-700.18-Q1 |
| Partially correct | **5** | COS-74.2052-Q1, COS-80.10-Q1, COS-701.13-G1, COS-74.2711-Q1, UC-COS-009 |
| Incorrect or unsupported | **27** | 26 wrong answers, plus 1 decline (COS-FDCA201(i)-Q1) |
| Degenerate | **11** | Repetition loops or prompt echo |
| Indeterminate | **0** | — |

**Was withholding justified?** Yes for 39, partly for 3 (74.2052, 80.10 and 701.13-G1, where real errors existed but the trigger didn't catch them), and no for 2 (700.18; FDCA201(i), a decline swapped for another non-answer).

**Was the trigger itself a false positive?** Fully for 9, partly for 14 (some findings mechanical, others real), and no for 21.

| ID | Key evidence in prompt | Draft class | Validator errors | Trigger FP? | Other errors | Withhold justified | Basis (short) |
|---|---|---|---|---|---|---|---|
| COS-700.18-Q1 | all paragraphs | correct | IC*,UC* | Y | minor | N | 700.18(b) in prompt. Draft restates the adulteration rule and the processing-solvent residue exclusion (the key) almost verbatim, cited [3]=700.18(b). Both error… |
| COS-74.2052-Q1 | partial | partial | CNC* | Y | Y | partly | 74.2052(c) in prompt, (e) absent. Draft gives the (c) use list verbatim (mascara, lipstick, GMP amounts) but never says hair gel is excluded, mis-cites [4]=720.4 as… |
| COS-74.2711-Q1 | none | partial | UF(q),UC | partial | Y | Y | 74.2711 not retrieved. Draft conclusions (allowed; no numeric limit; certification required) happen to match the key but are cited to animal-food guidance, 720.4 and… |
| COS-80.10-Q1 | partial | partial | UF(q) | Y | Y | partly | 80.10(a) in prompt; (c),(d) absent; (b) row ends 'shall be:' (its (b)(1)-(3) schedule rows exist but were not supplied). Draft states $0.45/lb, $288 minimum correctly… |
| COS-701.13-G1 | partial | partial | UC | Y | Y | partly | 701.13(e)(1) in prompt; (e) PDP/alternate-PDP row not supplied. Draft gives the boudoir/compact tear-away-tag alternative (correct) but turns 'capacity of one-fourth… |
| UC-COS-009 | statute (none) | partial | UC | N | Y | Y | Statute-only key. Draft says the exposure 'could lead to … suspension of the facility's registration' (directionally consistent with 607) but is ungrounded (cited to a… |
| COS-70.50-Q1 | none | incorrect | UF(q),IC* | Y | Y | Y | 70.50 in corpus snapshot, absent from registry. Draft describes SEND study-data packaging from a guidance. Triggers: '721' (from the question) and an 'If applicable'… |
| COS-70.55-Q1 | none | incorrect | UC | partial | Y | Y | 70.55 retrieved at registry rank 11, dropped soft_budget; 70.19(n) not retrieved. Draft says the firm can petition, never says FDA may run studies. Trigger… |
| COS-73.2085-Q1 | none | incorrect | UC | N | Y | Y | 73.2085 in snapshot, not retrieved; all 8 prompt rows are 1271.90 (supporting, AND full_text). Draft applies HCT/P labeling to a face cream; unsupported_claim (12%… |
| COS-73.2095-Q1 | none | incorrect | UC,CNC* | partial | Y | Y | Same 1271.90 pattern. Draft says beta-carotene must be labeled as an HCT/P. unsupported_claim true positive; co-trigger condition_not_in_cited_source is an 'If… |
| COS-73.2250-Q1 | none | incorrect | UC,IC | N | Y | Y | 1271.90 pattern. Draft: foundation 'must be labeled as an HCT/P'. unsupported_claim + invented_condition ('as appropriate') both fire on wrong content. |
| COS-73.2298-Q1 | none | incorrect | UC,IC* | N | Y | Y | 1271.90 pattern. Draft applies HCT/P labeling to an eyeliner. |
| COS-73.2645-Q1 | none | incorrect | UC | N | Y | Y | 1271.90 pattern. Draft: aluminum powder eyeliner labeled as HCT/P; unsupported_claim true positive. |
| COS-73.2646-Q1 | none | incorrect | UC | N | Y | Y | 1271.90 pattern. Draft labels a bronze eye shadow as an HCT/P; unsupported_claim true positive. |
| COS-73.2647-Q1 | none | incorrect | UC,CNC*,UC* | partial | Y | Y | 1271.90 pattern. unsupported_claim true positive; co-trigger is the 'If applicable … devices or persons' echo. |
| COS-74.2254-Q1 | none | incorrect | UC | N | Y | Y | 74.2254 and 70.3(v) not retrieved (70.3(u),(f) dropped - not required). Draft calls the color a flavoring and says no certification is needed; unsupported_claim true… |
| COS-74.2317-Q1 | none | incorrect | UF(q),UC | partial | Y | Y | 74.2317 and 70.3(v) not retrieved. Draft: 'does not require FDA certification' (wrong). unsupported_figure '17' comes from the question (FP); unsupported_claim fires on… |
| COS-74.2340-Q1 | none | incorrect | UF(q),IC* | Y | Y | Y | 74.2340 not retrieved. Draft says the calcium-lake eye shadow is permitted (key: not permitted). Both error findings are mechanical ('40' from the question; 'If… |
| COS-82.1205-Q1 | partial | incorrect | RWE | N | Y | Y | EXACT_CFR: the single supplied source is 82.1205's one sentence, which answers the question (no restriction or limit). Draft refuses. refusal_with_evidence is a true… |
| COS-82.1317-Q1 | none | incorrect | IC*,UC | N | Y | Y | 82.1317 and 70.3(v) not retrieved. Draft: food label declaration; 'If applicable, the color additives must be registered with the FDA' is itself an invented requirement… |
| COS-82.2050-Q1 | partial | incorrect | CNC,IC* | partial | Y | Y | 82.2050 (externally applied only) in prompt; 70.3(v) (lips not external) absent. Draft says it can go in a lipstick 'unless restricted' - ignores the restriction that… |
| COS-700.25-Q2 | none | incorrect | UC | partial | Y | Y | 700.25(a) in prompt, (d) (exemption procedure) absent and not seen in any saved artifact; 700.25(b) (not required) dropped soft_budget. Draft never addresses the… |
| COS-700.35-Q1 | none | incorrect | UC,IC* | partial | Y | Y | 700.35(a),(b) rows seen only in other saved runs; not retrieved. Draft says the product 'must not be labeled with sunscreen' (key: qualify the term). unsupported_claim… |
| COS-720.3-Q1 | none | incorrect | UF(q),IC* | Y | Y | Y | 720.3 row seen only in training data (same snapshot); not retrieved. Draft describes drug Forms 3988/3989. Both error findings mechanical ('2512' from the question; 'if… |
| COS-720.7-Q1 | none | incorrect | UF(q),IC*,UC | partial | Y | Y | 720.7 seen only in training data; not retrieved. Draft invents 'FSPCA Form 2-B…2-I'. Triggers: '2512' (question), 'If applicable', unsupported_claim (true). |
| COS-740.19-Q1 | none | incorrect | UC | N | Y | Y | 740.19 exists (it reached the prompt for COS-700.35-Q1) but was not retrieved here. Draft states SPF drug labeling tiers; unsupported_claim true positive. |
| COS-FDCA201(i)-Q1 | statute (none) | incorrect (decline) | UC | Y | N | N | Statute key (201(i)); retrieval reads only CFR and guidance tables. Draft is essentially a decline ('answer is not found in the available regulatory sources'); the sole… |
| COS-FDCA607-Q2 | statute (none) | incorrect | UF(q) | Y | Y | Y | Statute key (607(c), MoCRA listing). Draft answers with the voluntary Form 2512 rule of 720.4(e) and contradicts itself on whether 12 shades need separate forms; no… |
| COS-FDCA607-Q3 | statute (none) | incorrect | UC,IC* | partial | Y | Y | Statute key (607(f)). Draft describes food-facility U.S.-agent registration rules. unsupported_claim true positive; 'If applicable' co-trigger. |
| COS-FDCA613-Q2 | statute (none) | incorrect | IC*,UC | partial | Y | Y | Statute key (613(b)). Draft states food facility registration and renewal rules. unsupported_claim fires on a meta sentence; 'If applicable' sentences also invented. |
| COS-FDCA614-Q2 | statute (none) | incorrect | CNC | partial | Y | Y | Statute key (614(b)). Draft's first sentence matches the key ('does not stop'), then contradicts itself using food preemption-exemption petitions (100.1). Trigger… |
| UC-COS-006 | none | incorrect | UF(q),UC | partial | Y | Y | Key's CFR core (211.1(a), 211.67, 211.68(a), 211.160(b)(4)) is in the corpus snapshot and was not retrieved; 613 statute absent from corpus. Draft says requirements are… |
| UC-COS-015 | statute (none) | incorrect | UC,IC*,UC* | partial | Y | Y | Statute/no-rule key. Draft states tobacco NTSO, produce-safety record and animal-quarters rules as storage requirements. |
| COS-70.19-Q2 | partial | degenerate | DEG,TR,ECHO | N | Y | Y | Draft is a prompt-echo loop ('SOURCE n [1] The available…'), repetition stop at 64 tokens. Only 70.19(j) of (i),(j),(p)-(r) in prompt; 88% off-domain chars. |
| COS-71.25-Q1 | none | degenerate | ECHO | N | Y | Y | 71.25 not in registry; row ecfr:71.25:(a) exists only in training data built from the same 2026-09-03 snapshot (medium). Draft echoes 'SOURCE 1 : …' blocks of 505(q)… |
| COS-73.2575-Q1 | none | degenerate | DEG,TR | N | Y | Y | 1271.90 pattern. Draft repeats an HCT/P sentence 3x; repetition stop at 336/384. |
| COS-82.50-Q1 | none | degenerate | DEG*,TR,IC*,UP* | N | Y | Y | 82.50 in snapshot, not retrieved (82.1050, 82.2050, 82.6(a) were). Draft's opening paraphrases the analogous subpart text correctly, then loops 'If applicable, the batch… |
| COS-82.203-Q1 | all paragraphs | degenerate | DEG*,TR,UF,IC* | N | Y | Y | 82.203, 82.5, 82.50 in prompt (24 exact sources). Draft opens with the wrong color (74.1206, D&C Green No. 6) and loops on 'If applicable … § 82.203' to the repetition… |
| COS-82.304-Q1 | all paragraphs | degenerate | DEG,TR,PCM*,IC* | N | Y | Y | 82.304 and 82.50 in prompt. First sentences are correct (externally applied restriction; 74.1304(a)(1),(b)) though one says 'D&C Red No. 4'; then loops on D&C Red No. 31… |
| COS-700.14-Q1 | partial | degenerate | DEG*,TR,IC*,UC* | N | Y | Y | Required 700.14(a) was registry rank 1 and dropped with reason 'filtered'; only (b) reached the prompt. Draft's first sentence is right but non-committal, then loops 'If… |
| COS-FDCA605-Q3 | statute (none) | degenerate | DEG,TR | N | Y | Y | Statute key (605(f)). Draft echoes the question then a decline, three times, to the repetition stop. |
| COS-FDCA609-Q1 | statute (none) | degenerate | DEG,TR | N | Y | Y | Statute key (609(a)). Draft repeats 'The eCFR regulation requires … name and contact office address' to the repetition stop. |
| UC-COS-016 | statute (none) | degenerate | DEG,TR | N | Y | Y | Statute key (604/605). Draft cites COVID face-mask guidance and loops 'If the rash is due to the product's use…' to the repetition stop. |
| UC-COS-017 | statute (none) | degenerate | DEG,TR | N | Y | Y | Statute key (604/605). Draft cites 600.14 biologic deviation reporting and loops on contract-manufacturer sentences. |

---

## 5. Systematic-pattern analysis

### 5.1 Part 73 questions dominated by Part 1271

**Observed:**
- **Affected:** 9 of the 10 Part 73 questions: 73.2085, 2095, 2250, 2298, 2575, 2645, 2646, 2647 and 2725, all Q1. All share one template: "We're developing a … and want to use [colour] as the colorant. May we, and what restrictions, certification or labeling apply?"
- **Registries:**
  - Each held 32 items, all with tier `supporting` and method `full_text`, from the AND full-text leg.
  - The 16 highest-scoring items were all 21 CFR 1271.90 rows, with scores from 8.41 to 11.94; the rest were HCT/P and food guidance chunks.
  - **No Part 73 row appeared in any of the nine registries**, although every target section is in the corpus snapshot.
- **Fallback suppressed:**
  - With 32 primary hits (the threshold is 3), the OR fallback and RC1 section coverage did not run: `fallback_used: false`, `section_coverage.run: false`.
  - Selection kept the top 8 and dropped 24 under `max_results`. All eight prompt items were 1271.90 rows.
- **Contrast:** COS-73.2180-Q1 has a different wording. Its AND leg returned 0, so the fallback ran. It still didn't retrieve 73.2180, and the model declined.

**Probable mechanism (medium confidence):**
- All eight 1271.90 prompt rows carry the recorded heading "Are there other exceptions and what labeling requirements apply?". That mirrors the template's "what … labeling apply?".
- The search vector weights the heading at A and the body at B ([src/regulus/retrieval/sql.py:104](src/regulus/retrieval/sql.py#L104)).
- In seven of the eight rows the text itself contains none of the question's terms. In the snapshot, the Part 73 target sections spread "restrictions", "labeling" and "certification" across separate paragraph rows, (b) through (d).

**Not established:** the query string. Which terms the AND query used, and how they matched, cannot be recovered offline.

**Effect:**
- 8 of the 9 drafts were withheld. In every one of the 8, the error findings included UC or IC on the HCT/P content: correct rejections.
- 1 was delivered: COS-73.2725-Q1, which applies HCT/P labeling to an eye shadow and was scored Fabricated = 1.

### 5.2 Missing expected CFR sections (80 CFR-keyed questions)

Assessed at the **required-paragraph** level:

| Status | Questions | Notes |
|---|---|---|
| Required paragraph never in the candidate registry | **51** | Includes 700.15-Q1 and 700.25-Q2, where a different paragraph of the same section was in the prompt |
| Retrieved, then dropped by selection; none in the prompt | **3** | 70.55-Q1 (rank 11), 71.15-Q2 (ranks 11–12), 701.3-Q1 (rank 11); all `soft_budget` |
| Section in the prompt but a required paragraph missing | **17** | Includes 700.14-Q1: its required (a) was the **rank-1** candidate, dropped by the trigram usefulness rule (similarity < 0.4, [pipeline.py:305-312](src/regulus/rag/pipeline.py#L305-L312)) |
| All required paragraphs in the prompt | **9** | — |
| Indeterminate | **0 at section level** | Paragraph-row existence is unconfirmed for several Part 700–740 rows (see §8) |

**Corpus presence for the 51 never retrieved**, using the weakest evidence among each question's sections:

| Evidence of presence | Questions | Confidence |
|---|---|---|
| In the corpus snapshot | 29 | High |
| Row seen in this run's own registries | 10 | High |
| Seen only in other saved runs | 6 | Medium |
| Seen only in training data built from the same snapshot | 5 | Medium |
| No evidence anywhere (COS-80.37-Q1) | 1 | Marked IE |

**Paragraph-incomplete cases:** many are parent/child splits. Examples:
- 80.10(b) ends "shall be:", and its (b)(1)–(3) fee rows were not supplied.
- 80.31: only (a)(3) was supplied, not (a)(1) or (a)(2).
- 700.13: (a) was supplied, but not (d)(1)–(2).
- 740.12: (a) and (c) were supplied, but not (b).

### 5.3 Validator withholding

**Two mechanical triggers:**
- **"If applicable" echo.** The prompt's answer-format instruction contains the phrase ([answer_plan.py:636](src/regulus/rag/answer_plan.py#L636)).
  - 33 of 100 raw drafts contain it.
  - It drove findings on 19 withheld drafts.
  - In 3 drafts it became the repetition loop itself: 82.50, 82.203 and 700.14.
- **Question-supplied figures.** `unsupported_figure` checks figures against the supplied sources only, not against the question.
  - 9 withheld drafts were flagged on the user's own numbers: "721", "17", "40", "11", "000" (from "2,000"), "2512", "12" and "30".

**Which triggers decided the outcome:**
- 24 withheld drafts carried at least one mechanical finding.
- In **7** the mechanical findings were the only ones:
  - correct draft: 700.18;
  - partial drafts: 74.2052 and 80.10;
  - incorrect drafts: 70.50-Q1, 74.2340, 720.3 and FDCA607-Q2.
- In the other 17, real error findings fired alongside the mechanical ones.

**Where the validator works and where it doesn't:**
- **True positives:** `unsupported_claim` fired on genuinely unsupported content in most incorrect drafts, including all five Part 73 HCT/P drafts it flagged. `degenerate_output` was correct 10 out of 10 times.
- **Misses:** it **passed** wrong content that overlapped the supplied text lexically:
  - 73.2725 (HCT/P labeling for an eye shadow), 740.11-Q1 (cigarette warnings), 74.2602a (says no certification is needed);
  - 82.1321 and 82.1327 (invented restriction and use limit);
  - 740.12 (inverted rule, delivered after repair).

**Recording quirk:** on withheld rows, the "final" validation status describes the replacement notice, not the draft ([pipeline.py:604-607](src/regulus/rag/pipeline.py#L604-L607)).

### 5.4 Errors despite evidence (26 questions with some required evidence)

In 20 of the 26, the answer or draft misused evidence it had. Another 3 degenerated (82.304, 700.14, 70.19). Three were correct for what they had: 710.5 (PASS), 700.18 (withheld) and 80.31 (limited by its evidence).

| Subtype | Count | IDs |
|---|---|---|
| Contradicts or misstates text in the prompt | 6 | 82.1321, 82.1327, 740.12 (inverts (c)), 710.2 ("binding" vs "should"), 70.50-Q2, 700.13-Q2 ("or" vs "as well as") |
| Wrong provision chosen among many | 2 | 82.101 (cites 82.1104), 82.203 (74.1206); both had 24 exact sources |
| Omits a condition, exception or element that was present | 5 | 720.4-Q3 (hair-dye exception, which flips the conclusion), 70.3-Q3, 710.4, 82.1307, 701.3-Q4 |
| Unsupported inference or misreading | 5 | 70.3-Q1, 82.2050, 701.13-G1, 82.6, 80.10 |
| False refusal | 1 | 82.1205 |
| Citation mapping only (content right) | 1 | 74.2052 (cites a paragraph that doesn't exist) |

- **Delivered to the user:** 14 of these 20; the other 6 were withheld.
- **Context flooding:** a question naming "Part 82" caused a part-level expansion to 24 exact sources. None of those 5 questions passed: 2 degenerated, 1 chose the wrong colour's section, 1 produced a 1,418-token dump, and 1 was withheld.

### 5.5 Latency and degenerate generation

- **Generation dominates response time:**
  - median 11.7 s, 90th percentile 23.7 s;
  - Pearson r = 0.971 between tokens generated and generation time;
  - decode speed median 12.6 tokens/s (CPU, float32).
- **Retrieval:** median 1.5 s, maximum 13.5 s. The slowest five were all fallback-mode questions.
- **Outlier: COS-82.1307-Q1** took 235.9 s.
  - It generated 1,418 tokens at 6.2 tokens/s from a 3,469-token prompt with 24 sources, under a token allowance of 1,696.
  - Its label is PARTIALLY FAIL with the core correct, so the latency outlier is not the cause of an accuracy failure.
- **Degenerate drafts: 11.**
  - 10 hit the repetition stop; 1 is a prompt echo without repetition (71.25).
  - 9 of the 11 were general searches; 2 of the 5 exact-CFR prompts with 24 sources degenerated.
  - Loop forms: "SOURCE n" block echo (2), "If applicable" (3), and repeated question or content sentences (6).

---

## 6. Impact summary

Every percentage below is out of 100 questions. **Categories overlap, so totals can exceed 100.**

**Primary or secondary role, counted per question:**

| Category | Questions |
|---|---|
| RETRIEVAL_MISS | 52 |
| VALIDATOR_CORRECT_REJECTION | 39 |
| CORPUS_GAP | 22 |
| EVIDENCE_INCOMPLETE | 18 |
| CITATION_ERROR (as a contributing cause) | 16 |
| GENERATION_ERROR_WITH_EVIDENCE | 14 |
| GENERATION_FAILURE | 13 |
| MULTIPLE_CAUSES | 8 |
| ANSWER_INCOMPLETE | 7 |
| EVIDENCE_SELECTION_DROP | 4 |
| VALIDATOR_FALSE_POSITIVE_CANDIDATE | 4 |
| INSUFFICIENT_EVIDENCE_TO_ATTRIBUTE | 1 |

**Requested metrics:**

| Metric | Count | Basis / IDs | Confidence |
|---|---|---|---|
| No required evidence reached the model | **74%** | 51 never retrieved, 3 dropped, 20 statute-only (§5.2) | High |
| Required paragraph never retrieved | **51%** | COS-70.50-Q1, 70.51, 71.1, 71.6, 71.25, 71.26, 71.27, 73.2085, 73.2095, 73.2180, 73.2250, 73.2298, 73.2575, 73.2645, 73.2646, 73.2647, 73.2725, 74.2203, 74.2208, 74.2254, 74.2304, 74.2317, 74.2322, 74.2327, 74.2340, 74.2602a, 74.2708, 74.2710, 74.2711, 80.37, 80.38, 81.30, 82.50, 82.1104, 82.1206, 82.1254, 82.1317, 700.15, 700.25-Q2, 700.35, 701.9, 701.12, 701.13-Q1, 701.13-Q3, 720.3, 720.7, 720.8, 740.11-Q1, 740.11-Q2, 740.19, UC-COS-006 | High (registry is deterministic) |
| Required evidence dropped by selection | **4%** | 70.55, 71.15, 701.3-Q1 (`soft_budget`); 700.14 (`filtered`) | High |
| Paragraph-level evidence incomplete | **17%** | 70.3-Q1, 70.19, 74.2052, 80.10, 80.31, 82.6, 82.1205, 82.1321, 82.1327, 82.2050, 700.13, 700.14, 701.3-Q4, 701.13-G1, 710.4, 720.4-Q3, 740.12 | High at row level |
| Statute-only key (FD&C Act not retrievable) | **20%**; 22% including the 2 mixed keys | FDCA201(i), 601-Q3, 603, 605-Q1, 605-Q3, 606, 607-Q2, 607-Q3, 609-Q1, 609-Q2, 613, 614; UC-COS-009, 011, 013, 015, 016, 017, 020, 021 (+ 710.2, UC-COS-006) | High that statute text is absent; medium that nothing in the corpus could answer |
| Some evidence present, but the answer or draft misused it | **20%** | §5.4 | Medium (my judgment) |
| Answer incomplete despite the evidence (AI role) | **7%** | 70.3-Q1, 70.3-Q3, 82.101, 82.1307, 701.3-Q4, 710.4, 720.4-Q3 | High/medium |
| Citation fault present in the answer or draft | **67%** | 54 of these had no required evidence in the prompt, so they cited whatever they were given; 13 had evidence | Medium |
| Delivered answers asserting requirements without support | **25 of 56 delivered** | 24 of them in the no-evidence group (4 of those 24 scored PF/PP because an analogous rule happened to match) | Medium |
| Delivered declines | **16** | 15 in the no-evidence group, plus 700.15 (incomplete evidence) | High |
| Irrelevant or misleading evidence dominated the prompt | **69%** | Irrel = Y column. The automated off-domain proxy agreed on only 66 of 100, so the manual flag is reported | Medium |
| Withheld: correct / partial / incorrect / degenerate / indeterminate | **1 / 5 / 27 / 11 / 0** | §4 | Medium |
| Withholding decided only by mechanical triggers | **7** (4 incorrect, 2 partial, 1 correct) | §5.3 | High for the trigger; medium for draft correctness |
| Part 73 → 1271.90 dominance | **9** | §5.1 | High (observed); medium (mechanism) |
| Degenerate drafts | **11** | §5.5 | High |
| Not reliably attributable | **1** | COS-80.37-Q1 | — |

---

## 7. Ranked investigative targets

| Rank | Target | Questions | Severity | Diagnostic confidence | Explains multiple failures? | Isolable | Regression risk of investigating |
|---|---|---|---|---|---|---|---|
| **1** | **Candidate generation for questions that name no section:** required provisions never enter the registry, including AND-leg gating such as Part 73 | 51 (+ 701.9 behind FDCA603) | High: all FAIL except 4 by analogy | High that rows are absent; medium–low on mechanism (no query strings) | Yes. It feeds the irrelevant-evidence prompts (69), most unsupported delivered answers (24) and 34 withholdings | Yes: retrieval only, no model | None if read-only |
| 2 | Statute corpus gap (MoCRA provisions) | 20 + 2 | High | High that the text is absent | Yes, all 22 | Yes: content or scope decision | None to investigate; a product decision follows |
| 3 | Paragraph-level incompleteness (sub-paragraph rows not fetched alongside their parent) | 17 | Medium | High at row level | Partially | Yes, within retrieval | Low to investigate; any change competes for the budget |
| 4 | Generation misuse of evidence that is present (0.6B) | 20 + 3 degenerate | High | Medium; possibly 0.6B-specific | Yes | **No.** Needs an authorised 1.7B experiment | Experiment needed |
| 5 | Validator mechanical triggers ("If applicable" echo, question figures) | 24 affected, 7 decided | Low for PASS: 1 correct and 2 partial drafts lost | High | Partly | Yes | **High if acted on alone:** 4 wrong drafts would be released |
| 6 | Validator misses on lexically overlapping wrong content | ≥6 delivered | High (fabricated requirements) | Medium | Partly | Yes | Downstream of target 1 |
| 7 | Selection drops (budget or trigram filter) | 4 | Medium | High | No | Yes | Low |

**Why target 1 comes first:**
- It affects the most questions, and the observation that the rows are absent is deterministic.
- Fixing it is a precondition for every downstream target: no generation or validator improvement can recover evidence the model never received.
- It can be investigated without model inference.
- It also explains why the earlier budget and ordering experiments were zero-sum. Only 4 of the 74 evidence-less questions lost their evidence to selection.

---

## 8. Unresolved questions

1. **Retrieval internals (needs an approved read-only retrieval replay):**
   - the actual tsquery and OR terms, and per-leg candidate lists;
   - why the AND leg matched 1271.90;
   - why the fallback terms missed colour names and section subjects;
   - where the required rows would have ranked.
2. **Corpus presence (needs an approved read-only corpus query):**
   - whether 80.37 exists;
   - whether these paragraph rows exist: 701.13(g)(1), 700.25(d), 701.3(r), 81.30(r), 701.12(d), 71.1(c), 700.15(c);
   - whether the guidance corpus contains MoCRA guidance that could answer the statute questions.
3. **Model-specific behaviour (needs an authorised model experiment):**
   - whether Qwen3-1.7B MLX shows the same contradictions, omissions, "If applicable" echo and repetition loops;
   - whether the 1.7B path uses the same retrieval and selection settings. The code reading suggests it does, but it is unverified.
4. **Labels and assessments (needs expert review):** both the original labels and my draft and answer assessments are AI judgments.
5. **Trigram value:** the similarity score behind 700.14(a)'s `filtered` drop is not recorded.

---

## 9. Repository integrity

| Item | Before | After |
|---|---|---|
| Branch / HEAD | main / `6f94938` | same |
| Staged files | 0 | 0 |
| Modified tracked files | 27 | 27 |
| Untracked entries | 29 (358 files when listed individually) | same |
| Stash | 0 | 0 |
| Tracked-change hash | `5833cb00…8440` | same |
| Content hash of all 358 modified/untracked files | — | identical |
| Project files changed in the last 4 hours | — | none |

**No differences, and nothing was reverted or cleaned.**

- **How I read the repo:** Git ran in a mode that doesn't take index locks. Python ran without writing cache files, with every script and output in the session scratchpad.
- **No live systems were touched:** no database queries, no model inference, no benchmark run, no services started.
- **Outside the repository:** scratchpad files, plus my memory notes in `~/.claude`.

---

## 10. Recommended next step

**Step 2B: a read-only, retrieval-only candidate-generation trace.**

**Hypothesis:**
- **H1:** When the AND full-text leg returns at least 3 rows (`primary_min = 3`), the OR fallback and RC1 section coverage are skipped. Heading-weighted matches in unrelated parts, such as 1271.90 for the Part 73 template, then fill the registry.
- **H2:** When the fallback does run, its 8 or fewer `fallback_terms` drop the terms that would identify the right provision (colour name, product, paragraph subject). So the OR and RC1 candidates come from the wrong parts.

**Scope:**
- **Questions:**
  - the 51 never-retrieved questions;
  - controls: the 9 with full evidence, and the 12 exact-CFR questions;
  - the 3 budget-drop cases.
- **Method:**
  - Run the existing retrieval code unchanged (plan → `LexicalRetriever.run_plan` → registry) from a harness outside the repo.
  - Use a read-only database transaction on the regulatory tables only.
  - Log the SQL text and parameters, per-leg row counts, per-leg top candidates, and whether the fallback and RC1 ran.
  - Add one diagnostic lookup per required row to see where it would rank in each leg.
  - Add the presence lookups listed in §8.
- **Exclusions:** no model, no evaluator, no code or configuration edits.
- **Authorisation:** this goes beyond Step 2A's limits, so it needs your explicit approval for database access and for executing project retrieval code.

**Success criteria:**
1. The replay reproduces all 100 recorded registries exactly: same citations, tiers, methods and score order. If it doesn't, stop and report.
2. For at least 90% of the 51, a recorded leg-level explanation of why the required row was not a candidate.
3. H1 and H2 each confirmed or refuted, with the query terms shown, including the Part 73 match terms.
4. Corpus presence settled for 80.37 and the unconfirmed paragraph rows.

**Regression safeguards:**
- No change to source, prompts, configuration, validators or dependencies.
- Read-only transaction; retrieval stage only; no model loaded.
- Harness and outputs kept outside the repository.
- The same Git integrity snapshot before and after.
- No finding accepted unless the determinism check (criterion 1) passes.
- Output is attribution only. Any fix proposal waits for your review.

Step 2A is complete. I've stopped here and am waiting for your approval. I can also publish this report as a private page you can share with the team.