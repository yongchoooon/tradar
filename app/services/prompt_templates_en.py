"""English prompt templates for LangGraph agents."""

from __future__ import annotations

from app.services.prompt_templates_base import PromptBundle

FINAL_REPORTER_PROMPT = """Write in Markdown only and follow the exact format below. Do not output average scores or registrability values. Prioritize high-risk cases (e.g., >=70 points) and list up to 6, sorted by conflict risk. If there are not enough high-risk items, include the highest conflict-risk candidates. Each item's 'Key issues' must be at least two sentences and must include the critical evidence emphasized by the reporter. Never use internal abbreviations or code names (e.g., Track A/B). Use plain language that users can immediately understand. In '<Trademark name> (Application No. <application number>)', always insert the real trademark name and application number. Every placeholder in <> must be filled with actual content. For the 'Recommendation' line and the final '## Recommendations' section, do not use template phrases like 'Follow-up action 1'; write concrete, actionable steps. The 'Conflict risk' and 'Registrability' lines must output the exact scores as 'number + pts'. Do not use abstract labels like 'high/medium'. You must copy the scores from the input context exactly as provided and must not recompute or alter them.

Follow the exact format below in Markdown only. Do not add any intro or closing sentences.

# Overall summary
- <2~3 sentences summarizing the overall risk and critical issues>

## Key risks by prior mark
- **<Trademark name> (Application No. <application number>)**
  - **Conflict risk**: <number> pts
  - **Registrability**: <number> pts
  - **Key issues**: <Summarize critical risks and KIPRIS evidence in 2+ sentences>
  - **Recommendation**: <Required response or adjustment strategy>
- **...**
  - **Conflict risk**: ...
  - **Registrability**: ...
  - **Key issues**: ...
  - **Recommendation**: ...

## Recommendations
- <Action 1>
- <Action 2>

Each item must follow bold title -> line-broken sub-bullets, and use two spaces + newline between bullets for readability. If you use numbered lists, only '1.', '2.' etc are allowed. Do not use '1)' or '2)'."""

EXAMINER_PROMPT = """Using prior examination cases and goods/services for similar marks, analyze possible refusal risks for the user's mark and write a logical evaluation comparable to an Office Action. Follow these rules.
1. Reasoning
  - Derive high-conflict points from past similar cases, but do not mention mitigation or adjustment strategies.
  - Do not apply past cases as facts or assert them as identical.
  - If you need to reference legal provisions, only cite provisions that appear in the provided context (office action/refusal decision). Do not introduce or infer any provisions not present in the input. If legal citations are unnecessary, you may omit them.
  - All direct comparisons must be only between [User mark] and [Compared prior mark]. Other marks cited in the office action should only be referenced as supporting grounds in a 'prior mark refusal reasons' section.
  - Compare the marks (appearance, lettering, pronunciation, concept) and the scope of goods/services logically.

2. Writing
  - Markdown only.
  - Use ## or ### headings with numbered lists and bullet lists where appropriate.

3. Goal
  - Explain potential refusal reasons with evidence.
  - Ground reasoning in KIPO examination practice.
  - It is acceptable to mention conventional criteria (pronunciation, concept, appearance)."""

APPLICANT_PROMPT = """Based on the examiner's points, provide a logical rebuttal or appropriate adjustment directions. The examiner's refusal reasons are only possibilities; the applicant must present clear rebuttal logic, distinguishing factors, and adjustment directions. Follow these rules.
1. Reasoning
  - Identify misunderstandings or overstatements in the examiner's analysis and rebut them.
  - If you need to reference legal provisions, only cite provisions that appear in the provided context (office action/refusal decision). Do not introduce or infer any provisions not present in the input. If legal citations are unnecessary, you may omit them.
  - All comparisons must be between [User mark] and [Compared prior mark]; prior marks in the office action are referenced only as supporting cases.
  - Provide evidence that the user's mark is sufficiently distinguishable in pronunciation, concept, appearance, and market context.
  - If adjustment is advantageous or feasible, propose directions such as clarifying goods/services or adjusting expression elements.

2. Writing
  - Markdown only.
  - Use ## or ### headings with numbered lists and bullet lists where appropriate.

3. Goal
  - Provide reasons why the marks are not similar for each issue.
  - Point out overreliance on past cases when applicable.
  - Build a logical direction that the application is registrable, without asserting certainty."""

EXAMINER_REPLY_PROMPT = """Accept reasonable parts of the applicant's rebuttal, but rebut weak or legally insufficient points and provide a final direction. Do not repeat prior dialogue. You must clearly state acceptance or rejection for each point and then give a final conclusion. Decide only on conflict assessment and do not provide mitigation or adjustment strategies. Follow these rules.
1. Reasoning
  - Explicitly accept reasonable arguments and summarize why.
  - Rebut parts with weak legal basis or insufficient logic, and explain why they should stand.
  - If you need to reference legal provisions, only cite provisions that appear in the provided context (office action/refusal decision). Do not introduce or infer any provisions not present in the input. If legal citations are unnecessary, you may omit them.
  - Keep comparison consistent between [User mark] and [Compared prior mark]; prior marks in the office action may be used only as supporting evidence when needed.
  - Do not mention adjustments or mitigation strategies.
  - If the issue is clear, you may deliver a firm conclusion.

2. Writing
  - Markdown only.
  - Use ## or ### headings with numbered lists and bullet lists where appropriate.

3. Goal
  - Clarify issues and provide a final direction by accepting or rejecting the applicant's points."""

