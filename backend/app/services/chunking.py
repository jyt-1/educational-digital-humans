# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 文档切块
"""把解析出的多模态块切成入库单元（约 500 字、重叠 80，元数据记文件名/页码/段落号）。

切块策略（工单18 要求 + 检索效果考虑）：
- 表格 / 图片块**整体成块不切分**（切开就丢结构，引用也没法回显原图）；
  超大表格按行分组，每组重复表头，避免超出 Embedding 模型输入上限；
- 文本 / 公式块按句子边界聚合到 ``size`` 字，相邻块保留 ``overlap`` 字重叠，
  避免关键句正好落在切缝上导致检索漏召回；
- 每个块记录页码与所在段落（section），供引用溯源展示。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.services.parsers.base import FORMULA, IMAGE, TABLE, TEXT, ParsedBlock

logger = logging.getLogger(__name__)

# 单块字符上限：超过则强制切开（bge-m3 上限 8192 token，留足安全余量）
_MAX_CHUNK_CHARS = 2000
# 表格分组时每组的行数上限
_TABLE_ROWS_PER_PART = 60

# 句子切分：在中文/英文句末标点与换行后断开（保留标点）
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;：:\n])")


@dataclass
class Chunk:
    """切块结果，与 kb_chunks 表字段一一对应。"""

    chunk_index: int
    chunk_type: str
    content: str
    page_no: int | None = None
    image_path: str | None = None
    section: str | None = None


def chunk_blocks(
    blocks: list[ParsedBlock],
    *,
    size: int = 500,
    overlap: int = 80,
) -> list[Chunk]:
    """把解析块切成入库单元。``size`` 约 500 字、``overlap`` 相邻重叠 80 字。"""
    if size <= 0:
        raise ValueError("size 必须为正整数")
    overlap = max(0, min(overlap, size // 2))

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_types: list[str] = []
    buf_page: int | None = None
    buf_section: str | None = None
    added_len = 0  # 自上次 flush 起新写入的字符数（不含重叠尾巴）

    def flush() -> None:
        nonlocal buf, buf_types, buf_page, buf_section, added_len
        text = "".join(buf).strip()
        if not text or added_len == 0:
            # 缓冲区里只有上一次的重叠尾巴，没有新内容，直接丢弃避免产生重复块
            if added_len == 0:
                buf, buf_types, buf_page, buf_section, added_len = [], [], None, None, 0
            return
        chunk_type = FORMULA if buf_types and all(t == FORMULA for t in buf_types) else TEXT
        for part in _hard_split(text, size):
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    chunk_type=chunk_type,
                    content=part,
                    page_no=buf_page,
                    section=buf_section,
                )
            )
        tail = text[-overlap:].strip() if overlap else ""
        buf = [tail] if tail else []
        buf_types = [TEXT] if tail else []
        # 重叠尾巴沿用原页码与段落定位（buf_page / buf_section 保持不变）
        added_len = 0

    for block in blocks:
        if block.block_type in (TABLE, IMAGE):
            flush()
            if block.block_type == TABLE:
                for part in _split_table(block.content):
                    chunks.append(
                        Chunk(
                            chunk_index=len(chunks),
                            chunk_type=TABLE,
                            content=part,
                            page_no=block.page_no,
                            section=block.section,
                        )
                    )
            else:
                chunks.append(
                    Chunk(
                        chunk_index=len(chunks),
                        chunk_type=IMAGE,
                        content=block.content or "图片",
                        page_no=block.page_no,
                        image_path=block.image_path,
                        section=block.section,
                    )
                )
            # 表格/图片打断上下文连续性，不跨模态做重叠
            buf, buf_types, buf_page, buf_section, added_len = [], [], None, None, 0
            continue

        for sentence in _split_sentences(block.content, size):
            current = sum(len(item) for item in buf)
            if current + len(sentence) > size:
                if added_len:
                    flush()  # 装不下了：先把已有的落块，尾巴作为下一块的重叠
                    current = sum(len(item) for item in buf)
                if current + len(sentence) > size:
                    # 缓冲里只剩重叠尾巴且仍装不下，丢弃尾巴（保块大小不超过 size）
                    buf, buf_types, buf_page, buf_section, added_len = [], [], None, None, 0
            if not buf or buf_page is None:
                buf_page = block.page_no
                buf_section = block.section
            buf.append(sentence)
            buf_types.append(block.block_type)
            added_len += len(sentence)

    flush()
    return chunks


def _split_sentences(text: str, limit: int) -> list[str]:
    """按句末标点切句；超长句子再按 ``limit`` 硬切，保证单句放得进一个块。"""
    cap = max(1, min(limit, _MAX_CHUNK_CHARS))
    sentences: list[str] = []
    for raw in _SENTENCE_SPLIT.split(text or ""):
        piece = raw.strip()
        if not piece:
            continue
        if len(piece) <= cap:
            sentences.append(piece)
            continue
        sentences.extend(piece[i : i + cap] for i in range(0, len(piece), cap))
    return sentences


def _hard_split(text: str, limit: int) -> list[str]:
    """兜底：块内容超长时按上限硬切（正常路径下不会触发）。"""
    cap = max(1, min(limit, _MAX_CHUNK_CHARS))
    if len(text) <= cap:
        return [text]
    return [text[i : i + cap] for i in range(0, len(text), cap)]


def _split_table(markdown: str) -> list[str]:
    """超大 Markdown 表格按行分组，每组重复表头（前两行：表头 + 分隔行）。"""
    text = (markdown or "").strip()
    if not text:
        return []
    lines = text.splitlines()
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]

    header = lines[:2] if len(lines) >= 2 and set(lines[1]) <= set("|-: ") else []
    body = lines[len(header) :]
    parts: list[str] = []
    for start in range(0, len(body), _TABLE_ROWS_PER_PART):
        group = body[start : start + _TABLE_ROWS_PER_PART]
        parts.append("\n".join(header + group))
    logger.info("大表格已拆分为 %d 块（共 %d 行）", len(parts), len(body))
    return parts
