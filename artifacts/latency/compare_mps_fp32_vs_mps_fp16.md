# Inference equivalence: mps_fp32_resume2_20260929T054005Z vs mps_fp16_20260929T050537Z

```json
{
 "compared": 60,
 "identical_in_every_field": 55,
 "questions_with_any_difference": 5,
 "differences_by_field": {
  "prompt_sha256": 0,
  "sources": 0,
  "answer": 5,
  "citations": 2,
  "validation_initial": 4,
  "validation_final": 4,
  "repair": 2,
  "coverage_action": 0,
  "citation_support": 3,
  "generated_tokens": 5,
  "prompt_tokens": 0,
  "model_called": 0
 },
 "only_in_a": [],
 "only_in_b": []
}
```

## S5-005 (single): What does § 211.132(a) say?

### answer
First divergence at character 31, after: `§ 211.132(a) requires that OTC `
- mps_fp32_resume2_20260929T054005Z: `drug products (except for specific categories) must be packaged in tamper-resist`
- mps_fp16_20260929T050537Z: `human drug products (except for specific categories) must be packaged in tamper-`

```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -1 +1 @@
-§ 211.132(a) requires that OTC drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section. If applicable, the requirement applies to devices or persons that are not properly labeled or packaged. [1]
+§ 211.132(a) requires that OTC human drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section. If applicable, the requirement applies to devices or persons that are not properly labeled or packaged. [1]
```

### validation_initial
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -25,3 +25,3 @@
    "requirement_id": "r1",
-   "sentence": "§ 211.132(a) requires that OTC drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section.",
+   "sentence": "§ 211.132(a) requires that OTC human drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section.",
    "severity": "warning"
```

### validation_final
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -25,3 +25,3 @@
    "requirement_id": "r1",
-   "sentence": "§ 211.132(a) requires that OTC drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section.",
+   "sentence": "§ 211.132(a) requires that OTC human drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section.",
    "severity": "warning"
```

### generated_tokens
- mps_fp32_resume2_20260929T054005Z: `60`
- mps_fp16_20260929T050537Z: `61`

## S5-010 (parent): What does 21 CFR 820.10(b) require manufacturers to comply with?

### answer
First divergence at character 191, after: `ance with the requirements of part 830 of this chapter [1]. `
- mps_fp32_resume2_20260929T054005Z: ` 
The manufacturer must document procedures for traceability in accordance with `
- mps_fp16_20260929T050537Z: `The manufacturer must document procedures for traceability in accordance with th`

```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -1,4 +1 @@
-21 CFR 820.10(b) requires manufacturers to document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1].  
-The manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [3].  
-The manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [4].  
-Advisory notices shall be handled in accordance with the requirements of part 806 of this chapter [5].
+21 CFR 820.10(b) requires manufacturers to document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1]. The manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [3]. The manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [4]. Advisory notices shall be handled in accordance with the requirements of part 806 of this chapter [5].
```

### generated_tokens
- mps_fp32_resume2_20260929T054005Z: `124`
- mps_fp16_20260929T050537Z: `119`

## S5-061 (general): What is a unique device identifier required to contain?

### answer
First divergence at character 0, after: ``
- mps_fp32_resume2_20260929T054005Z: `The generated answer could not be validated against the retrieved regulatory evi`
- mps_fp16_20260929T050537Z: `What is a unique device identifier required to contain? [1] A unique device iden`

```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -1 +1 @@
-The generated answer could not be validated against the retrieved regulatory evidence.
+What is a unique device identifier required to contain? [1] A unique device identifier is required to contain. [2] The exception for shipping containers is provided in [1]. [3] A device packaged within the immediate container of a combination product or convenience kit is subject to the requirement if the label of the combination product or convenience kit bears a UDI. [4] The requirement applies to devices packaged within the immediate container of a combination product or convenience kit.
```

