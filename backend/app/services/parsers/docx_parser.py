# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— DOC/DOCX 解析器
"""Word 文档解析（python-docx）：按文档真实顺序遍历段落与表格，抽取内嵌图片与公式。

多模态处理（工单18）：
- 表格 → Markdown；图片 → 抽存 uploads/kb/{doc_id}/ 并以所在段落文字作为上下文；
- 公式：OMML 公式的文本不在 paragraph.text 里，故单独取 ``m:t`` 节点还原，
  并把该段标记为 formula 块（保留原文位置与上下文，不做 OCR/LaTeX 转换）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.parsers.base import BlockBuilder, ParsedBlock, save_image_bytes, table_to_markdown

logger = logging.getLogger(__name__)

# 显式声明命名空间，避免依赖 python-docx 版本内部的 nsmap
_W_P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
_W_TBL = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"
_M_OMATH = "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"
_M_T = "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"
_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def parse(path: Path, image_dir: Path | None = None, rel_prefix: str = "") -> list[ParsedBlock]:
    """解析 Word 文档，返回按正文顺序排列的多模态块序列。"""
    document = DocxDocument(str(path))
    builder = BlockBuilder()
    image_seq = 0

    for child in document.element.body.iterchildren():
        if child.tag == _W_P:
            paragraph = Paragraph(child, document)
            image_seq = _handle_paragraph(paragraph, builder, document, image_dir, rel_prefix, image_seq)
        elif child.tag == _W_TBL:
            try:
                markdown = _table_markdown(Table(child, document))
            except Exception as exc:  # noqa: BLE001 - 单个表格异常不影响整篇解析
                logger.warning("Word 表格解析失败：%s", exc)
                continue
            builder.table(markdown)

    return builder.blocks


def _handle_paragraph(
    paragraph: Paragraph,
    builder: BlockBuilder,
    document: DocxDocument,
    image_dir: Path | None,
    rel_prefix: str,
    image_seq: int,
) -> int:
    text = (paragraph.text or "").strip()

    # 1) 内嵌图片（按段内出现顺序）
    if image_dir is not None:
        for blip in paragraph._p.iter(_A_BLIP):
            rid = blip.get(_R_EMBED)
            if not rid:
                continue
            part = document.part.related_parts.get(rid)
            if part is None:
                continue
            image_seq += 1
            ext = Path(str(part.partname)).suffix.lstrip(".") or "png"
            rel_path = save_image_bytes(
                getattr(part, "blob", b""), ext, image_dir, rel_prefix, stem=f"img{image_seq}"
            )
            if rel_path:
                builder.image(rel_path, context=text)

    # 2) 公式（OMML）：正文文本 + 公式文本合并保留
    math_text = _math_text(paragraph)
    if math_text:
        merged = f"{text}\n{math_text}".strip() if text else math_text
        builder.add(ParsedBlock("formula", merged))
    elif text:
        builder.text(text)

    return image_seq


def _math_text(paragraph: Paragraph) -> str:
    """还原段落内的 OMML 公式文本（不含格式，仅保留字符与位置）。"""
    parts: list[str] = []
    for omml in paragraph._p.iter(_M_OMATH):
        chunk = "".join(node.text or "" for node in omml.iter(_M_T)).strip()
        if chunk:
            parts.append(chunk)
    return " ".join(parts)


def _table_markdown(table: Table) -> str:
    rows = [[cell.text or "" for cell in row.cells] for row in table.rows]
    return table_to_markdown(rows)
