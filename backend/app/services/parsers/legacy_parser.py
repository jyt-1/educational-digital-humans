# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 老式 Office 文档降级解析器
"""Office 97-2003 老格式（.doc / .ppt / .xls）解析。

工单18 要求覆盖 DOC/PPT/XLS，但这三种是 OLE 复合文档，python-docx / python-pptx /
openpyxl 均无法打开。本机无 GPU、不引入重量级转换组件，故按「保留可检索文本」的方式降级：

1. 先嗅探文件头——不少导出工具把 OOXML 文件错误命名成 .doc/.ppt/.xls，
   这类文件直接交给对应的新格式解析器，多模态能力不受影响；
2. 真正的老格式：按 UTF-16LE 抽取可读文本段（老版 Word 正文即以 UTF-16LE 存储），
   表格/图片/公式无法还原，入库时在首块显式写明降级说明，避免用户误以为内容完整。

降级说明会作为首块进入检索结果与引用展示，用户能明确看到该文档的能力边界。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.services.parsers.base import BlockBuilder, ParsedBlock

logger = logging.getLogger(__name__)

# OOXML 是 zip（PK\x03\x04），OLE 复合文档是 D0 CF 11 E0
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# 可读文本段：中日韩、全角标点、ASCII 可见字符连续出现 6 个以上
_TEXT_RUN = re.compile(
    r"[一-鿿　-〿＀-￯"
    r"A-Za-z0-9 ,.;:!?()\[\]{}<>/%\-_'\"+=*&@#$~^|]{6,}"
)
# 纯符号/纯数字噪声段
_NOISE = re.compile(r"^[\W_]+$")

_NEW_FORMAT = {"doc": "docx", "ppt": "pptx", "xls": "xlsx"}
_CHUNK_CHARS = 800

DEGRADE_NOTE = (
    "【格式说明】本文档为 Office 97-2003 老格式（.{ext}），已降级为纯文本抽取："
    "正文文字可被检索与引用，但表格、图片、公式不会保留。"
    "如需完整的多模态解析，请用 Office 另存为 .{new_ext} 后重新上传。"
)


def parse(path: Path, image_dir: Path | None = None, rel_prefix: str = "") -> list[ParsedBlock]:
    builder = BlockBuilder()
    raw = path.read_bytes()
    ext = path.suffix.lstrip(".").lower() or "doc"

    if raw.startswith(_ZIP_MAGIC):
        # 实为新格式，转交对应解析器（保持多模态完整能力）
        logger.info("%s 实为 OOXML 文件，转交 %s 解析器", path.name, _NEW_FORMAT.get(ext, "docx"))
        from app.services.parsers import parse_document  # 延迟导入避免循环依赖

        return parse_document(
            path,
            file_type=_NEW_FORMAT.get(ext, "docx"),
            image_dir=image_dir,
            rel_prefix=rel_prefix,
        )

    builder.add(
        ParsedBlock(
            "text",
            content=DEGRADE_NOTE.format(ext=ext, new_ext=_NEW_FORMAT.get(ext, "docx")),
            page_no=1,
        )
    )

    sentences = _extract_runs(raw)
    if not sentences:
        builder.add(
            ParsedBlock(
                "text",
                content=(
                    "【解析提示】未能从该老格式文件中抽取出可读文本，可能为加密文档或纯图形内容。"
                    "请用 Office 打开后另存为新格式再上传。"
                ),
            )
        )
        return builder.blocks

    text = "\n".join(sentences)
    for start in range(0, len(text), _CHUNK_CHARS):
        builder.text(text[start : start + _CHUNK_CHARS])

    return builder.blocks


def _extract_runs(raw: bytes) -> list[str]:
    """从 OLE 二进制里抽取 UTF-16LE 文本段，做去重与噪声过滤。"""
    decoded = raw.decode("utf-16-le", errors="ignore")
    runs: list[str] = []
    seen: set[str] = set()
    for match in _TEXT_RUN.findall(decoded):
        text = " ".join(match.split())
        if len(text) < 6 or _NOISE.match(text):
            continue
        # 老格式同一段文字常重复出现（正文 + 摘要表），按内容去重
        key = text[:80]
        if key in seen:
            continue
        seen.add(key)
        runs.append(text)
    return runs