### citations
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -1 +1,87 @@
-[]
+[
+ {
+  "citation": {
+   "center": null,
+   "corpus": "ecfr",
+   "docket_number": null,
+   "document_title": null,
+   "heading": "General exceptions from the requirement for the label of a device to bear a unique device identifier.",
+   "issued_on": null,
+   "label": "21 CFR 801.30(c)",
+   "paragraph": "(c)",
+   "part": "801",
+   "section": "801.30",
+   "status": null,
+   "title": "21",
+   "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-801/section-801.30"
+  },
+  "cited_in_answer": true,
+  "corpus": "ecfr",
+  "index": 1,
+  "indices": [
+   1
+  ],
+  "label": "21 CFR 801.30(c)",
+  "requirement_ids": [],
+  "role": "cited",
+  "tier": "supporting",
+  "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-801/section-801.30"
+ },
+ {
+  "citation": {
+   "center": "OTHER",
+   "corpus": "fda_guidance",
+   "docket_number": "FDA-2025-D-0176",
+   "document_title": "Unique Device Identifier Requirements for Combination Products: Draft Guidance for Industry",
+   "heading": null,
+   "issued_on": "2025-06-25",
+   "label": "FDA Guidance: Unique Device Identifier Requirements for Combination Products: Draft Guidance for Industry (draft, 2025-06-25, Docket FDA-2025-D-0176)",
+   "paragraph": null,
+   "part": null,
+   "section": null,
+   "status": "draft",
+   "title": null,
+   "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/unique-device-identifier-requirements-combination-products"
+  },
+  "cited_in_answer": true,
+  "corpus": "fda_guidance",
+  "index": 2,
+  "indices": [
+   2,
+   4
+  ],
+  "label": "FDA Guidance: Unique Device Identifier Requirements for Combination Products: Draft Guidance for Industry (draft, 2025-06-25, Docket FDA-2025-D-0176)",
+  "requirement_ids": [],
+  "role": "cited",
+  "tier": "supporting",
+  "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/unique-device-identifier-requirements-combination-products"
+ },
+ {
+  "citation": {
+   "center": null,
+   "corpus": "ecfr",
+   "docket_number": null,
+   "document_title": null,
+   "heading": "General exceptions from the requirement for the label of a device to bear a unique device identifier.",
+   "issued_on": null,
+   "label": "21 CFR 801.30(a)(11)",
+   "paragraph": "(a)(11)",
+   "part": "801",
+   "section": "801.30",
+   "status": null,
+   "title": "21",
+   "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-801/section-801.30"
+  },
+  "cited_in_answer": true,
+  "corpus": "ecfr",
+  "index": 3,
+  "indices": [
+   3
+  ],
+  "label": "21 CFR 801.30(a)(11)",
+  "requirement_ids": [],
+  "role": "cited",
+  "tier": "supporting",
+  "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-801/section-801.30"
+ }
+]
```

### validation_initial
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -7,14 +7,3 @@
   3,
-  4,
-  5,
-  6,
-  7,
-  8,
-  9,
-  10,
-  11,
-  12,
-  13,
-  14,
-  15
+  4
  ],
@@ -26,496 +15,12 @@
  },
- "codes": [
-  "degenerate_output",
-  "truncated",
-  "invalid_citation",
-  "repeated_statement"
- ],
- "errors": 13,
+ "codes": [],
+ "errors": 0,
  "explicit": false,
- "invalid_citations": [
-  5,
-  6,
-  7,
-  8,
-  9,
-  10,
-  11,
-  12,
-  13,
-  14,
-  15
- ],
+ "invalid_citations": [],
  "n_sources": 4,
- "ok": false,
- "problems": [
-  {
-   "citation": null,
-   "code": "degenerate_output",
-   "detail": "69% of 4-grams are repeats",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": null,
-   "code": "truncated",
-   "detail": "generation stopped at this question's allowance (384/384 tokens) before the answer finished",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 5,
-   "code": "invalid_citation",
-   "detail": "[5] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 6,
-   "code": "invalid_citation",
-   "detail": "[6] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 7,
-   "code": "invalid_citation",
-   "detail": "[7] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 8,
-   "code": "invalid_citation",
-   "detail": "[8] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 9,
-   "code": "invalid_citation",
-   "detail": "[9] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 10,
-   "code": "invalid_citation",
-   "detail": "[10] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 11,
-   "code": "invalid_citation",
-   "detail": "[11] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 12,
-   "code": "invalid_citation",
-   "detail": "[12] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 13,
-   "code": "invalid_citation",
-   "detail": "[13] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 14,
-   "code": "invalid_citation",
-   "detail": "[14] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 15,
-   "code": "invalid_citation",
-   "detail": "[15] does not correspond to any supplied source (1..4)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [7].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [8].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [9].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [10].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [11].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [12].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device packaged withi'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [8].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [9].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [10].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [11].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [12].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [9].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [10].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [11].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [12].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [10].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [11].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [12].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [11].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [12].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [12].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [13].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [14].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  },
-  {
-   "citation": null,
-   "code": "repeated_statement",
-   "detail": "near-duplicate of an earlier statement: 'The unique device identifier is required to be placed on a device that is packag'",
-   "requirement_id": null,
-   "sentence": "The unique device identifier is required to be placed on a device that is packaged within the immediate container of a combination product or convenience kit [15].",
-   "severity": "warning"
-  }
- ],
+ "ok": true,
+ "problems": [],
  "shape": {
   "citation_gaps": 0,
-  "codes": [
-   "repeated_statement"
-  ],
+  "codes": [],
   "groups": 3,
@@ -528,3 +33,3 @@
   "provision_led_blocks": [],
-  "repeated_pairs": 45,
+  "repeated_pairs": 0,
   "shape": {
@@ -543,5 +48,5 @@
  },
- "status": "degenerate",
+ "status": "valid",
  "unaddressed": [],
- "warnings": 45
+ "warnings": 0
 }
```

