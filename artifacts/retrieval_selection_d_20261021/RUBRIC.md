# Guidance relevance rubric (fixed before any judgement)

You see one QUESTION and one FDA guidance PASSAGE: its document title, and the passage text exactly as it would appear
in the evidence given to the answering system, possibly cut short. Judge only whether this passage would help a
regulatory expert answer this question correctly. Do not judge writing quality. Do not use any other knowledge of
what the correct answer is.

**R2, directly relevant.**
- The passage states FDA guidance, a requirement or a recommendation on the specific subject the question asks
  about, and that subject applies to the question's product category: cosmetics, when the question is about
  cosmetics.
- An expert answering this question would cite the passage, or rely on its content.

**R1, related but not needed.**
- Same broad topic, such as colour additives, labeling, lead or registration, but a different product category (drug,
  food, animal food, device, biologic, tobacco) or a different aspect.
- Or background that would not change the answer.
- An expert would not cite it for this question, though it is not misleading.

**R0, not relevant.**
- A different subject, product domain or programme.
- Or only shared vocabulary.
- Or text that would mislead an answer to this question.

**Rules:**
- When unsure between two levels, choose the lower one only if nothing in the passage bears on the question's specific
  subject.
- A passage cut short is judged on the text shown.
- Output one label per item: R2, R1 or R0, with a short reason of at most 25 words naming what in the passage makes it
  so.
