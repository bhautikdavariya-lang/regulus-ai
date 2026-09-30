# A vs B: 39 questions differ

## S5-003 (explanation): Explain 21 CFR 830.310(b)(1).

Sources (same retrieval): 21 CFR 830.310(b)(1), 21 CFR 830.310(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 1 |
| generated tokens | 38 | 21 |
| total ms | 3816.52 | 2678.96 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-21 CFR 830.310(b)(1) requires that the device identifier portion of the UDI assigned to the version or model be provided. [1]
+The device identifier portion of the UDI assigned to the version or model is required. [1]
```

## S5-004 (requirement): What must be included under 21 CFR 50.25(a)(1)?

Sources (same retrieval): 21 CFR 50.25(a)(1), 21 CFR 50.25(a), FDA Guidance: Investigational Device Exemption (IDE) Guidance for Retinal Prostheses: Guidance for Industry and FDA Staff (final, 2013-03-06, Docket FDA-2009-D-0010), FDA Guidance: Cellular Therapy for Cardiac Disease: Guidance for Industry (final, 2010-10-01, Docket FDA-2009-D-0132)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 1 |
| generated tokens | 64 | 66 |
| total ms | 7276.23 | 7661.95 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-Under 21 CFR 50.25(a)(1), a statement must be included that the study involves research, an explanation of the purposes of the research, the expected duration of the subject's participation, a description of the procedures to be followed, and identification of any experimental procedures. [1]
+Under 21 CFR 50.25(a)(1), a statement must be included that the study involves research, an explanation of the purposes of the research, the expected duration of the subject's participation, a description of the procedures to be followed, and identification of any procedures which are experimental. [1]
```

## S5-005 (requirement): What does § 211.132(a) say?

Sources (same retrieval): 21 CFR 211.132(a)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 1 |
| generated tokens | 60 | 52 |
| total ms | 5193.39 | 4855.13 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-§ 211.132(a) requires that OTC drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section. If applicable, the requirement applies to devices or persons that are not properly labeled or packaged. [1]
+§ 211.132(a) requires that OTC human drug products (except for specific categories) must be packaged in tamper-resistant packages and properly labeled under this section to prevent adulteration or misbranding. [1]
```

## S5-007 (requirement): What does 21 CFR 806.10(a) require?

Sources (same retrieval): 21 CFR 806.10(a), 21 CFR 806.10(a)(1), 21 CFR 806.10(a)(2), FDA Guidance: Postmarketing Safety Reporting for Combination Products: Guidance for Industry and FDA Staff (final, 2019-07-22, Docket FDA-2008-N-0424), FDA Guidance: Medical Device Classification Product Codes - Guidance for Industry and Food and Drug Administration Staff (final, 2013-04-10, Docket FDA-2011-D-0916)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 1 | 2 |
| generated tokens | 126 | 129 |
| total ms | 11935.65 | 12377.36 |
| flags | citation_mismatch | citation_mismatch |

```diff
--- A
+++ B
@@ -1 +1 @@
-21 CFR 806.10(a) requires that device manufacturers or importers submit a written report to the FDA of any correction or removal of a device initiated by such manufacturer or importer if the correction or removal was initiated. The report must include either to reduce a risk to health posed by the device or to remedy a violation of the act caused by the device which may present a risk to health unless the information has already been provided as set forth in paragraph (f) of this section or the corrective or removal action is exempt from the reporting requirements under § 806.1(b). [1]
+21 CFR 806.10(a) requires that device manufacturers or importers submit a written report to the FDA of any correction or removal of a device initiated by such manufacturer or importer if the correction or removal was initiated. [1] The report must include either to reduce a risk to health posed by the device or to remedy a violation of the act caused by the device which may present a risk to health unless the information has already been provided as set forth in paragraph (f) of this section or the corrective or removal action is exempt from the reporting requirements under § 806.1(b). [2]
```

## S5-010 (requirement): What does 21 CFR 820.10(b) require manufacturers to comply with?

Sources (same retrieval): 21 CFR 820.10(b), 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10, FDA Guidance: Quality Management System Information for Certain Premarket Submission Reviews: Draft Guidance for Industry and Food and Drug Administration Staff (draft, 2025-10-27, Docket FDA-2025-D-4051)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 4 | 4 |
| generated tokens | 124 | 117 |
| total ms | 13374.89 | 12899.33 |
| flags | citation_mismatch, missing_condition | citation_mismatch, missing_condition |

```diff
--- A
+++ B
@@ -1,4 +1 @@
-21 CFR 820.10(b) requires manufacturers to document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1].  
-The manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [3].  
-The manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [4].  
-Advisory notices shall be handled in accordance with the requirements of part 806 of this chapter [5].
+21 CFR 820.10(b) requires manufacturers to document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1], document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [3], and notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [4]. If applicable, advisory notices shall be handled in accordance with the requirements of part 806 of this chapter [5].
```

## S5-011 (requirement): What does 21 CFR 101.3(b) require?

Sources (same retrieval): 21 CFR 101.3(b), 21 CFR 101.3(b)(1), 21 CFR 101.3(b)(2), 21 CFR 101.3(b)(3), FDA Guidance: Guidance for Industry: The Seafood List FDA’s Guide to Determine Acceptable Seafood Names (final, 2023-08-22, Docket FDA-1994-D-0221), FDA Guidance: Guidance for Industry: The Seafood List FDA’s Guide to Determine Acceptable Seafood Names (final, 2023-08-22, Docket FDA-1994-D-0221)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | False |
| citations | 3 | 1 |
| generated tokens | 107 | 86 |
| total ms | 10773.09 | 9014.84 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-21 CFR 101.3(b) requires that the identity statement of food in packaged form be in terms of [1]. The name now or hereafter specified in or required by any applicable Federal law or regulation; or, in the absence thereof, [2] the common or usual name of the food; or, in the absence thereof, [3] an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food. [1]
+21 CFR 101.3(b) requires that the identity statement of food in packaged form be in terms of the name now or hereafter specified in or required by any applicable Federal law or regulation, or the common or usual name of the food, or an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food. [1]
```

## S5-012 (requirement): What does 21 CFR 820.10 say?

Sources (same retrieval): 21 CFR 820.10, 21 CFR 820.10(a), 21 CFR 820.10(b), 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10(c), 21 CFR 820.10(c)(1), 21 CFR 820.10(c)(2), 21 CFR 820.10(d), 21 CFR 820.10(e)

| | A | B |
|---|---|---|
| initial validation | incomplete | valid |
| repair | appended_missing_items | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | True |
| citations | 12 | 12 |
| generated tokens | 191 | 154 |
| total ms | 21776.55 | 18416.66 |
| flags | citation_mismatch | - |