### validation_final
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -3,8 +3,16 @@
  "answer_class": "answer",
- "cited": [],
- "cited_tiers": {},
- "codes": [
-  "truncated"
+ "cited": [
+  1,
+  2,
+  3,
+  4
  ],
- "errors": 1,
+ "cited_tiers": {
+  "1": "supporting",
+  "2": "supporting",
+  "3": "supporting",
+  "4": "supporting"
+ },
+ "codes": [],
+ "errors": 0,
  "explicit": false,
@@ -12,13 +20,4 @@
  "n_sources": 4,
- "ok": false,
- "problems": [
-  {
-   "citation": null,
-   "code": "truncated",
-   "detail": "generation stopped at this question's allowance (384/384 tokens) before the answer finished",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  }
- ],
+ "ok": true,
+ "problems": [],
  "shape": {
@@ -27,3 +26,3 @@
   "groups": 3,
-  "groups_covered": 0,
+  "groups_covered": 3,
   "material_items": 0,
@@ -49,3 +48,3 @@
  },
- "status": "incomplete",
+ "status": "valid",
  "unaddressed": [],
```

### repair
- mps_fp32_resume2_20260929T054005Z: `safe_message`
- mps_fp16_20260929T050537Z: `None`

### citation_support
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -6,6 +6,12 @@
   "structural": 0,
-  "supporting": 0
+  "supporting": 5
  },
  "exact_source_cited_for": {},
- "markers": []
+ "markers": [
+  1,
+  2,
+  1,
+  3,
+  4
+ ]
 }
```

### generated_tokens
- mps_fp32_resume2_20260929T054005Z: `384`
- mps_fp16_20260929T050537Z: `95`

## S5-083 (domain_boundary): What does the EU Medical Device Regulation require for UDI?

### answer
First divergence at character 111, after: `(Unique Device Identification) must be assigned to a device `
- mps_fp32_resume2_20260929T054005Z: `under the following conditions: 
- Non-Device-MDDS must be assigned to a device `
- mps_fp16_20260929T050537Z: `that is a non-device-MDDS or device-MDDS. If the device is a non-device-MDDS, th`

```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -1,5 +1 @@
-The EU Medical Device Regulation requires that UDI (Unique Device Identification) must be assigned to a device under the following conditions: 
-- Non-Device-MDDS must be assigned to a device under section 201(h) of the FD&C Act, and UDI must be assigned to a device that is a hardware function intended to assist software functions. 
-- Device-MDDS must be assigned to a device under section 201(h) of the FD&C Act, and UDI must be assigned to a device that is a hardware function intended to assist the software functions listed in the recommendations. 
-
-[1]
+The EU Medical Device Regulation requires that UDI (Unique Device Identification) must be assigned to a device that is a non-device-MDDS or device-MDDS. If the device is a non-device-MDDS, then the UDI must be assigned to a device that is a non-Device-MDDS. If the device is a device-MDDS, then the UDI must be assigned to a device that is a device under section 201(h) of the FD&C Act. The requirements apply to devices that are either non-Device-MDDS or device-MDDS. [1] [2]
```

### citations
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -21,3 +21,4 @@
   "indices": [
-   1
+   1,
+   2
   ],
```

### validation_initial
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -5,41 +5,18 @@
   1,
-  4
+  2
  ],
  "cited_tiers": {
-  "1": "discovery"
+  "1": "discovery",
+  "2": "discovery"
  },
- "codes": [
-  "invalid_citation",
-  "synthesis_citation_gap"
- ],
- "errors": 1,
+ "codes": [],
+ "errors": 0,
  "explicit": false,
- "invalid_citations": [
-  4
- ],
+ "invalid_citations": [],
  "n_sources": 2,
- "ok": false,
- "problems": [
-  {
-   "citation": 4,
-   "code": "invalid_citation",
-   "detail": "[4] does not correspond to any supplied source (1..2)",
-   "requirement_id": null,
-   "sentence": null,
-   "severity": "error"
-  },
-  {
-   "citation": 2,
-   "code": "synthesis_citation_gap",
-   "detail": "section 201(h) comes from SOURCE 2, which the statement does not cite (it cites 1)",
-   "requirement_id": null,
-   "sentence": "- Device-MDDS must be assigned to a device under section 201(h) of the FD&C Act, and UDI must be assigned to a device that is a hardware function intended to assist the software functions listed in the recommendations [1] [4].",
-   "severity": "warning"
-  }
- ],
+ "ok": true,
+ "problems": [],
  "shape": {
-  "citation_gaps": 1,
-  "codes": [
-   "synthesis_citation_gap"
-  ],
+  "citation_gaps": 0,
+  "codes": [],
   "groups": 1,
@@ -65,5 +42,5 @@
  },
- "status": "citation_invalid",
+ "status": "valid",
  "unaddressed": [],
- "warnings": 1
+ "warnings": 0
 }
```

### validation_final
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -4,10 +4,10 @@
  "cited": [
-  1
+  1,
+  2
  ],
  "cited_tiers": {
-  "1": "discovery"
+  "1": "discovery",
+  "2": "discovery"
  },
- "codes": [
-  "synthesis_citation_gap"
- ],
+ "codes": [],
  "errors": 0,
@@ -17,17 +17,6 @@
  "ok": true,
- "problems": [
-  {
-   "citation": 2,
-   "code": "synthesis_citation_gap",
-   "detail": "section 201(h) comes from SOURCE 2, which the statement does not cite (it cites 1)",
-   "requirement_id": null,
-   "sentence": "- Device-MDDS must be assigned to a device under section 201(h) of the FD&C Act, and UDI must be assigned to a device that is a hardware function intended to assist the software functions listed in the recommendations [1].",
-   "severity": "warning"
-  }
- ],
+ "problems": [],
  "shape": {
-  "citation_gaps": 1,
-  "codes": [
-   "synthesis_citation_gap"
-  ],
+  "citation_gaps": 0,
+  "codes": [],
   "groups": 1,
@@ -55,3 +44,3 @@
  "unaddressed": [],
- "warnings": 1
+ "warnings": 0
 }
```

### repair
- mps_fp32_resume2_20260929T054005Z: `invalid_citations_removed`
- mps_fp16_20260929T050537Z: `None`

### citation_support
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -2,3 +2,3 @@
  "by_tier": {
-  "discovery": 1,
+  "discovery": 2,
   "exact": 0,
@@ -10,3 +10,4 @@
  "markers": [
-  1
+  1,
+  2
  ]
```

### generated_tokens
- mps_fp32_resume2_20260929T054005Z: `130`
- mps_fp16_20260929T050537Z: `123`

## AS-05 (comparison): Compare 21 CFR 820.10(c) and 820.10(d).

### answer
First divergence at character 214, after: `evelopment, Clause 7.3 and its Subclauses in ISO 13485. The `
- mps_fp32_resume2_20260929T054005Z: `class I devices are as follows: [2] [2]. 21 CFR 820.10(d) applies to devices tha`
- mps_fp16_20260929T050537Z: `requirement applies only to devices that are automated with computer software [2`

```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -1,4 +1,4 @@
-[1] 21 CFR 820.10(c) requires manufacturers of class II, class III, and class I devices listed in paragraph (c)(1) and table 1 to comply with Design and Development, Clause 7.3 and its Subclauses in ISO 13485. The class I devices are as follows: [2] [2]. 21 CFR 820.10(d) applies to devices that support or sustain life. 
+[1] 21 CFR 820.10(c) requires manufacturers of class II, class III, and class I devices listed in paragraph (c)(1) and table 1 to comply with Design and Development, Clause 7.3 and its Subclauses in ISO 13485. The requirement applies only to devices that are automated with computer software [2]. 21 CFR 820.10(d) applies to devices that support or sustain life and must comply with the requirements in ISO 13485, as appropriate. 
 
-The requirements differ in that 21 CFR 820.10(c) applies to both automated devices and devices listed in table 1, while 21 CFR 820.10(d) applies only to devices that support or sustain life.
+The requirements differ in that 21 CFR 820.10(c) applies to automated devices and class I devices, while 21 CFR 820.10(d) applies to devices that support or sustain life.
 21 CFR 820.10(d) (eCFR, binding, verbatim): (d) Devices that support or sustain life. Manufacturers of devices that support or sustain life, the failure of which to perform when properly used in accordance with instructions for use provided in the labeling can be reasonably expected to result in a significant injury, must comply with the requirements in Traceability for Implantable Devices, Clause 7.5.9.2 in ISO 13485, in addition to all other applicable requirements in this part, as appropriate [2].
```

### validation_initial
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -17,2 +17,3 @@
   "citation_mismatch",
+  "uncited_statement",
   "low_overlap_with_cited_source",
@@ -39,3 +40,3 @@
    "requirement_id": "r1",
-   "sentence": "21 CFR 820.10(c) applies to devices that are automated with computer software and the devices listed in table 1 [2].",
+   "sentence": "21 CFR 820.10(c) applies to devices that are automated with computer software and to class II, class III, and class I devices listed in paragraph (c)(1) and table 1 [2].",
    "severity": "error"
@@ -55,4 +56,20 @@
    "requirement_id": "r1",
-   "sentence": "21 CFR 820.10(c) applies to devices that are automated with computer software and the devices listed in table 1 [2].",
+   "sentence": "21 CFR 820.10(c) applies to devices that are automated with computer software and to class II, class III, and class I devices listed in paragraph (c)(1) and table 1 [2].",
    "severity": "error"
+  },
+  {
+   "citation": null,
+   "code": "uncited_statement",
+   "detail": "statement about a requested provision carries no citation",
+   "requirement_id": "r2",
+   "sentence": "21 CFR 820.10(d) applies to devices that support or sustain life and must comply with the requirements in ISO 13485, as appropriate.",
+   "severity": "warning"
+  },
+  {
+   "citation": 2,
+   "code": "low_overlap_with_cited_source",
+   "detail": "only 17% of the content words appear in the cited exact source",
+   "requirement_id": null,
+   "sentence": "The requirement applies only to devices that are automated with computer software [2].",
+   "severity": "warning"
   },
