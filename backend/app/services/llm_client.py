# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— LLM 统一封装
"""LLM 调用统一封装（OpenAI 兼容接口）。

设计要点（见设计文档 3.2.3 与 CLAUDE.md 第 9 节）：
1. base_url / api_key / model 全部走 .env，代码中不得硬编码；
2. JSON 容错：失败重试 1 次 + 正则提取首个 {} 块宽松解析；
3. 无 API Key 时不影响应用启动，仅在真正调用时抛出可读异常。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# 调用超时（秒）：生成类内容较长，给足时间
_REQUEST_TIMEOUT = 120.0


class LLMNotConfiguredError(RuntimeError):
    """未配置 API Key 时抛出，便于接口层返回可读提示。"""


def _client() -> AsyncOpenAI:
    if not settings.LLM_API_KEY or settings.LLM_API_KEY.startswith("sk-xxx"):
        raise LLMNotConfiguredError(
            "未配置 LLM API Key。请复制 .env.example 为 .env，并填入 LLM_API_KEY。"
        )
    return AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        timeout=_REQUEST_TIMEOUT,
    )


def extract_json_block(text: str) -> dict | list | None:
    """从可能夹带说明文字/Markdown 代码块的回复中，宽松提取首个完整的 {} 或 [] 块。

    优先匹配 fenced code block，其次做括号配对扫描。解析失败返回 None。
    """
    if not text:
        return None

    # 1) 依次尝试直接解析、以及 ```json ... ``` 代码块
    candidates: list[str] = [text.strip()]
    candidates += re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)

    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            pass

    # 2) 括号配对扫描，截取首个完整块（跳过字符串内的括号）
    #    必须按"哪个左括号先出现"决定扫描顺序：若先扫 {，则 '[{"a":1},{"b":2}]'
    #    会被误截成首个对象 {'a':1}，丢掉数组其余元素。
    attempts = sorted(
        (text.find(opener), opener, closer)
        for opener, closer in (("{", "}"), ("[", "]"))
        if text.find(opener) != -1
    )
    for start, opener, closer in attempts:
        depth = 0
        in_str = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    snippet = text[start : idx + 1]
                    try:
                        return json.loads(snippet)
                    except json.JSONDecodeError:
                        break
    return None


async def chat_json(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_retries: int = 1,
) -> dict | list:
    """要求 LLM 返回 JSON 并宽松解析。失败重试 max_retries 次（默认 1 次）。

    :raises ValueError: 重试后仍无法解析出 JSON
    """
    last_raw = ""
    for attempt in range(max_retries + 1):
        kwargs: dict = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
        }
        # DeepSeek 支持 json_object；若供应商不支持则自动回退为普通调用
        if attempt == 0:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await _client().chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 供应商不支持 response_format 等
            if attempt == 0 and "response_format" in kwargs:
                logger.warning("JSON 模式调用失败，回退普通调用：%s", exc)
                continue
            raise

        last_raw = response.choices[0].message.content or ""
        parsed = extract_json_block(last_raw)
        if parsed is not None:
            return parsed
        logger.warning("第 %d 次 JSON 解析失败，原始回复前 200 字：%s", attempt + 1, last_raw[:200])

    raise ValueError(f"LLM 返回内容无法解析为 JSON：{last_raw[:200]}")


async def chat_text(
    messages: list[dict],
    *,
    temperature: float = 0.5,
) -> str:
    """普通文本调用（非流式）。"""
    response = await _client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


async def chat_stream(
    messages: list[dict],
    *,
    temperature: float = 0.5,
) -> AsyncIterator[str]:
    """流式调用，逐段 yield 文本增量（供 SSE 推送）。"""
    stream = await _client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