```diff
--- A
+++ B
@@ -1,3 +1 @@
-21 CFR 820.10 requires a manufacturer subject to this part to document a quality management system that complies with ISO 13485 and other applicable requirements. The manufacturer must document a system to assign unique device identification in accordance with part 830 of this chapter, document procedures for traceability in accordance with part 821 of this chapter, and notify FDA of complaints that meet the reporting criteria of part 803 of this chapter. Advisory notices shall be handled in accordance with part 806 of this chapter. The requirements apply to devices automated with computer software, devices listed in the following table, and devices that support or sustain life. If applicable, the requirements apply to devices that support or sustain life. The enforcement of these requirements renders a device adulterated under section 501(h) of the Federal Food, Drug, and Cosmetic Act. [4][5]
-21 CFR 820.10(a) (eCFR, binding, verbatim): (a) Document. Document a quality management system that complies with the applicable requirements of ISO 13485 (incorporated by reference, see § 820.7) and other applicable requirements of this part; and [2].
-21 CFR 820.10(d) (eCFR, binding, verbatim): (d) Devices that support or sustain life. Manufacturers of devices that support or sustain life, the failure of which to perform when properly used in accordance with instructions for use provided in the labeling can be reasonably expected to result in a significant injury, must comply with the requirements in Traceability for Implantable Devices, Clause 7.5.9.2 in ISO 13485, in addition to all other applicable requirements in this part, as appropriate [11].
+21 CFR 820.10 requires a manufacturer to document a quality management system that complies with ISO 13485 and other applicable requirements, including unique device identification, traceability procedures, and FDA complaints reporting. If applicable, the manufacturer must also document procedures for advisory notices. The requirements apply to devices automated with computer software, devices listed in table 1, devices that support or sustain life, and enforcement of compliance. If applicable, the requirements apply to class II, class III, and class I devices listed in paragraphs (c)(1) and (c)(2) of this section, and devices that support or sustain life. [1][2][4][5][8][9][11][12]
```

## S5-013 (explanation): Summarize 21 CFR 803.13.

Sources (same retrieval): 21 CFR 803.13

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 1 |
| generated tokens | 29 | 28 |
| total ms | 5195.14 | 3266.64 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-[1] 21 CFR 803.13 requires that all reports required by this part must be submitted in English.
+21 CFR 803.13 requires that all reports required by this part must be submitted in English. [1]
```

## S5-020 (requirement): What do 21 CFR 820.10(b)(2) and 820.10(b)(4) require?

Sources (same retrieval): 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(4), 21 CFR 820.10(b), FDA Guidance: Quality Management System Information for Certain Premarket Submission Reviews: Draft Guidance for Industry and Food and Drug Administration Staff (draft, 2025-10-27, Docket FDA-2025-D-4051), FDA Guidance: Quality Management System Information for Certain Premarket Submission Reviews: Draft Guidance for Industry and Food and Drug Administration Staff (draft, 2025-10-27, Docket FDA-2025-D-4051)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 2 | 2 |
| generated tokens | 130 | 86 |
| total ms | 15559.18 | 10237.21 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1,2 +1 @@
-[1] 21 CFR 820.10(b)(2) [1] requires that if applicable, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, as required by ISO 13485.  
-[2] 21 CFR 820.10(b)(4) [2] requires that for Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance with the requirements of part 806 of this chapter.
+21 CFR 820.10(b)(2) requires that the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable. 21 CFR 820.10(b)(4) requires that advisory notices shall be handled in accordance with the requirements of part 806 of this chapter. [1] [2]
```

## S5-021 (requirement): What are the requirements of 21 CFR § 820.10(b)(1), (b)(2), and (b)(3)?

Sources (same retrieval): 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b), FDA Guidance: Quality Management System Information for Certain Premarket Submission Reviews: Draft Guidance for Industry and Food and Drug Administration Staff (draft, 2025-10-27, Docket FDA-2025-D-4051)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | True |
| citations | 3 | 3 |
| generated tokens | 164 | 164 |
| total ms | 15491.28 | 15391.82 |
| flags | citation_mismatch | - |

```diff
--- A
+++ B
@@ -1,3 +1,3 @@
-[1] (1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter.  
-[2] (2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable.  
-[3] (3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter.
+(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1].  
+(2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [2].  
+(3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [3].
```

## S5-022 (comparison): Compare the requirements of § 820.10(b)(2) and § 820.10(b)(4).

Sources (same retrieval): 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(4), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | False |
| citations | 2 | 2 |
| generated tokens | 115 | 142 |
| total ms | 10242.0 | 11477.57 |
| flags | - | citation_mismatch, missing_condition |

```diff
--- A
+++ B
@@ -1,3 +1 @@
-[1] § 820.10(b)(2) requires that manufacturers document traceability procedures in accordance with part 821 of this chapter, if applicable. [2] § 820.10(b)(4) requires that advisory notices be handled in accordance with part 806 of this chapter.  
-
-If applicable, the requirements in § 820.10(b)(2) apply to manufacturers, while the requirements in § 820.10(b)(4) apply to advisory notices.
+§ 820.10(b)(2) requires that manufacturers document traceability procedures in accordance with part 821 of this chapter, if applicable [1]. It applies to manufacturers under clause 7.5.9.1 in ISO 13485. [2] § 820.10(b)(4) requires that advisory notices be handled in accordance with part 806 of this chapter, if applicable. It applies to manufacturers under clauses 7.2.3, 8.2.3, and 8.3.3 of ISO 13485. If applicable, these requirements apply to manufacturers.
```

## S5-023 (requirement): What do 21 CFR 101.54(a)(1) and 101.54(a)(3) require?