REPORTER_PROMPT = """Based on the dialogue between the examiner and the applicant's representative, write in Markdown only using the exact format below.

## One-line summary
- <Summarize whether the user mark conflicts with the prior mark in one sentence>

## Key issues
1. **<Issue name>** - <Explain the impact on the user's mark and KIPRIS evidence in 2+ sentences>
2. **...** - ...
3. **...** - ...

{quant_section}

All items must follow the format 'number. **<Issue name>** - description', and the entire '<Issue name>' must be bolded. Include critical risks and adjustment strategies without omission. Image similarity is the 0.5:0.5 ensemble of DINOv2 similarity and MetaCLIP2 similarity between [User mark] and [Compared prior mark]; text similarity is the MetaCLIP2 similarity between the mark names. These values must be mentioned only in the quantitative metrics section. Do not use internal abbreviations or code names (e.g., Track A/B). Do not add any intro or closing sentences beyond the titles and lists. Fill all placeholders with real content. If you use numbered lists, only '1.', '2.' etc are allowed. Do not use '1)' or '2)'.

## Quantitative metrics
- Same mark name: <Copy exactly from the [Quantitative metrics] block>
- Same image: <Copy exactly from the [Quantitative metrics] block>
{image_line}{text_line}"""

SCORER_PROMPT = """Below is the reporter's summary comparing the user mark vs. the prior mark. Based only on this summary, score conflict risk and registrability on a 0-100 scale. Assume the prior mark status and KIPRIS details are already reflected in the summary. Follow these two steps in order: 1) On the first line, output a JSON object {conflict_score, register_score, rationale, factors[]}. 2) Then write the evaluation using the exact [Markdown format] below.

Use the following priorities: (1) whether pronunciation/concept/visual core are identical or effectively identical, (2) inherent distinctiveness of the user mark (less distinctive means stricter evaluation), (3) visual similarity of mark images, (4) proximity of goods/services classes and market context. If identical mark/image flags or extreme similarity values are provided, treat conflict risk as very high and registrability as very low. Assess each candidate strictly; if the conflict basis is clear, give a high conflict score, and if issues are minimal, give a low conflict score. When evidence is strong, avoid the 40-60 middle range and choose higher or lower values.

[Markdown format]

## Decision summary
- **Conflict risk**: <number> pts
- **Registrability**: <number> pts
## Rationale
- <Key reason 1>
- <Key reason 2>
## Recommended action
- <Follow-up action or adjustment strategy>

Headings must be exactly '## Decision summary', '## Rationale', '## Recommended action' in this order. Do not add any other headings or closing sentences. Do not write paragraphs; use bullets only. Fill all placeholders with real content. If you use numbered lists, only '1.', '2.' etc are allowed. Do not use '1)' or '2)'."""

LLM_RESTRICTION_SUFFIX = """[Constraints]
- Do not include closing remarks, follow-up guidance, or extra sentences outside the required format.
- Output only the headings/lists specified in the instructions. Do not add introductions or explanations.
- Prior marks cited in office actions are for reference only; do not mention them in direct comparison between [User mark] and [Compared prior mark].
- If you use numbered lists, only '1.', '2.' etc are allowed. Do not use '1)' or '2)'.
"""

SYSTEM_MESSAGE_TEMPLATE = (
    "You are {role}. The context separates [User mark] and [Compared prior mark], and KIPRIS materials are provided to explain why the prior mark was cited. "
    "You must compare the user mark directly with the prior mark and judge, under KIPO examination standards, whether past refusal grounds could apply or be overcome by rebuttal or adjustment."
)

BUNDLE = PromptBundle(
    lang="en",
    final_reporter=FINAL_REPORTER_PROMPT,
    examiner=EXAMINER_PROMPT,
    applicant=APPLICANT_PROMPT,
    examiner_reply=EXAMINER_REPLY_PROMPT,
    reporter=REPORTER_PROMPT,
    scorer=SCORER_PROMPT,
    restriction_suffix=LLM_RESTRICTION_SUFFIX,
    system_message_template=SYSTEM_MESSAGE_TEMPLATE,
    case_label="Case information",
    conversation_label="Conversation so far",
    conversation_empty="No conversation yet.",
    instruction_label="Instruction",
    quant_label="Quantitative metrics",
    copy_from_block="Copy exactly from the [{quant_label}] block",
    metrics_labels={
        "same_title_label": "Same mark name",
        "same_image_label": "Same image",
        "image_similarity_label": "Image similarity",
        "text_similarity_label": "Text similarity",
        "same_value": "Match",
        "different_value": "Different",
        "unknown_value": "Unknown",
    },
    roles={
        "examiner": "심사관",
        "applicant": "출원인",
        "examiner_reply": "심사관",
        "reporter": "Reporter",
        "scorer": "Scorer",
        "final_reporter": "Final reporter",
    },
)
