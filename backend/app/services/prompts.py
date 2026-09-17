# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 备课 Prompt 模板
# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 追加 AIGC 错题分析 Prompt（3.2.7）
"""五类备课内容（教案/课件/习题/案例/试题）的 Prompt 构造 + 错题分析 Prompt。

内容合规要求见设计文档 5.4 节：生成内容须符合教学规范与社会主义核心价值观。
"""

from __future__ import annotations

import json

from app.models.lesson import CONTENT_TYPES

# 教案/案例类 → Markdown；课件/习题/试题类 → JSON
MARKDOWN_TYPES = ("教案", "案例")
JSON_TYPES = ("课件", "习题", "试题")

# 题量规格：题型 -> (题量, 每题分值)。模板中的「题量要求」整句由 _spec_line 生成，
# 避免手写文案与分值各说各话（曾出现试题写「总分 100 分」但分项相加只有 90 分）。
# 习题规格来自工单17：单选10 + 多选5 + 判断5 + 简答3。
DEFAULT_EXERCISE_SPEC: dict[str, tuple[int, int]] = {
    "单选": (10, 2),
    "多选": (5, 4),
    "判断": (5, 2),
    "简答": (3, 10),
}
# 月考试题规格，分项相加恰为 100 分
DEFAULT_EXAM_SPEC: dict[str, tuple[int, int]] = {
    "单选": (10, 4),
    "多选": (5, 4),
    "判断": (5, 2),
    "简答": (3, 10),
}


def _spec_line(spec: dict[str, tuple[int, int]]) -> str:
    """由规格生成「题量要求」整句，题量与总分一并算出。"""
    parts = [f"{qtype} {count} 道（每题 {score} 分）" for qtype, (count, score) in spec.items()]
    total_count = sum(count for count, _ in spec.values())
    total_score = sum(count * score for count, score in spec.values())
    return f"{'、'.join(parts)}，共 {total_count} 道，总分 {total_score} 分"

SYSTEM_PROMPT = """你是一位资深的高职院校专业课教师与教学设计专家，正在为「人工智能」相关专业课程编写教学材料。

硬性要求：
1. 内容必须符合我国教育方针与社会主义核心价值观，政治导向正确，不得出现任何违法违规或不当内容。
2. 紧密结合高职院校学生的知识基础与就业导向，理论够用、突出实践，避免照搬本科教材的过度理论化。
3. 专业术语准确，涉及算法与公式时表述严谨。
4. 严格按用户要求的输出格式作答，不要输出任何与格式要求无关的寒暄或说明。"""


def _common_context(
    subject: str | None,
    course_name: str,
    chapter: str | None,
    knowledge_points: list[str],
    difficulty: str | None,
    objectives: list[str],
) -> str:
    """拼装各类型共用的课程上下文。"""
    lines = [f"学科/专业：{subject or '人工智能'}", f"课程名称：{course_name}"]
    if chapter:
        lines.append(f"章节：{chapter}")
    if knowledge_points:
        lines.append(f"涉及知识点：{'、'.join(knowledge_points)}")
    if difficulty:
        lines.append(f"难度要求：{difficulty}")
    if objectives:
        lines.append(f"教学目标：{'；'.join(objectives)}")
    return "\n".join(lines)


