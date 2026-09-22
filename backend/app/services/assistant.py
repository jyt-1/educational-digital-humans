# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 检索增强问答
"""RAG 问答：把检索到的多模态资料拼成带编号的上下文，约束 LLM 有据可依地回答。

对应设计文档「幻觉控制」条款：
- 强制基于检索到的资料作答，答案中每处依据标注 ``[n]`` 角标；
- 检索无结果时明确告知「未在知识库中找到依据」，不得编造；
- 若确有通用知识补充，必须显式标注【非知识库内容】。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.services import avatar_persona, llm_client
from app.services.retriever import Hit

logger = logging.getLogger(__name__)

# 上下文里单条资料的最大字符数，避免超长资料挤爆上下文
_MAX_SNIPPET_CHARS = 1200

_SYSTEM_WITH_CONTEXT = """你是「智能助教」，服务于高职院校与 K12 的教师和学生。请**严格依据下方【资料】**回答用户问题。

硬性要求：
1. 每处引用资料的结论，在句末标注来源编号（如 [1][2]），编号必须与【资料】一致；
2. 表格类资料用 Markdown 表格原样呈现；图片类资料用「见引用[n]」提示查看原图；
3. 【资料】不足以回答时，明确说明"知识库中未找到依据"，**不得编造**；
   若确需用通用知识补充，必须在该段开头标注【非知识库内容】；
4. 面向学生时深入浅出：先给定义，再给例子；面向教师时可给出教学建议；
5. 用简体中文作答，结构清晰，可使用小标题与列表。"""

_SYSTEM_NO_CONTEXT = """你是「智能助教」，服务于高职院校与 K12 的教师和学生。
本次检索**未在知识库中找到任何相关资料**，请：
1. 首先明确告知用户"未在知识库中找到依据"；
2. 建议用户上传相关资料，或换一种问法再试；
3. 若该问题属于通用学科知识，可在开头标注【非知识库内容】后用通用知识简要回答；
4. 严禁假装引用知识库内容，严禁编造文件名或页码。
用简体中文作答。"""

# 闲聊/自我介绍专用：**不检索、不要求引用**，只按形象人设自然回应。
# 没有它的时候，用户问一句"介绍一下你自己"，数字人会回一屏"知识库中未找到依据"。
_SYSTEM_CHITCHAT = """{persona}

用户这次说的是**寒暄、自我介绍或能力询问**这类闲聊，本次**没有检索知识库**，也不要假装检索过。

请按你的身份自然回应：
1. 自我介绍时用一两句口语化的话讲清「你是谁、带哪类课、有什么脾气」，**语气必须符合上面的人设**，不要像念简历；
2. 顺带说说你能帮上什么忙（基于知识库的答疑与讲解、答案带引用溯源、按知识点出题备课、把教案课件做成讲课视频），**只提真实具备的能力**，不要编造；
3. 称呼对方为「同学」，不要称呼「用户」；
4. 不要出现「知识库中未找到依据」「建议上传资料」这类检索话术，也不要标 [n] 角标；
5. 2~4 句为宜，不要过度卖萌；用简体中文作答。"""


def build_context_block(hits: list[Hit]) -> str:
    """把命中的资料拼成带编号的上下文块。编号即前端引用角标。"""
    if not hits:
        return ""
    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        location = f"《{hit.filename}》"
        if hit.page_no:
            location += f" 第 {hit.page_no} 页"
        location += f"（{_type_label(hit.chunk_type)}）"
        content = hit.content.strip()
        if len(content) > _MAX_SNIPPET_CHARS:
            content = content[:_MAX_SNIPPET_CHARS] + "……（已截断）"
        lines.append(f"[{index}] {location}\n{content}")
    return "\n\n".join(lines)


def build_rag_messages(
    question: str,
    hits: list[Hit],
    history: list[dict] | None = None,
    *,
    avatar_id: str | None = None,
    smalltalk: bool = False,
) -> list[dict]:
    """构造 RAG 对话消息。``history`` 为之前的多轮消息（role/content）。

    ``avatar_id`` 决定数字人人设（见 avatar_persona.py）：常规问答只注入语气，
    闲聊分支（``smalltalk=True``）则整套换成人设应答。闲聊分支不要求引用，
    传进来的 ``hits`` 应为空——调用方（api/assistant.py）已按此跳过检索。
    """
    persona = avatar_persona.persona_line(avatar_id)
    if smalltalk:
        messages: list[dict] = [{"role": "system", "content": _SYSTEM_CHITCHAT.format(persona=persona)}]
        for item in history or []:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})
        return messages

    context = build_context_block(hits)
    base = _SYSTEM_WITH_CONTEXT if context else _SYSTEM_NO_CONTEXT
    system = f"{persona}\n\n{base}"
    messages = [{"role": "system", "content": system}]

    for item in history or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    if context:
        user_content = f"【资料】\n{context}\n\n【问题】\n{question}"
    else:
        user_content = f"【问题】\n{question}（知识库中未检索到相关资料）"
    messages.append({"role": "user", "content": user_content})
    return messages


async def stream_answer(
    question: str,
    hits: list[Hit],
    history: list[dict] | None = None,
    *,
    avatar_id: str | None = None,
    smalltalk: bool = False,
) -> AsyncIterator[str]:
    """流式产出答案增量（供 SSE 推送）。"""
    messages = build_rag_messages(
        question, hits, history, avatar_id=avatar_id, smalltalk=smalltalk
    )
    async for delta in llm_client.chat_stream(messages, temperature=0.3):
        yield delta


def make_title(question: str, limit: int = 24) -> str:
    """用首个问题生成会话标题。"""
    text = " ".join((question or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _type_label(chunk_type: str) -> str:
    return {
        "table": "表格",
        "image": "图片",
        "formula": "公式",
    }.get(chunk_type, "正文")
