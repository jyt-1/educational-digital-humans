# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— PPT/PPTX 解析器
"""课件解析（python-pptx）：逐页抽取文本框、表格与插图，页码即幻灯片序号。

多模态处理（工单18）：
- 表格 → Markdown；插图 → 抽存 uploads/kb/{doc_id}/，检索命中后可原图回显；
- 图片的上下文取「替代文字（alt text）」与同页标题，便于「这页的架构图」这类提问命中。
"""

from __future__ import annotations

import logging
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.services.parsers.base import BlockBuilder, ParsedBlock, save_image_bytes, table_to_markdown

logger = logging.getLogger(__name__)


def parse(path: Path, image_dir: Path | None = None, rel_prefix: str = "") -> list[ParsedBlock]:
    """解析 PPT/PPTX，返回按幻灯片顺序排列的多模态块序列（page_no = 幻灯片序号）。"""
    presentation = Presentation(str(path))
    builder = BlockBuilder()

    for slide_no, slide in enumerate(presentation.slides, start=1):
        title = _slide_title(slide)
        # 幻灯片标题本身就是该页最重要的内容，单独成块（下面跳过同文文本框避免重复）
        if title:
            builder.text(title, page_no=slide_no, section=title)
        image_seq = 0
        for shape in slide.shapes:
            try:
                image_seq = _handle_shape(
                    shape, builder, slide_no, title, image_dir, rel_prefix, image_seq
                )
            except Exception as exc:  # noqa: BLE001 - 单个形状异常不影响整页
                logger.warning("第 %d 页形状解析失败（%s）：%s", slide_no, shape.shape_type, exc)

    return builder.blocks


def _handle_shape(
    shape,
    builder: BlockBuilder,
    slide_no: int,
    title: str | None,
    image_dir: Path | None,
    rel_prefix: str,
    image_seq: int,
) -> int:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for child in shape.shapes:
            image_seq = _handle_shape(child, builder, slide_no, title, image_dir, rel_prefix, image_seq)
        return image_seq

    if getattr(shape, "has_table", False) and shape.has_table:
        rows = [[cell.text or "" for cell in row.cells] for row in shape.table.rows]
        markdown = table_to_markdown(rows)
        if markdown:
            builder.table(markdown, page_no=slide_no, section=title)
        return image_seq

    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and image_dir is not None:
        image = shape.image
        image_seq += 1
        rel_path = save_image_bytes(
            image.blob,
            image.ext,
            image_dir,
            rel_prefix,
            stem=f"slide{slide_no}_img{image_seq}",
        )
        if rel_path:
            context = " ".join(filter(None, [_alt_text(shape), title]))
            builder.image(rel_path, context=context, page_no=slide_no, section=title)
        return image_seq

    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = (shape.text_frame.text or "").strip()
        if text and text != (title or "").strip():
            builder.text(text, page_no=slide_no, section=title)

    return image_seq


def _slide_title(slide) -> str | None:
    try:
        if slide.shapes.title is not None:
            text = (slide.shapes.title.text or "").strip()
            return text or None
    except Exception:  # noqa: BLE001 - 个别版式取标题会抛错
        return None
    return None


def _alt_text(shape) -> str:
    """图片的替代文字，常含「图 3-1 反向传播示意」这类描述，是很好的检索入口。"""
    try:
        nodes = shape._element.xpath(".//p:cNvPr")
        if nodes:
            return (nodes[0].get("descr") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""