def build_messages(
    content_type: str,
    *,
    subject: str | None,
    course_name: str,
    chapter: str | None,
    knowledge_points: list[str],
    difficulty: str | None,
    objectives: list[str],
    extra: str | None = None,
) -> list[dict]:
    """根据内容类型构造 messages。extra 为用户自定义补充要求。"""
    if content_type not in CONTENT_TYPES:
        raise ValueError(f"不支持的内容类型：{content_type}，可选 {'/'.join(CONTENT_TYPES)}")

    context = _common_context(
        subject, course_name, chapter, knowledge_points, difficulty, objectives
    )
    if extra:
        context += f"\n补充要求：{extra}"

    # 五个模板共用一次 format：非题目类模板不含 spec 占位符，多余的关键字参数会被忽略
    user_prompt = _USER_TEMPLATES[content_type].format(
        context=context,
        exercise_spec=_spec_line(DEFAULT_EXERCISE_SPEC),
        exam_spec=_spec_line(DEFAULT_EXAM_SPEC),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------- 各类型模板

_TEMPLATE_LESSON_PLAN = """请为以下课程编写一份完整、可直接使用的**教案**。

{context}

请使用 Markdown 格式输出，依次包含以下部分（用二级标题）：
## 一、教学目标
分「知识目标 / 能力目标 / 素质目标」三方面，每方面 2~3 条，可测量、可评价。
## 二、教学重点与难点
分别说明，并简述突破难点的思路。
## 三、学情分析
结合高职学生的知识基础与常见认知障碍简要分析。
## 四、教学准备
所需教具、软件环境、实训资源。
## 五、教学过程
以表格形式呈现，列为：教学环节 | 教师活动 | 学生活动 | 时间分配 | 设计意图。
环节须包含导入、新知讲授、实践操作、总结提升、布置作业。总时长 90 分钟。
## 六、板书设计
## 七、作业布置
## 八、教学反思（预设）

直接输出教案正文，不要任何前言。"""

_TEMPLATE_COURSEWARE = """请为以下课程设计一套 **课件**（PPT 大纲）。

{context}

输出**严格的 JSON 数组**，不要输出任何解释文字、不要用 Markdown 代码块包裹。
数组中每个元素代表一页幻灯片，结构如下：
[
  {{
    "title": "幻灯片标题",
    "bullets": ["要点1", "要点2", "要点3"],
    "notes": "教师讲解备注（讲这一页时该说什么，2~3 句）"
  }}
]

要求：
1. 共 12~16 页，第 1 页为封面（标题为课程名与章节），最后一页为小结与思考题。
2. 每页要点 3~5 条，每条不超过 30 字，适合投屏展示。
3. 内容须覆盖教学重点，并在关键页的 notes 中给出举例或提问设计。"""

_TEMPLATE_EXERCISES = """请为以下课程编写一套 **课后习题**。

{context}

输出**严格的 JSON 数组**，不要输出任何解释文字、不要用 Markdown 代码块包裹。
题量要求：{exercise_spec}。
每道题的结构如下：
[
  {{
    "qtype": "单选",
    "stem": "题干内容",
    "options": ["A. 选项内容", "B. 选项内容", "C. 选项内容", "D. 选项内容"],
    "answer": "B",
    "analysis": "解析：说明为什么选 B，以及其余选项错在哪里",
    "knowledge_point": "本题对应的知识点名称",
    "score": 2,
    "difficulty": "简单"
  }}
]

要求：
1. qtype 只能是「单选」「多选」「判断」「简答」之一。
2. 判断题的 options 固定为 ["A. 正确", "B. 错误"]，answer 为 "A" 或 "B"。
3. 简答题 options 为 null，answer 为完整的参考答案要点。
4. 每道题必须给出 score（分值）与 analysis（解析），不得省略。
5. knowledge_point 必须从上下文【涉及知识点】中原样选取其一，不得改写、不得新造；
   若未提供【涉及知识点】，则填本题最贴切的一个知识点名称。
6. difficulty 只能是「简单」「中等」「困难」之一，不得使用"较难""容易""基础"等其他说法。"""

_TEMPLATE_CASE = """请为以下课程编写一个**教学案例**（企业级实战案例）。

{context}

请使用 Markdown 格式输出，依次包含以下部分（用二级标题）：
## 一、案例背景
描述真实的企业/行业场景，说明该场景在本专业岗位中的位置。
## 二、案例描述
给出具体业务问题、已知条件与数据，篇幅充实、细节可信。
## 三、问题分析
拆解问题，指出解决该问题需要用到本课程的哪些知识点。
## 四、解决方案
给出完整的解决思路与关键步骤，涉及技术选型时说明理由。
## 五、关键代码/操作示例
如适用，给出核心代码片段或实训操作步骤。
## 六、案例小结与延伸思考
总结方法论，并给出 3 个可供课堂讨论的延伸问题。

直接输出案例正文，不要任何前言。"""

_TEMPLATE_EXAM = """请为以下课程编写一套 **月考试题**。

{context}

输出**严格的 JSON 数组**，不要输出任何解释文字、不要用 Markdown 代码块包裹。
题量要求：{exam_spec}。
每道题的结构如下：
[
  {{
    "qtype": "单选",
    "stem": "题干内容",
    "options": ["A. 选项内容", "B. 选项内容", "C. 选项内容", "D. 选项内容"],
    "answer": "B",
    "analysis": "解析：说明解题思路与易错点",
    "knowledge_point": "本题对应的知识点名称",
    "score": 3,
    "difficulty": "中等"
  }}
]

要求：
1. 覆盖面须均匀分布在本章节各知识点上，不得集中于单一知识点。
2. 难度分布建议：简单 30% / 中等 50% / 困难 20%。
3. 每题必须给出 score（分值）、analysis（解析）与 knowledge_point，不得省略。
4. knowledge_point 必须从上下文【涉及知识点】中原样选取其一，不得改写、不得新造；
   若未提供【涉及知识点】，则填本题最贴切的一个知识点名称。
5. difficulty 只能是「简单」「中等」「困难」之一，不得使用"较难""容易""基础"等其他说法。"""


_USER_TEMPLATES: dict[str, str] = {
    "教案": _TEMPLATE_LESSON_PLAN,
    "课件": _TEMPLATE_COURSEWARE,
    "习题": _TEMPLATE_EXERCISES,
    "案例": _TEMPLATE_CASE,
    "试题": _TEMPLATE_EXAM,
}


# ---------------------------------------------------------------- 结构化内容组装

# ---------------------------------------------------------------- 错题分析（工单19）

# 工单19 原文把「Prompt 设计」列为核心，并点名要求输入包含
# {原题干、学生错误答案、正确答案、所属知识点、预设的常见错误类型}。
# 此处逐一对应，见设计文档 3.2.7 的输入字段表。
_TEMPLATE_MISTAKE = """一名高职院校学生在一道{subject}题目上答错了，请完成错题分析并给出变式题。

【原题干】
{stem}
{options_block}
【题型】{qtype}
【学生的错误答案】{user_answer}
【正确答案】{correct_answer}
【所属知识点】{kp_line}
{misconception_block}
【要求】
1. `analysis`：面向高职学生的**深入浅出**解析。先讲清这道题在考什么、正确思路怎么走，
   再指出本题的关键点。不要复述题干，不要写"本题考察了……"这类空话。
2. `misconception`：**错误原因诊断**——说清学生为什么会选错、脑子里可能是哪个概念拧了。
3. `misconception_type`：上一条归因**必须命中一个具体的错误类型**（不是"概念不清"这种笼统说法）。
   {misconception_rule}
4. 若上一步是"先推断"，把推断出的 3~5 个该知识点的常见错误类型填进 `inferred_misconceptions`。
5. `variant_questions`：{variant_count} 道**同知识点**变式题，用于巩固同一个薄弱点。
   变式题必须与本题**考法不同**（换情境、换问法或反向提问），不能只改数字。
6. 全面遵守上述 JSON 格式，不要输出任何额外文字。

严格按以下 JSON 结构输出：
{{
  "analysis": "深入浅出的题目解析",
  "misconception": "错误原因诊断",
  "misconception_type": "命中的错误类型",
  "inferred_misconceptions": ["推断出的常见错误类型"],
  "variant_questions": [
    {{"stem": "变式题题干", "options": ["A. 选项内容", "B. 选项内容"], "answer": "A", "analysis": "变式题解析"}}
  ]
}}"""


def build_mistake_messages(
    *,
    stem: str,
    options: list[str] | None,
    user_answer: str | None,
    correct_answer: str | None,
    kp_name: str | None,
    prereq_chain: list[str] | None = None,
    common_misconceptions: list[str] | None = None,
    qtype: str | None = None,
    subject: str = "人工智能",
    variant_count: int = 3,
) -> list[dict]:
    """组装错题分析的对话消息（设计文档 3.2.7）。

    **"预设的常见错误类型"有值就注入、为空就要求 LLM 先推断再归因**——这是本工单
    对 Prompt 的硬性要求里最容易漏的一条：知识点有预设时归因才有针对性，
    没有预设时若不给"先推断"这一步，模型会退化成"概念理解不清"这类无信息量的套话。
    """
    options = [opt for opt in (options or []) if str(opt).strip()]
    options_block = ("【选项】\n" + "\n".join(str(opt) for opt in options) + "\n") if options else ""

    kp_line = kp_name or "（未标注）"
    if prereq_chain:
        kp_line += f"（前置知识：{' → '.join(prereq_chain)}）"

    presets = [str(item).strip() for item in (common_misconceptions or []) if str(item).strip()]
    if presets:
        misconception_block = (
            "【该知识点已归纳的常见错误类型】\n"
            + "\n".join(f"- {item}" for item in presets)
            + "\n"
        )
        misconception_rule = (
            "从上面列出的「已归纳的常见错误类型」中**原样选取**一条填入，"
            "不得自造新的说法；确实都不贴切时才允许另拟，并在 `misconception_type` 中说明。"
        )
    else:
        misconception_block = ""
        misconception_rule = (
            "该知识点**尚未归纳**常见错误类型，请**先推断**该知识点在高职学生中 "
            "3~5 个典型错误类型（填入 `inferred_misconceptions`），**再据此归因**，"
            "`misconception_type` 必须取自你推断出的那几条之一。"
        )

    content = _TEMPLATE_MISTAKE.format(
        subject=subject,
        stem=stem,
        options_block=options_block,
        qtype=qtype or "（未标注）",
        user_answer=user_answer or "（未作答）",
        correct_answer=correct_answer or "（未提供）",
        kp_line=kp_line,
        misconception_block=misconception_block,
        misconception_rule=misconception_rule,
        variant_count=variant_count,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def build_content_payload(content_type: str, raw_text: str, parsed: dict | list | None) -> str:
    """把流式产出的原始文本与解析结果组装为 teaching_plans.content_json。

    统一结构：{"format": "markdown"|"json", "raw": <原始文本>, "items": [...]}
    """
    fmt = "json" if content_type in JSON_TYPES else "markdown"
    payload = {"format": fmt, "raw": raw_text}
    if fmt == "json" and isinstance(parsed, list):
        payload["items"] = parsed
    return json.dumps(payload, ensure_ascii=False)


def normalize_items(parsed: dict | list | None) -> list[dict]:
    """把 LLM 解析结果规整为题目列表。兼容「顶层数组」与「{questions:[...]}」两种形态。"""
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        for key in ("questions", "items", "data", "list", "slides"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []
