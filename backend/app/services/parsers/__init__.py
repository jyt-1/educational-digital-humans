# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 多模态解析调度
"""统一解析入口：按文件类型分发到各解析器，输出一致的 ``ParsedBlock`` 序列。

工单18 要求的格式范围（不可缩窄）：
PDF / DOC / DOCX / PPT / PPTX / XLS / XLSX / 图像。
其中 doc/ppt/xls 为 OLE 老格式，按 legacy_parser 的降级策略处理（首块写明能力边界）。

用法::

    blocks = parse_document(path, file_type="pdf", image_dir=..., rel_prefix="kb/12")
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.parsers import (
    docx_parser,
    image_parser,
    legacy_parser,
    pdf_parser,
    pptx_parser,
    xlsx_parser,
)
from app.services.parsers.base import (
    FORMULA,
    IMAGE,
    TABLE,
    TEXT,
    BlockBuilder,
    ParsedBlock,
    looks_formula,
    save_image_bytes,
    table_to_markdown,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FORMULA",
    "IMAGE",
    "TABLE",
    "TEXT",
    "BlockBuilder",
    "ParsedBlock",
    "detect_file_type",
    "looks_formula",
    "parse_document",
    "save_image_bytes",
    "table_to_markdown",
]

_PARSERS = {
    "pdf": pdf_parser.parse,
    "docx": docx_parser.parse,
    "doc": legacy_parser.parse,
    "pptx": pptx_parser.parse,
    "ppt": legacy_parser.parse,
    "xlsx": xlsx_parser.parse,
    "xls": legacy_parser.parse,
    "image": image_parser.parse,
}

_EXT_TO_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".pptx": "pptx",
    ".ppt": "ppt",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".bmp": "image",
    ".gif": "image",
    ".webp": "image",
    ".tiff": "image",
}

_MAGIC_SNIFF = (
    (b"%PDF", "pdf"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"BM", "image"),
    (b"RIFF", "image"),
    (b"II*\x00", "image"),
    (b"MM\x00*", "image"),
)


def detect_file_type(filename: str, head: bytes | None = None) -> str | None:
    """按扩展名判定文件类型；扩展名缺失或可疑时用文件头兜底。返回 None 表示不支持。"""
    ext = Path(filename).suffix.lower()
    if ext in _EXT_TO_TYPE:
        return _EXT_TO_TYPE[ext]

    if head:
        for magic, file_type in _MAGIC_SNIFF:
            if head.startswith(magic):
                return file_type
        if head.startswith(b"PK\x03\x04"):
            return "docx"  # 无扩展名的 OOXML，按最常见的 Word 处理
    return None


def parse_document(
    path: Path,
    *,
    file_type: str | None = None,
    image_dir: Path | None = None,
    rel_prefix: str = "",
) -> list[ParsedBlock]:
    """解析文档为多模态块序列。

    :param path: 待解析文件的绝对路径
    :param file_type: 文件类型（None 时按扩展名自动判定）
    :param image_dir: 抽取图片的落地目录（绝对路径）；None 表示不抽图
    :param rel_prefix: 图片路径前缀，即 image_dir 相对 uploads/ 的路径
    """
    file_type = file_type or detect_file_type(path.name)
    parser = _PARSERS.get(file_type or "")
    if parser is None:
        raise ValueError(f"暂不支持的文档格式：{path.name}（支持 PDF/Word/PPT/Excel/图像）")

    blocks = parser(path, image_dir, rel_prefix)
    logger.info("解析完成：%s（%s，%d 块）", path.name, file_type, len(blocks))
    return blocks