Sources (same retrieval): 21 CFR 101.54(a)(1), 21 CFR 101.54(a)(3), 21 CFR 101.54(a)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 2 | 2 |
| generated tokens | 109 | 103 |
| total ms | 9725.4 | 8753.43 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1,5 +1 @@
-[1] 21 CFR 101.54(a)(1) [1]  
-The claim uses one of the terms defined in this section in accordance with the definition for that term.  
-
-[2] 21 CFR 101.54(a)(3) [2]  
-The food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.
+21 CFR 101.54(a)(1) [1] requires that the claim uses one of the terms defined in this section in accordance with the definition for that term. 21 CFR 101.54(a)(3) [2] requires that the food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.
```

## S5-024 (requirement): What do 21 CFR 807.81(a) and 21 CFR 820.10(b)(3) require?

Sources (same retrieval): 21 CFR 807.81(a), 21 CFR 820.10(b)(3), 21 CFR 807.81(a)(1), 21 CFR 807.81(a)(2), 21 CFR 807.81(a)(3), 21 CFR 807.81(a)(3)(i), 21 CFR 807.81(a)(3)(ii)

| | A | B |
|---|---|---|
| initial validation | degenerate | incomplete |
| repair | extractive_replacement | appended_missing_provisions |
| final validation | incomplete | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | True |
| citations | 6 | 6 |
| generated tokens | 487 | 329 |
| total ms | 48206.19 | 29497.35 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1,3 +1,7 @@
-The generated answer could not be validated against the retrieved regulatory evidence. The verified text of the requested provision(s) follows.
-21 CFR 807.81(a) (eCFR, binding, verbatim): (a) Except as provided in paragraph (b) of this section, each person who is required to register his establishment pursuant to § 807.20 must submit a premarket notification submission to the Food and Drug Administration at least 90 days before he proposes to begin the introduction or delivery for introduction into interstate commerce for commercial distribution of a device intended for human use which meets any of the following criteria: [1].
+21 CFR 807.81(a) requires that a person required to register an establishment must submit a premarket notification submission at least 90 days before the device is introduced into interstate commerce for commercial distribution [1].  
+21 CFR 807.81(a)(1) requires that a device is introduced for the first time by a person required to register, whether or not it meets the criteria in paragraph (a)(1) of this section [3].  
+21 CFR 807.81(a)(2) requires that a device is introduced for the first time by a person required to register, but that is about to be significantly changed or modified in design, components, method of manufacture, or intended use [4].  
+21 CFR 807.81(a)(3) requires that a device is one that the person currently has in commercial distribution or is reintroducing into commercial distribution, but that is about to be significantly changed or modified in design, components, method of manufacture, or intended use [5].  
+21 CFR 807.81(a)(3)(i) requires that a change or modification in the device that could significantly affect the safety or effectiveness of the device, e.g., a significant change or modification in design, material, chemical composition, energy source, or manufacturing process [6].  
+21 CFR 807.81(a)(3)(ii) requires that a major change or modification in the intended use of the device [7].
 21 CFR 820.10(b)(3) (eCFR, binding, verbatim): (3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [2].
```

## S5-030 (requirement): What do 21 CFR 820.10(b)(1) through (b)(4) require?

Sources (same retrieval): 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10(b), FDA Guidance: Quality Management System Information for Certain Premarket Submission Reviews: Draft Guidance for Industry and Food and Drug Administration Staff (draft, 2025-10-27, Docket FDA-2025-D-4051)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 4 | 4 |
| generated tokens | 187 | 188 |
| total ms | 18765.29 | 17579.63 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1,4 +1,4 @@
-1. [1] 21 CFR 820.10(b)(1) requires that the manufacturer document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter.  
-2. [2] 21 CFR 820.10(b)(2) requires that the manufacturer document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable.  
-3. [3] 21 CFR 820.10(b)(3) requires that the manufacturer notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter.  
-4. [4] 21 CFR 820.10(b)(4) requires that advisory notices be handled in accordance with the requirements of part 806 of this chapter.
+1. 21 CFR 820.10(b)(1) requires that the manufacturer document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1].  
+2. 21 CFR 820.10(b)(2) requires that the manufacturer document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [2].  
+3. 21 CFR 820.10(b)(3) requires that the manufacturer notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter [3].  
+4. 21 CFR 820.10(b)(4) requires that the manufacturer handle advisory notices in accordance with the requirements of part 806 of this chapter [4].
```

## S5-031 (requirement): List the requirements in 820.10(b)(1)-(b)(4).

Sources (same retrieval): 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | True |
| citations | 4 | 4 |
| generated tokens | 72 | 276 |
| total ms | 7549.49 | 22675.18 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1,11 @@
-21 CFR 820.10(b)(1) [1]; 21 CFR 820.10(b)(2) [2]; 21 CFR 820.10(b)(3) [3]; 21 CFR 820.10(b)(4) [4].
+21 CFR 820.10(b)(1) [1]  
+(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter.  
+
+21 CFR 820.10(b)(2) [2]  
+(2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable.  
+
+21 CFR 820.10(b)(3) [3]  
+(3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter.  
+
+21 CFR 820.10(b)(4) [4]  
+(4) For Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance with the requirements of part 806 of this chapter.
```

## S5-032 (requirement): What do 21 CFR 101.3(b)(1) through (b)(3) require?

Sources (same retrieval): 21 CFR 101.3(b)(1), 21 CFR 101.3(b)(2), 21 CFR 101.3(b)(3), 21 CFR 101.3(b), FDA Guidance: Draft Guidance for Industry: Labeling of Plant-Based Milk Alternatives and Voluntary Nutrient Statements (draft, 2023-02-10, Docket FDA-2023-D-0451), FDA Guidance: Guidance for Industry: Labeling of Infant Formula (final, 2023-03-06, Docket FDA-2013-S-0610)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 3 | 3 |
| generated tokens | 193 | 166 |
| total ms | 19095.67 | 15466.08 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1,3 +1,3 @@
-[1] 21 CFR 101.3(b)(1) [1] The name now or hereafter specified in or required by any applicable Federal law or regulation; or, in the absence thereof, the common or usual name of the food; or, when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
-[2] 21 CFR 101.3(b)(2) [2] The common or usual name of the food; or, in the absence thereof, an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
-[3] 21 CFR 101.3(b)(3) [3] An appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.
+21 CFR 101.3(b)(1) requires that the name now or hereafter specified in or required by any applicable Federal law or regulation; or, in the absence thereof, the common or usual name of the food [1].  
+21 CFR 101.3(b)(2) requires that the common or usual name of the food; or, in the absence thereof, an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food [2].  
+21 CFR 101.3(b)(3) requires that an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food [3].
```

## S5-033 (explanation): Explain 21 CFR 101.54(a)(1) through (a)(3).

Sources (same retrieval): 21 CFR 101.54(a)(1), 21 CFR 101.54(a)(2), 21 CFR 101.54(a)(3), 21 CFR 101.54(a)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 3 | 3 |
| generated tokens | 108 | 111 |
| total ms | 9827.32 | 9716.56 |
| flags | - | citation_mismatch |

```diff
--- A
+++ B
@@ -1,3 +1 @@
-[1] (1) The claim uses one of the terms defined in this section in accordance with the definition for that term;  
-[2] (2) The claim is made in accordance with the general requirements for nutrient content claims in § 101.13;  
-[3] (3) The food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.
+The available regulatory sources do not provide enough information to answer this. [1] The claim uses one of the terms defined in this section in accordance with the definition for that term. [2] The claim is made in accordance with the general requirements for nutrient content claims in § 101.13; and [3] The food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.
```

## S5-041 (requirement): What do 21 CFR 820.10(b)(1) through (b)(5) require?

Sources (same retrieval): 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer_partial | answer_partial |
| machine checks pass (final) | True | True |
| citations | 4 | 4 |
| generated tokens | 292 | 179 |
| total ms | 24545.15 | 15407.08 |
| flags | citation_mismatch, missing_condition | - |

```diff
--- A
+++ B
@@ -1,11 +1,4 @@
-[1] 21 CFR 820.10(b)(1) [1]  
-(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter.  
-
-[2] 21 CFR 820.10(b)(2) [2]  
-(2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable.  
-
-[3] 21 CFR 820.10(b)(3) [3]  
-(3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter.  
-
-[4] 21 CFR 820.10(b)(4) [4]  
-(4) For Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance with the requirements of part 806 of this chapter. Not found in the available eCFR data: 21 CFR 820.10(b)(5). The answer above covers only the provisions that were retrieved.
+21 CFR 820.10(b)(1) requires that the manufacturer document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1].  
+21 CFR 820.10(b)(2) requires that the manufacturer document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [2].  
+21 CFR 820.10(b)(3) requires that the manufacturer notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter [3].  
+21 CFR 820.10(b)(4) requires that advisory notices be handled in accordance with the requirements of part 806 of this chapter [4]. Not found in the available eCFR data: 21 CFR 820.10(b)(5). The answer above covers only the provisions that were retrieved.
```

## S5-042 (requirement): What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?

Sources (same retrieval): 21 CFR 820.10(b)(2), 21 CFR 820.10, 21 CFR 820.10(b), 21 CFR 520.999(a), 21 CFR 820.1(a), 21 CFR 820.3, 21 CFR 820.7

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer_partial | answer_partial |
| machine checks pass (final) | True | False |
| citations | 1 | 1 |
| generated tokens | 103 | 138 |
| total ms | 11122.25 | 13563.07 |
| flags | - | missing_condition |

```diff
--- A
+++ B
@@ -1,2 +1,5 @@
-[1] 21 CFR 820.10(b)(2) requires that a manufacturer subject to this part must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable.  
-[1] 21 CFR 820.999 (not found in the available eCFR data) requires that a manufacturer subject to this part must establish and maintain a quality management system that is appropriate for its specific device(s). Not found in the available eCFR data: 21 CFR 820.999. The answer above covers only the provisions that were retrieved.
+21 CFR 820.10(b)(2) requires that a manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable. [1]  
+
+21 CFR 820.10(b)(2) requires that a manufacturer subject to this part must comply with the other applicable regulatory requirements in this title, including, but not limited to, the following, to fully comply with the listed ISO 13485 Clause. [1]  
+
+21 CFR 820.999 (not found in the available eCFR data) does not provide any requirements. Not found in the available eCFR data: 21 CFR 820.999. The answer above covers only the provisions that were retrieved.
```

## S5-050 (requirement): Which FDA form number must be used under 21 CFR 820.10(b)(4)?

Sources (same retrieval): 21 CFR 820.10(b)(4), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | True |
| citations | 1 | 1 |
| generated tokens | 59 | 64 |
| total ms | 5348.73 | 5657.65 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-[1] The FDA form number required under 21 CFR 820.10(b)(4) is not specified in the provided evidence. The evidence does not provide a form number for this provision. The available regulatory sources do not provide enough information to answer this question.
+Under 21 CFR 820.10(b)(4), advisory notices for Clauses 7.2.3, 8.2.3, and 8.3.3 must be handled in accordance with the requirements of part 806 of this chapter. [1]
```

## S5-051 (requirement): What penalty amount does 21 CFR 820.10(b)(3) specify for late complaint notification?

Sources (same retrieval): 21 CFR 820.10(b)(3), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | unsupported | unsupported |
| repair | extractive_replacement | extractive_replacement |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 1 |
| generated tokens | 34 | 34 |
| total ms | 3398.29 | 3420.62 |
| flags | - | possible_hallucination |

## S5-052 (requirement): By what date must a manufacturer comply with 21 CFR 820.10(b)(1)?

Sources (same retrieval): 21 CFR 820.10(b)(1), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 1 | 1 |
| generated tokens | 37 | 58 |
| total ms | 3627.5 | 4950.74 |
| flags | - | missing_condition |

```diff
--- A
+++ B
@@ -1 +1 @@
-The manufacturer must comply with 21 CFR 820.10(b)(1) by the date specified in the requirements for a quality management system. [1]
+The manufacturer must comply with 21 CFR 820.10(b)(1) by the date specified in the requirements for a quality management system, as outlined in the applicable regulatory requirements under 21 CFR 820.10(b). [1]
```

## S5-053 (applicability): Does 21 CFR 820.10(b)(2) require annual traceability audits?

Sources (same retrieval): 21 CFR 820.10(b)(2), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | incomplete |
| repair | None | appended_missing_provisions |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 0 |
| generated tokens | 24 | 7 |
| total ms | 2783.25 | 1712.54 |
| flags | missing_condition, missing_direct_answer, unsupported_claim | missing_citation |

```diff
--- A
+++ B
@@ -1 +1,2 @@
-21 CFR 820.10(b)(2) requires annual traceability audits. [1]
+The sources do not say.
+21 CFR 820.10(b)(2) (eCFR, binding, verbatim): (2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [1].
```

## S5-060 (requirement): When must a manufacturer notify FDA about a complaint?

Sources (same retrieval): 21 CFR 820.10(b)(3), FDA Guidance: Medical Gases — Current Good Manufacturing Practice: Draft Guidance for Industry (draft, 2025-11-28, Docket FDA-2003-D-0431), FDA Guidance: Current Good Manufacturing Practice for Phase 1 Investigational Drugs: Guidance for Industry (final, 2008-07-14, Docket FDA-2005-D-0157)

| | A | B |
|---|---|---|
| initial validation | citation_invalid | valid |
| repair | invalid_citations_removed | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 1 | 1 |
| generated tokens | 104 | 171 |
| total ms | 11231.27 | 15796.75 |
| flags | - | citation_mismatch |

```diff
--- A
+++ B
@@ -1 +1,7 @@
-The manufacturer must notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter. If applicable, the manufacturer must also maintain written records for complaints, recalls, and investigations under § 213.180(d). Additionally, the manufacturer must have written procedures to notify responsible officials of any recalls, reports, or investigations under § 213.180(e). These requirements are based on the eCFR and FDA Guidance. [1]
+The manufacturer must notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter. [1]
+
+If applicable, the manufacturer must maintain written records so that data therein can be used for evaluating, at least annually, the quality standards of each medical gas to determine the need for changes in specifications or manufacturing or control procedures. [1]
+
+If applicable, the manufacturer must have written procedures for the review of the following: complaints, recalls, returned or salvaged medical gases, and investigations conducted under § 213.192 for each medical gas. [1]
+
+If applicable, the manufacturer must have written procedures to notify responsible officials of the firm, in writing, of any recalls, reports of inspectional observations by FDA, regulatory actions related to good manufacturing practices brought by FDA, or investigations. [1]
```

## S5-061 (requirement): What is a unique device identifier required to contain?

Sources (same retrieval): 21 CFR 801.30(c), FDA Guidance: Unique Device Identifier Requirements for Combination Products: Draft Guidance for Industry (draft, 2025-06-25, Docket FDA-2025-D-0176), 21 CFR 801.30(a)(11), FDA Guidance: Unique Device Identifier Requirements for Combination Products: Draft Guidance for Industry (draft, 2025-06-25, Docket FDA-2025-D-0176)

| | A | B |
|---|---|---|
| initial validation | degenerate | valid |
| repair | safe_message | None |
| final validation | incomplete | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 3 | 3 |
| generated tokens | 384 | 156 |
| total ms | 33310.82 | 13247.35 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-The generated answer could not be validated against the retrieved regulatory evidence.
+A unique device identifier is required to be placed on a device, as specified in the eCFR [1]. The eCFR [1] states that a unique device identifier is not required for shipping containers. The FDA Guidance [2] provides additional information on the requirements for combination products, including the need for a UDI if a device constituent part is present. The eCFR [3] specifies that a device packaged within the immediate container of a combination product or convenience kit must bear a UDI if the label of the combination product or convenience kit bears a UDI. The FDA Guidance [4] also mentions that a device must bear a UDI if it is a combination product and if it contains a device constituent part that is not subject to the exception.
```

## S5-062 (requirement): What are the tamper-evident packaging requirements for OTC drug products?

Sources (same retrieval): 21 CFR 211.132(b), 21 CFR 211.132(a), 21 CFR 211.132(d)(2), 21 CFR 211.132(c)(1)(iii), 21 CFR 211.132(b)(2), 21 CFR 211.132(c)(1)(i), 21 CFR 211.132(c)(1)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 0 | 4 |
| generated tokens | 180 | 149 |
| total ms | 16959.69 | 13270.47 |
| flags | missing_citation, question_echo | - |

```diff
--- A
+++ B
@@ -1,5 +1 @@
-What are the tamper-evident packaging requirements for OTC drug products?  
-
-The tamper-evident packaging requirements for OTC drug products are outlined in 21 CFR 211.132(b), which states that the requirements will improve the security of OTC drug packaging and help assure the safety and effectiveness of OTC drug products.  
-
-The requirements also include that the tamper-evident packaging feature must be placed in a way that is unaffected if the feature is breached or missing, as stated in 21 CFR 211.132(c)(1)(iii). Additionally, the packaging must identify all tamper-evident feature(s) and any capsule sealing technologies used to comply with paragraph (b) of this section, as stated in 21 CFR 211.132(c)(1)(i).
+The tamper-evident packaging requirements for over-the-counter (OTC) human drug products are specified in 21 CFR 211.132(b), which requires that the packaging be tamper-resistant and labeled appropriately. Additionally, 21 CFR 211.132(c)(1)(i) mandates that all tamper-evident features and capsule sealing technologies be identified, and 21 CFR 211.132(c)(1) requires that each retail package be labeled with a statement about the specific tamper-evident features used. These requirements ensure the security and effectiveness of OTC drug packaging. [1] [2] [6] [7]
```

## S5-063 (requirement): What must an IRB do when reviewing research?

Sources (same retrieval): FDA Guidance: Minutes of Institutional Review Board (IRB) Meetings: Guidance for Institutions and IRBs (final, 2017-09-25, Docket FDA-2015-D-3638), FDA Guidance: Frequently Asked Questions - IRB Registration: Guidance for Institutional Review Boards (IRBs) (final, 2009-07-09, Docket FDA-2009-D-0312), FDA Guidance: Minutes of Institutional Review Board (IRB) Meetings: Guidance for Institutions and IRBs (final, 2017-09-25, Docket FDA-2015-D-3638)

| | A | B |
|---|---|---|
| initial validation | citation_invalid | valid |
| repair | invalid_citations_removed | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 1 | 1 |
| generated tokens | 225 | 173 |
| total ms | 21143.36 | 15395.47 |
| flags | - | repeated_content |

```diff
--- A
+++ B
@@ -1 +1,5 @@
-An IRB must document the information required by 45 CFR 46.115(a)(2) and 21 CFR 56.115(a)(2) in the minutes. Additionally, the IRB must review research involving children as subjects covered by 45 CFR part 46, subpart D and/or 21 CFR part 50, subpart D, and approve such research only if it satisfies the conditions of all applicable sections of those subparts. The regulations for meeting minutes at 45 CFR 46.115(a)(2) and 21 CFR 56.115(a)(2) require documentation of these additional findings and determinations in the minutes. The regulations for meeting minutes at 45 CFR 46.115(a)(2) and 21 CFR 56.115(a)(2) also require documentation of relevant summary information when such information contributes to an understanding of the IRB’s findings and determinations. [1]
+An IRB must document the information required by 45 CFR 46.115(a)(2) and 21 CFR 56.115(a)(2) in the minutes. Additionally, IRBs must review research involving children as subjects covered by 45 CFR part 46, subpart D and/or 21 CFR part 50, subpart D, and approve such research only if it satisfies the conditions of all applicable sections of those subparts. [1]
+
+An IRB must document these additional findings and determinations in the minutes. [1] 
+
+An IRB must document the information required by 45 CFR 46.115(a)(2) and 21 CFR 56.115(a)(2) in the minutes. [1]
```

## S5-070 (explanation): Summarise the guidance in docket FDA-2016-D-2565.

Sources (same retrieval): FDA Guidance: 510(k) Third Party Review Program and Third Party Emergency Use Authorization (EUA) Review: Guidance for Industry, Food and Drug Administration Staff, and Third Party Review Organizations (final, 2024-11-21, Docket FDA-2016-D-2565), FDA Guidance: 510(k) Third Party Review Program and Third Party Emergency Use Authorization (EUA) Review: Guidance for Industry, Food and Drug Administration Staff, and Third Party Review Organizations (final, 2024-11-21, Docket FDA-2016-D-2565), FDA Guidance: 510(k) Third Party Review Program and Third Party Emergency Use Authorization (EUA) Review: Guidance for Industry, Food and Drug Administration Staff, and Third Party Review Organizations (final, 2024-11-21, Docket FDA-2016-D-2565)

| | A | B |
|---|---|---|
| initial validation | citation_invalid | valid |
| repair | invalid_citations_removed | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | False |
| citations | 1 | 1 |
| generated tokens | 202 | 128 |
| total ms | 23405.47 | 13708.92 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-The guidance in Docket FDA-2016-D-2565 requires that industry, food and drug administration staff, and third party review organizations submit electronic comments for Agency consideration. It also states that comments may not be acted upon until the document is next revised or updated. Additional copies are available from the Internet. The guidance also includes nonbinding recommendations about the 3P510k review program and third party emergency use authorization (EUA) review program. It specifies that factors used in determining device type eligibility in the 3P510k review program and the review of 510(k) submissions or EUA requests by third party review organizations are outlined in the document. The guidance also states that a submission must be administratively complete before a substantive review is conducted. The review should identify deficiencies in a submission and document the review. The requirements apply to industry, food and drug administration staff, and third party review organizations. [1]
+The guidance in Docket FDA-2016-D-2565 outlines requirements for the Third Party Review Program and Third Party Emergency Use Authorization (EUA) Review, including nonbinding recommendations, a table of contents, and specific sub-requirements. It specifies that comments may not be acted upon until the document is revised or updated, and that additional copies are available. The guidance also includes a table of contents and sub-sections detailing the scope, definitions, and review process for 3P510k and 3PEUA reviews. The sources cited support these requirements. [1][2][3].
```

## S5-071 (explanation): What does FDA guidance FDA-2024-D-2511 recommend?

Sources (same retrieval): FDA Guidance: Dental Composite Resin Devices - Premarket Notification (510(k)) Submissions: Guidance for Industry and Food and Drug Administration Staff (final, 2026-09-02, Docket FDA-2024-D-2511), FDA Guidance: Dental Composite Resin Devices - Premarket Notification (510(k)) Submissions: Guidance for Industry and Food and Drug Administration Staff (final, 2026-09-02, Docket FDA-2024-D-2511), FDA Guidance: Dental Composite Resin Devices - Premarket Notification (510(k)) Submissions: Guidance for Industry and Food and Drug Administration Staff (final, 2026-09-02, Docket FDA-2024-D-2511)

| | A | B |
|---|---|---|
| initial validation | citation_invalid | citation_invalid |
| repair | invalid_citations_removed | invalid_citations_removed |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 1 | 1 |
| generated tokens | 141 | 107 |
| total ms | 13612.43 | 10477.72 |
| flags | - | citation_mismatch |

```diff
--- A
+++ B
@@ -1 +1 @@
-The FDA guidance FDA-2024-D-2511 recommends that dental composite resin devices must be submitted as Premarket Notification (510(k)) submissions, with specific requirements for device description, predicate comparison, labeling, shelf life, biocompatibility, and non-clinical performance testing. These requirements are outlined in the guidance document, which is non-binding and issued on September 2, 2026. The document supersedes previous submissions from October 26, 2005, and includes instructions for submitting comments and receiving copies. If applicable, the guidance limits the scope to dental composite resin devices and their submissions. [1]
+The FDA guidance FDA-2024-D-2511 recommends that dental composite resin devices must be submitted with a Premarket Notification (510(k)) and include specific recommendations for device description, predicate comparison, labeling, shelf life, biocompatibility, and non-clinical performance testing. These recommendations are non-binding and do not establish rights for any person. If applicable, the guidance limits the scope to dental composite resin devices and applies to industry and staff. [1]
```

## S5-080 (definition): What is the capital of France?

Sources (same retrieval): FDA Guidance: Recommendations to Reduce the Possible Risk of Transmission of Creutzfeldt-Jakob Disease and Variant Creutzfeldt-Jakob Disease by Blood and Blood Components: Guidance for Industry (final, 2022-05-23, Docket FDA-2012-D-0307), FDA Guidance: Contents of a Complete Submission for the Evaluation of Proprietary Names (final, 2016-04-11, Docket FDA-2008-D-0592), 21 CFR 1143.5(a)(2)(iv)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 1 | 1 |
| generated tokens | 11 | 11 |
| total ms | 2818.19 | 2901.17 |
| flags | question_echo, scope_mismatch, uncertainty_not_disclosed | scope_mismatch, uncertainty_not_disclosed |

```diff
--- A
+++ B
@@ -1 +1 @@
-What is the capital of France? [1]
+The capital of France is Paris. [1]
```

## S5-081 (explanation): Who wrote Hamlet?

Sources (same retrieval): FDA Guidance: Guidance for Industry: Acrylamide in Foods (final, 2016-03-11, Docket FDA-2013-D-0715)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | False |
| citations | 0 | 0 |
| generated tokens | 15 | 60 |
| total ms | 2775.39 | 5869.59 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-The available regulatory sources do not provide enough information to answer this question.
+The available regulatory sources do not provide enough information to answer this question. The question is about who wrote *Hamlet*, but the provided evidence only contains information related to acrylamide in foods and does not mention any author of *Hamlet*. The question is not addressed by the evidence.
```

## S5-082 (definition): What is the boiling point of water in Celsius?

Sources (same retrieval): FDA Guidance: Draft Guidance for Industry: Hazard Analysis and Risk-Based Preventive Controls for Human Food (draft, 2024-01-30, Docket FDA-2016-D-2343), FDA Guidance: Draft Guidance for Industry: Evaluating Alternate Curricula for the Standards for the Growing, Harvesting, Packing, and Holding of Produce for Human Consumption (draft, 2019-06-03, Docket FDA-2019-D-2131), 21 CFR 161.130(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 1 | 0 |
| generated tokens | 33 | 29 |
| total ms | 4702.81 | 4483.34 |
| flags | question_echo, scope_mismatch, uncertainty_not_disclosed | - |

```diff
--- A
+++ B
@@ -1 +1 @@
-What is the boiling point of water in Celsius? [1] The boiling point of water is 100°C at standard atmospheric pressure. [1]
+The available regulatory sources do not provide enough information to answer this question. The sources provided do not address the boiling point of water in Celsius.
```

## S5-083 (out_of_scope): What does the EU Medical Device Regulation require for UDI?

Sources (same retrieval): FDA Guidance: Medical Device Data Systems, Medical Image Storage Devices, and Medical Image Communications Devices: Guidance for Industry and Food and Drug Administration Staff (final, 2022-09-28, Docket FDA-2014-D-0798), FDA Guidance: Medical Device Data Systems, Medical Image Storage Devices, and Medical Image Communications Devices: Guidance for Industry and Food and Drug Administration Staff (final, 2022-09-28, Docket FDA-2014-D-0798)

| | A | B |
|---|---|---|
| initial validation | citation_invalid | None |
| repair | invalid_citations_removed | None |
| final validation | valid | None |
| coverage action | answer | refuse_out_of_scope |
| machine checks pass (final) | False | True |
| citations | 1 | 0 |
| generated tokens | 130 | None |
| total ms | 11909.85 | 773.33 |
| flags | citation_mismatch, scope_mismatch, uncertainty_not_disclosed | - |

```diff
--- A
+++ B
@@ -1,5 +1 @@
-The EU Medical Device Regulation requires that UDI (Unique Device Identification) must be assigned to a device under the following conditions: 
-- Non-Device-MDDS must be assigned to a device under section 201(h) of the FD&C Act, and UDI must be assigned to a device that is a hardware function intended to assist software functions. 
-- Device-MDDS must be assigned to a device under section 201(h) of the FD&C Act, and UDI must be assigned to a device that is a hardware function intended to assist the software functions listed in the recommendations. 
-
-[1]
+This question is outside what Regulus AI can answer. Regulus AI answers from U.S. FDA regulations (21 CFR) and FDA guidance only, and the question asks about a non-U.S. framework (EU); no source for it is available, so no answer is given.
```

## S5-084 (requirement): What does 21 CFR 820.10(b)(3) require, and what is the population of Paris?

Sources (same retrieval): 21 CFR 820.10(b)(3), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | unsupported | valid |
| repair | extractive_replacement | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | True | True |
| citations | 2 | 1 |
| generated tokens | 64 | 43 |
| total ms | 5688.22 | 4162.41 |
| flags | - | - |

```diff
--- A
+++ B
@@ -1,2 +1,2 @@
-The generated answer could not be validated against the retrieved regulatory evidence. The verified text of the requested provision(s) follows.
-21 CFR 820.10(b)(3) (eCFR, binding, verbatim): (3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [1].
+21 CFR 820.10(b)(3) requires that the manufacturer must notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter. [1]
+Not answered: "what is the population of Paris". The available regulatory sources do not cover this part of the question.
```

## S5-090 (citation_lookup): Cite the provision that requires manufacturers to notify FDA of complaints meeting part 803 criteria.

Sources (same retrieval): 21 CFR 803.10(a), 21 CFR 803.11(a), 21 CFR 803.12(a), 21 CFR 803.13, 21 CFR 803.15(a), 21 CFR 803.16, 21 CFR 803.17, 21 CFR 803.18(a), 21 CFR 803.19(a), 21 CFR 803.1(a), 21 CFR 803.20(a), 21 CFR 803.21(a), 21 CFR 803.22(a), 21 CFR 803.23(a), 21 CFR 803.30(a), 21 CFR 803.32, 21 CFR 803.33(a), 21 CFR 803.3, 21 CFR 803.9(a)

| | A | B |
|---|---|---|
| initial validation | evidence_mismatched | valid |
| repair | mismatched_statements_replaced | None |
| final validation | evidence_mismatched | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 19 | 19 |
| generated tokens | 113 | 32 |
| total ms | 21841.14 | 7907.63 |
| flags | citation_mismatch | - |

```diff
--- A
+++ B
@@ -1,2 +1 @@
-The provision that requires manufacturers to notify FDA of complaints meeting part 803 criteria is [1]. If you are a device user facility, you must submit reports (described in subpart C of this part), as follows: [1].
-21 CFR part 803 (eCFR, binding, verbatim): (a) If you are a device user facility, you must submit reports (described in subpart C of this part), as follows: [1]. (a) If you are a manufacturer or importer, you must submit reports of individual adverse events to FDA in an electronic format in accordance with § 803.12(a) and § 803.20, unless granted an exemption under § 803.19 [2]. (a) Manufacturers and importers must submit initial and supplemental or followup reports to FDA in an electronic format that FDA can process, review, and archive [3].
+21 CFR 803.10(a) requires manufacturers to notify the FDA of complaints meeting part 803 criteria. [1]
```

## S5-091 (citation_lookup): Which provision of 21 CFR 820.10 refers to part 806?

Sources (same retrieval): 21 CFR 820.10, 21 CFR 820.10(a), 21 CFR 820.10(b), 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10(c), 21 CFR 820.10(c)(1), 21 CFR 820.10(c)(2), 21 CFR 820.10(d), 21 CFR 820.10(e), 21 CFR 806.10(a), 21 CFR 806.1(a), 21 CFR 806.20(a), 21 CFR 806.2, 21 CFR 806.30, 21 CFR 806.40(a)

| | A | B |
|---|---|---|
| initial validation | evidence_mismatched | evidence_mismatched |
| repair | mismatched_statements_replaced+appended_missing_items | mismatched_statements_replaced |
| final validation | evidence_mismatched | evidence_mismatched |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 18 | 18 |
| generated tokens | 629 | 209 |
| total ms | 100240.7 | 25883.42 |
| flags | citation_mismatch, missing_condition, repeated_content | citation_mismatch |

```diff
--- A
+++ B
@@ -1,34 +1,2 @@
-21 CFR 820.10(a) [2] 
-A manufacturer subject to this part as described by § 820.1(a) must: 
-
-21 CFR 820.10(b) [3] 
-Comply, as appropriate, with the other applicable regulatory requirements in this title, including, but not limited to, the following, to fully comply with the listed ISO 13485 Clause: 
-
-21 CFR 820.10(b)(1) [4] 
-For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter. 
-
-21 CFR 820.10(b)(2) [5] 
-For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable. 
-
- 
-
-21 CFR 820.10(c) [8] 
-Manufacturers of class II, class III, and those class I devices listed in paragraph (c)(1) of this section and table 1 to paragraph (c)(2) of this section must comply with the requirements in Design and Development, Clause 7.3 and its Subclauses in ISO 13485. The class I devices are as follows: 
-
-21 CFR 820.10(c)(1) [9] 
-Devices automated with computer software; and 
-
-21 CFR 820.10(c)(2) [10] 
-The devices listed in the following table: 
-
-21 CFR 820.10(d) [11] 
-Devices that support or sustain life. Manufacturers of devices that support or sustain life, the failure of which to perform when properly used in accordance with instructions for use provided in the labeling can be reasonably expected to result in a significant injury, must comply with the requirements in Traceability for Implantable Devices, Clause 7.5.9.2 in ISO 13485, in addition to all other applicable requirements in this part, as appropriate. 
-
-21 CFR 820.10(e) [12] 
-The failure to comply with any applicable requirement in this part renders a device adulterated under section 501(h) of the Federal Food, Drug, and Cosmetic Act. Such a device, as well as any person responsible for the failure to comply, is subject to regulatory action.
+21 CFR 820.10 refers to part 806. It requires manufacturers to document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter [1]. The manufacturer must also document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable [5]. The manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter [6]. Devices automated with computer software [9], the devices listed in the following table [10], and devices that support or sustain life [11] must comply with the requirements in Traceability for Implantable Devices, Clause 7.5.9.2 in ISO 13485, in addition to all other applicable requirements in this part, as appropriate [11] [1].
 21 CFR part 806 (eCFR, binding, verbatim): (a) Each device manufacturer or importer shall submit a written report to FDA of any correction or removal of a device initiated by such manufacturer or importer if the correction or removal was initiated: [13]. (a) This part implements the provisions of section 519(g) of the Federal Food, Drug, and Cosmetic Act (the act) requiring device manufacturers and importers to report promptly to the Food and Drug Administration (FDA) certain actions concerning device corrections and removals, and to maintain records of all corrections and removals regardless of whether such corrections and removals are required to be reported to FDA [14]. (a) Each device manufacturer or importer who initiates a correction or removal of a device that is not required to be reported to FDA under § 806.10 shall keep a record of such correction or removal [15].
-21 CFR 806.10(a) (eCFR, binding, verbatim): (a) Each device manufacturer or importer shall submit a written report to FDA of any correction or removal of a device initiated by such manufacturer or importer if the correction or removal was initiated: [13].
-21 CFR 806.1(a) (eCFR, binding, verbatim): (a) This part implements the provisions of section 519(g) of the Federal Food, Drug, and Cosmetic Act (the act) requiring device manufacturers and importers to report promptly to the Food and Drug Administration (FDA) certain actions concerning device corrections and removals, and to maintain records of all corrections and removals regardless of whether such corrections and removals are required to be reported to FDA [14].
-21 CFR 806.20(a) (eCFR, binding, verbatim): (a) Each device manufacturer or importer who initiates a correction or removal of a device that is not required to be reported to FDA under § 806.10 shall keep a record of such correction or removal [15].
-21 CFR 806.30 (eCFR, binding, verbatim): Each device manufacturer or importer required under this part to maintain records and every person who is in charge or custody of such records shall, upon request of an officer or employee designated by FDA and under section 704(e) of the act, permit such officer or employee at all reasonable times to have access to, and to copy and verify, such records and reports [17].
-21 CFR 806.40(a) (eCFR, binding, verbatim): (a) Any report submitted under this part is available for public disclosure in accordance with part 20 of this chapter [18].
```

## S5-100 (explanation): Explain every requirement in 21 CFR 820.10(b)(1) through (b)(4) in plain English, one by one.

Sources (same retrieval): 21 CFR 820.10(b)(1), 21 CFR 820.10(b)(2), 21 CFR 820.10(b)(3), 21 CFR 820.10(b)(4), 21 CFR 820.10(b)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | True |
| citations | 4 | 4 |
| generated tokens | 216 | 176 |
| total ms | 19624.08 | 16373.74 |
| flags | citation_mismatch | - |

```diff
--- A
+++ B
@@ -1,4 +1,7 @@
-[1] (1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter.  
-[2] (2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable.  
-[3] (3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter.  
-[4] (4) For Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance with the requirements of part 806 of this chapter.
+The requirements in 21 CFR 820.10(b)(1) require that manufacturers document a system to assign unique device identification to the medical device in accordance with part 830 of this chapter. [1]
+
+The requirements in 21 CFR 820.10(b)(2) require that manufacturers document procedures for traceability in accordance with part 821 of this chapter, if applicable. [2]
+
+The requirements in 21 CFR 820.10(b)(3) require that manufacturers notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter. [3]
+
+The requirements in 21 CFR 820.10(b)(4) require that manufacturers handle advisory notices in accordance with part 806 of this chapter. [4]
```

## S5-101 (explanation): Describe 21 CFR 101.3(b)(1), (b)(2) and (b)(3) and 21 CFR 101.54(a)(1) through (a)(3).

Sources (same retrieval): 21 CFR 101.3(b)(1), 21 CFR 101.3(b)(2), 21 CFR 101.3(b)(3), 21 CFR 101.54(a)(1), 21 CFR 101.54(a)(2), 21 CFR 101.54(a)(3), 21 CFR 101.3(b), 21 CFR 101.54(a)

| | A | B |
|---|---|---|
| initial validation | valid | valid |
| repair | None | None |
| final validation | valid | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 6 | 6 |
| generated tokens | 357 | 334 |
| total ms | 33550.92 | 49079.0 |
| flags | citation_mismatch, repeated_content | - |

```diff
--- A
+++ B
@@ -1,6 +1,6 @@
-[1] 21 CFR 101.3(b)(1) [1]: The name now or hereafter specified in or required by any applicable Federal law or regulation; or, in the absence thereof, the common or usual name of the food; or, in the absence thereof, an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
-[2] 21 CFR 101.3(b)(2) [2]: The claim uses one of the terms defined in this section in accordance with the definition for that term.  
-[3] 21 CFR 101.3(b)(3) [3]: An appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
-[4] 21 CFR 101.54(a)(1) [4]: The food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.  
-[5] 21 CFR 101.54(a)(2) [5]: The claim is made in accordance with the general requirements for nutrient content claims in § 101.13; and  
-[6] 21 CFR 101.54(a)(3) [6]: The food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.
+21 CFR 101.3(b)(1) [1]: The name now or hereafter specified in or required by any applicable Federal law or regulation; or, in the absence thereof, the common or usual name of the food; or, in the absence thereof, an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
+21 CFR 101.3(b)(2) [2]: The common or usual name of the food; or, in the absence thereof, an appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
+21 CFR 101.3(b)(3) [3]: An appropriately descriptive term, or when the nature of the food is obvious, a fanciful name commonly used by the public for such food.  
+21 CFR 101.54(a)(1) [4]: The claim uses one of the terms defined in this section in accordance with the definition for that term.  
+21 CFR 101.54(a)(2) [5]: The claim is made in accordance with the general requirements for nutrient content claims in § 101.13; and  
+21 CFR 101.54(a)(3) [6]: The food for which the claim is made is labeled in accordance with § 101.9, § 101.10, or § 101.36, as applicable.
```

## S5-111 (explanation): Explain §820.10(b)(3).

Sources (same retrieval): 21 CFR 820.10(b)(3), 21 CFR 820.10(b), FDA Guidance: Quality Management System Information for Certain Premarket Submission Reviews: Draft Guidance for Industry and Food and Drug Administration Staff (draft, 2025-10-27, Docket FDA-2025-D-4051)

| | A | B |
|---|---|---|
| initial validation | citation_invalid | valid |
| repair | invalid_citations_removed+truncation_noted | None |
| final validation | incomplete | valid |
| coverage action | answer | answer |
| machine checks pass (final) | False | False |
| citations | 2 | 1 |
| generated tokens | 256 | 153 |
| total ms | 20721.73 | 13500.51 |
| flags | excessive_length, missing_condition | - |

```diff
--- A
+++ B
@@ -1,2 +1 @@
-[1] §820.10(b)(3) requires that the manufacturer must notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter. [3] If applicable, the manufacturer must also document a system to assign a UDI to the subject device and utilization of UDI to identify devices accurately from manufacturing through distribution to patient use, as required by 21 CFR 820.10(b)(1) and 21 CFR part 830. The submitter should also document a system to assign UDI to the medical device in accordance with the requirements of 21 CFR 820.10(b)(2), 21 CFR part 821, and Subclause 7.5.9.1. The process by which the submitter will notify FDA of complaints that meet the reporting criteria of 21 CFR 820.10(b)(3) and 21 CFR part 803, as set forth at Subclause 8.2.3, is required. The manufacturer must also include a summary of the MDR procedure(s) and explain how this process is linked
-(Incomplete: generation stopped at the token limit before this answer finished, so wording after this point is missing.)
+The requested provision requires that manufacturers notify the FDA of complaints that meet the reporting criteria of part 803 of this chapter, as set forth in Subclause 8.2.3 of 21 CFR 820.10(b)(3). This notification must be documented in accordance with the requirements of 21 CFR 820.10(b)(1) and 21 CFR part 830, as well as the MDR procedure(s) and their linkage to the processes described in 21 CFR 820.10(b)(2) and 21 CFR part 821. The requirement applies to devices and persons as specified in the sub-requirements. [1]
```
