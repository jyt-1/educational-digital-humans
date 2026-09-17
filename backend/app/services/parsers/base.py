# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 多模态解析公共定义
"""解析结果的统一结构与公共工具。

设计要点（工单18）：
1. 解析器统一输出 ``ParsedBlock`` 序列，块类型与 kb_chunks.chunk_type 对齐：
   text（通用文本）/ table（表格，转 Markdown 存储）/ image（图片，抽存路径供引用回显）
   / formula（公式，保留原文位置与上下文）；
2. 每个块都带页码或定位信息，供检索结果标注引用来源；
3. 不使用 MinerU/OCR（本机无 GPU，纯 CPU 跑 OCR 极慢），公式与复杂版面按
   「保留原文位置 + 引用回显」降级处理（CLAUDE.md 第 8 节工单18 已确认方案）。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# 块类型
TEXT = "text"
TABLE = "table"
IMAGE = "image"
FORMULA = "formula"

# 常见数学符号：用于判断某段文本是否为公式（无 OCR 时的轻量启发式）
MATH_CHARS = set(
    "∑∫∮∂√∞≈≠≤≥±×÷∇∈∉⊂⊃⊆⊇∪∩∀∃∅⇒⇔→←↔↑↓"
    "αβγδεζηθικλμνξοπρστυφχψω"
    "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    "·⋅∙⋅½⅓¼¾²³ⁿ₀₁₂₃₄"
)
# 含中日韩字符的行基本是正文（公式行极少混排汉字）
_CJK_RE = re.compile(r"[一-鿿　-〿＀-￯]")

MATH_PATTERNS = (
    "\\frac",
    "\\sum",
    "\\int",
    "\\alpha",
    "\\beta",
    "\\theta",
    "\\nabla",
    "^{",
    "_{",
    "$$",
    "\\(",
    "\\[",
)


@dataclass
class ParsedBlock:
    """解析出的最小内容单元（尚未切块）。"""

    block_type: str = TEXT
    content: str = ""
    page_no: int | None = None
    image_path: str | None = None  # 相对 uploads/ 的路径，如 kb/12/p3_x7.png
    section: str | None = None  # 段落/工作表/幻灯片标题等定位信息


@dataclass
class BlockBuilder:
    """解析器内部使用的可变收集器，避免各解析器重复样板代码。"""

    blocks: list[ParsedBlock] = field(default_factory=list)

    def add(self, block: ParsedBlock) -> None:
        if block.content or block.image_path:
            self.blocks.append(block)

    def text(self, content: str, page_no: int | None = None, section: str | None = None) -> None:
        content = (content or "").strip()
        if not content:
            return
        self.add(
            ParsedBlock(
                block_type=FORMULA if looks_formula(content) else TEXT,
                content=content,
                page_no=page_no,
                section=section,
            )
        )

    def table(self, content: str, page_no: int | None = None, section: str | None = None) -> None:
        content = (content or "").strip()
        if content:
            self.add(ParsedBlock(TABLE, content, page_no=page_no, section=section))

    def image(
        self,
        rel_path: str,
        context: str = "",
        page_no: int | None = None,
        section: str | None = None,
    ) -> None:
        """图片块：content 存上下文文字（作为检索入口），图片本体按路径回显。"""
        ctx = _trim(context, 120)
        label = f"图片（第 {page_no} 页）" if page_no else "图片"
        self.add(
            ParsedBlock(
                IMAGE,
                content=f"{label}：{ctx}" if ctx else label,
                page_no=page_no,
                image_path=rel_path,
                section=section,
            )
        )


# ------------------------------------------------------------------ 公共工具

def looks_formula(text: str) -> bool:
    """判断一段文本是否更像公式：数学符号占比高，或含 LaTeX 片段。

    阈值刻意保守——宁可把公式判成普通文本，也不要把正文误判成公式。
    """
    text = (text or "").strip()
    if not text or len(text) > 300:
        return False
    if any(p in text for p in MATH_PATTERNS) and "\\" in text:
        return True

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    math_lines = sum(1 for ln in lines if _line_is_math(ln))
    return math_lines * 2 >= len(lines)


def _line_is_math(line: str) -> bool:
    """单行判定：需要出现数学字形（希腊字母/求和/上下标等）+ 足够的运算符密度。

    刻意保守——纯 ASCII 的四则运算式（如 "y = wx + b"）不判为公式，
    宁可漏标也不要误伤英文正文；漏标的公式仍会作为文本入库，不影响检索与引用。
    """
    if len(line) > 160 or _CJK_RE.search(line):
        return False
    math_cnt = sum(1 for ch in line if ch in MATH_CHARS)
    if math_cnt == 0:
        return False
    # 只反复出现同一个符号的行（如目录的点线引导、分隔线）不算公式
    if len({ch for ch in line if not ch.isspace()}) <= 2:
        return False
    operator_cnt = sum(1 for ch in line if ch in "=+-*/^_()[]{}<>|,")
    return operator_cnt >= 1 and math_cnt * 2 + operator_cnt >= 3


# PDF 文本抽取常见的实体化残留：`&amp;#45;` / `&amp;lt;` 等（字体编码导致）
_ENTITY_AMP = re.compile(r"&(amp|lt|gt|quot|apos);")
_ENTITY_NUM = re.compile(r"&#(\d{1,5});")


def unescape_entities(text: str) -> str:
    """还原 PDF 抽取文本里被实体化的字符（先还原命名实体，再还原数字实体）。"""
    if not text or "&" not in text:
        return text
    named = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
    text = _ENTITY_AMP.sub(lambda m: named[m.group(1)], text)
    return _ENTITY_NUM.sub(lambda m: chr(int(m.group(1))), text)


def table_to_markdown(rows: list[list[str]]) -> str:
    """二维表 → Markdown 表格（工单18 要求表格转 Markdown 存储）。"""
    cleaned: list[list[str]] = []
    for row in rows:
        cells = [_cell_text(c) for c in row]
        if any(c for c in cells):
            cleaned.append(cells)
    if not cleaned:
        return ""

    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    header = cleaned[0]
    body = cleaned[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _cell_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unescape_entities(text)
    text = text.replace("\r", " ").replace("\n", "<br>").replace("|", "\\|")
    return " ".join(text.split())


def save_image_bytes(data: bytes, ext: str, image_dir: Path, rel_prefix: str, stem: str) -> str | None:
    """把抽取到的图片写入 uploads/kb/{doc_id}/，返回相对 uploads/ 的 POSIX 路径。"""
    if not data:
        return None
    ext = (ext or "png").lstrip(".").lower()
    if ext in ("jpeg", "jpg"):
        ext = "jpg"
    elif ext not in ("png", "bmp", "gif", "webp", "tiff"):
        ext = "png"
    safe_stem = re.sub(r"[^0-9A-Za-z_\-]", "_", stem)[:60] or uuid.uuid4().hex[:8]
    filename = f"{safe_stem}_{uuid.uuid4().hex[:6]}.{ext}"

    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / filename).write_bytes(data)
    return f"{rel_prefix.strip('/')}/{filename}" if rel_prefix else filename


def _trim(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
