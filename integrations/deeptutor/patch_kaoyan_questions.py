"""Apply the deliberately narrow v1.7.1 question-pipeline extension."""
from pathlib import Path
import sys


def transform(path, replacements):
    source = path.read_text(encoding='utf-8')
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError(f'DeepTutor v1.7.1 anchor changed: {path.name}: {old[:100]}')
        source = source.replace(old, new, 1)
    path.write_text(source, encoding='utf-8')


def apply(root):
    base = root / 'agents' / 'question'
    transform(base / 'pipeline.py', [
        ('    CHOICE = "choice"', '    CHOICE = "choice"\n    MULTIPLE_CHOICE = "multiple_choice"'),
        ('frozenset({QuestionType.CHOICE.value})', 'frozenset({QuestionType.CHOICE.value, QuestionType.MULTIPLE_CHOICE.value})'),
        ('        messages = self._build_system_user_messages(\n            system_prompt, user_prompt, image_attachments=image_attachments\n        )\n\n        tool_schemas',
         '''        if "kaoyan_quote" in (context.user_message or ""):
            user_prompt += ("\\n本轮考研出题原始要求及逐字资料：\\n" + context.user_message
                            + "\\nFINISH 的 JSON 必须包含 kaoyan_quote；written 还必须包含 kaoyan_rubric。")
        messages = self._build_system_user_messages(
            system_prompt, user_prompt, image_attachments=image_attachments
        )

        tool_schemas'''),
        ('        if expected_type == QuestionType.CHOICE.value:', '        if expected_type in _TYPES_WITH_OPTIONS:'),
        ('            if clean and normalized["correct_answer"]:',
         '''            if expected_type == QuestionType.MULTIPLE_CHOICE.value:
                raw = payload.get("correct_answer")
                keys = raw if isinstance(raw, list) else re.split(r"[\\s,，、]+", str(raw or "").strip())
                normalized["correct_answer"] = ",".join(str(k).strip().upper() for k in keys if str(k).strip())
            elif clean and normalized["correct_answer"]:'''),
        ('        if qtype == QuestionType.CHOICE.value:',
         '''        if qtype == QuestionType.MULTIPLE_CHOICE.value:
            keys = correct.split(",")
            if not isinstance(options, dict) or set(options) != set(_CHOICE_KEYS):
                issues.append("choice_options_must_be_a_to_d")
            if not 2 <= len(keys) <= 4 or len(set(keys)) != len(keys) or not set(keys) <= set(_CHOICE_KEYS):
                issues.append("multiple_choice_requires_two_to_four_unique_option_keys")
        elif qtype == QuestionType.CHOICE.value:'''),
        ('            metadata={"issues": issues} if issues else {},',
         '''            metadata={**({"issues": issues} if issues else {}),
                      "kaoyan_quote": str(payload.get("kaoyan_quote") or "").strip()[:600],
                      "kaoyan_rubric": [item.strip() for item in payload["kaoyan_rubric"][:12]
                                        if isinstance(item, str) and item.strip()]
                                       if isinstance(payload.get("kaoyan_rubric"), list) else []},'''),
    ])
    transform(base / 'prompts' / 'zh' / 'pipeline.yaml', [
        ('choice|concept|fill_in_blank|short_answer|written|coding', 'choice|multiple_choice|concept|fill_in_blank|short_answer|written|coding'),
        ('       - ``choice``——4 选 1 选择题（A/B/C/D），一个正确答案。',
         '       - ``choice``——4 选 1 选择题（A/B/C/D），一个正确答案。\n       - ``multiple_choice``——四个选项，二至四个正确选项。'),
        ('"question_type": "choice" | "concept"', '"question_type": "choice" | "multiple_choice" | "concept"'),
        ('    - 如果 ``question_type`` 是 ``concept``：',
         '    - ``multiple_choice`` 使用恰好四个选项，正确答案以逗号分隔的选项键返回，例如 "A,C"。\n'
         '    - 考研题若给了资料，输出 ``kaoyan_quote``（逐字原文）；分析题还要输出 ``kaoyan_rubric``（评分要点字符串数组）。\n'
         '    - 如果 ``question_type`` 是 ``concept``：'),
        ('    - 返回 JSON 只包含字段：question_type, question, options, correct_answer, explanation。',
         '    - 多选使用四个选项及逗号分隔的至少两个正确键，例如 "A,C"。\n'
         '    - 返回 JSON 只包含字段：question_type, question, options, correct_answer, explanation, kaoyan_quote, kaoyan_rubric。'
         ' 原文引文和分析题评分要点必须保留。'),
    ])


if __name__ == '__main__':
    apply(Path(sys.argv[1]))