@@ -69,5 +86,5 @@
    "code": "low_overlap_with_cited_source",
-   "detail": "only 14% of the content words appear in the cited exact source",
+   "detail": "only 11% of the content words appear in the cited exact source",
    "requirement_id": null,
-   "sentence": "21 CFR 820.10(c) applies to devices that are automated with computer software and the devices listed in table 1 [2].",
+   "sentence": "21 CFR 820.10(c) applies to devices that are automated with computer software and to class II, class III, and class I devices listed in paragraph (c)(1) and table 1 [2].",
    "severity": "warning"
@@ -120,3 +137,3 @@
  "unaddressed": [],
- "warnings": 3
+ "warnings": 5
 }
```

### validation_final
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -14,3 +14,6 @@
  },
- "codes": [],
+ "codes": [
+  "uncited_statement",
+  "low_overlap_with_cited_source"
+ ],
  "errors": 0,
@@ -20,3 +23,20 @@
  "ok": true,
- "problems": [],
+ "problems": [
+  {
+   "citation": null,
+   "code": "uncited_statement",
+   "detail": "statement about a requested provision carries no citation",
+   "requirement_id": "r2",
+   "sentence": "21 CFR 820.10(d) applies to devices that support or sustain life and must comply with the requirements in ISO 13485, as appropriate.",
+   "severity": "warning"
+  },
+  {
+   "citation": 2,
+   "code": "low_overlap_with_cited_source",
+   "detail": "only 17% of the content words appear in the cited exact source",
+   "requirement_id": null,
+   "sentence": "The requirement applies only to devices that are automated with computer software [2].",
+   "severity": "warning"
+  }
+ ],
  "shape": {
@@ -56,3 +76,3 @@
  "unaddressed": [],
- "warnings": 0
+ "warnings": 2
 }
```

### citation_support
```diff
--- mps_fp32_resume2_20260929T054005Z
+++ mps_fp16_20260929T050537Z
@@ -3,3 +3,3 @@
   "discovery": 0,
-  "exact": 5,
+  "exact": 4,
   "invalid": 0,
@@ -16,3 +16,2 @@
   2,
-  2,
   1
```

### generated_tokens
- mps_fp32_resume2_20260929T054005Z: `264`
- mps_fp16_20260929T050537Z: `295`

