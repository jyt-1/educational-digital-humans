# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— PDF 多模态解析器
"""PDF 解析（PyMuPDF）：逐页抽取文本块、表格与内嵌图片，按版面纵坐标还原阅读顺序。

多模态处理（工单18 验收标准）：
- 表格：``page.find_tables()`` → Markdown 存储，落在表格框内的文本块会被去重剔除；
- 图片：``page.get_image_info(xrefs=True)`` 定位 + ``doc.extract_image()`` 抽原图，
  存 uploads/kb/{doc_id}/，并把该图前面的正文作为上下文一并写入图片块（检索入口）；
- 公式：文本层里的公式保留原文，并通过启发式标记为 formula 块，位置与上下文不丢。

不使用 MinerU/OCR：本机无独立显卡，纯 CPU 跑 OCR 极慢（CLAUDE.md 第 8 节工单18）。
"""

from __future__ import annotations

import logging
from pathlib import Path

try:  # PyMuPDF >= 1.24.3 提供 pymupdf 包名，旧版本用 fitz
    import pymupdf as fitz
except ImportError:  # pragma: no cover - 取决于安装版本
    import fitz

from app.services.parsers.base import (
    BlockBuilder,
    ParsedBlock,
    save_image_bytes,
    unescape_entities,
)

logger = logging.getLogger(__name__)

# 过小的内嵌图片多为项目符号/图标，不作为可引用内容
_MIN_IMAGE_PX = 32
# 单页抽取图片数量上限，防止某个 PDF 塞满图标时拖垮解析
_MAX_IMAGES_PER_PAGE = 20
# 图片上下文取前文末尾多少字
_CONTEXT_CHARS = 120
# 同一纵坐标时的稳定排序：表格 → 图片 → 文本
_KIND_ORDER = {"table": 0, "image": 1, "text": 2}


def parse(path: Path, image_dir: Path | None = None, rel_prefix: str = "") -> list[ParsedBlock]:
    """解析 PDF，返回按阅读顺序排列的多模态块序列。"""
    builder = BlockBuilder()
    text_seen = 0

    with fitz.open(str(path)) as doc:
        for page_no, page in enumerate(doc, start=1):
            regions = _collect_regions(doc, page, page_no, image_dir, rel_prefix)
            # 按版面纵坐标还原阅读顺序；同一高度时按 表格 → 图片 → 文本 的稳定顺序
            regions.sort(key=lambda item: (round(item[0], 1), _KIND_ORDER[item[1]]))

            last_text = ""
            for _, kind, payload in regions:
                if kind == "table":
                    builder.table(str(payload), page_no=page_no)
                elif kind == "image":
                    builder.image(str(payload), context=last_text, page_no=page_no)
                else:  # text
                    text_seen += 1
                    builder.text(payload, page_no=page_no)
                    last_text = payload

    if text_seen == 0:
        builder.blocks.insert(
            0,
            ParsedBlock(
                block_type="text",
                content=(
                    "【解析提示】本 PDF 未包含可提取的文本层（疑似扫描件或纯图片版），"
                    "仅抽出了图片内容。如需全文检索，请提供带文本层的 PDF 或原始文档。"
                ),
                page_no=1,
            ),
        )
    return builder.blocks


def _collect_regions(
    doc: "fitz.Document",
    page: "fitz.Page",
    page_no: int,
    image_dir: Path | None,
    rel_prefix: str,
) -> list[tuple[float, int, object]]:
    """收集一页内的三类区域：表格 / 图片 / 文本。返回 (纵坐标, 排序位, 载荷)。"""
    regions: list[tuple[float, int, object]] = []
    table_rects: list[fitz.Rect] = []

    # 1) 表格 → Markdown
    try:
        found = page.find_tables()
        tables = list(getattr(found, "tables", []) or [])
    except Exception as exc:  # noqa: BLE001 - 个别 PDF 的表格探测会抛错，不影响其余内容
        logger.warning("第 %d 页表格探测失败：%s", page_no, exc)
        tables = []

    for table in tables:
        try:
            # PyMuPDF 直接给出的 Markdown 可能带字体编码残留（如 &#45;），统一还原
            markdown = unescape_entities(table.to_markdown() or "").strip()
            bbox = fitz.Rect(table.bbox)
        except Exception as exc:  # noqa: BLE001
            logger.warning("第 %d 页表格转换失败：%s", page_no, exc)
            continue
        if not markdown:
            continue
        table_rects.append(bbox)
        regions.append((bbox.y0, "table", markdown))

    # 2) 内嵌图片
    if image_dir is not None:
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("第 %d 页图片定位失败：%s", page_no, exc)
            infos = []

        saved_xrefs: set[int] = set()
        for pos, info in enumerate(infos[:_MAX_IMAGES_PER_PAGE]):
            xref = int(info.get("xref") or 0)
            if xref <= 0 or xref in saved_xrefs:
                continue
            if (info.get("width") or 0) < _MIN_IMAGE_PX or (info.get("height") or 0) < _MIN_IMAGE_PX:
                continue
            saved_xrefs.add(xref)
            try:
                raw = doc.extract_image(xref)
            except Exception as exc:  # noqa: BLE001
                logger.warning("第 %d 页图片抽取失败（xref=%s）：%s", page_no, xref, exc)
                continue
            rel_path = save_image_bytes(
                raw.get("image", b""),
                raw.get("ext", "png"),
                image_dir,
                rel_prefix,
                stem=f"p{page_no}_x{xref}",
            )
            if not rel_path:
                continue
            bbox = fitz.Rect(info.get("bbox") or (0, 0, 0, 0))
            regions.append((bbox.y0, "image", rel_path))

    # 3) 文本块（剔除落在表格框内的，避免与 Markdown 表格重复）
    try:
        raw_blocks = page.get_text("blocks")
    except Exception as exc:  # noqa: BLE001
        logger.warning("第 %d 页文本抽取失败：%s", page_no, exc)
        raw_blocks = []

    for block in raw_blocks:
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        text = _clean_text(text)
        if not text:
            continue
        center = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if any(rect.contains(center) for rect in table_rects):
            continue
        regions.append((y0, "text", text))

    return regions


def _clean_text(text: str) -> str:
    """清洗 PDF 文本块：还原实体化字符、去掉页码类孤立行。"""
    lines = [ln.strip() for ln in unescape_entities(text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    # 纯数字/罗马数字的孤立行多为页码
    lines = [ln for ln in lines if not (len(ln) <= 4 and ln.isdigit())]
    return "\n".join(lines).strip()
