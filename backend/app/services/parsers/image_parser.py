# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 图像文档解析器
"""图片类文档（PNG/JPG/BMP/GIF/WEBP/TIFF）入库。

多模态处理（工单18）：图像本身作为 image 块入库，原文件即引用回显源（不复制、不转码）。
本机无 GPU、不做 OCR（CLAUDE.md 第 8 节已确认降级），因此图片的检索入口是
文件名 + 上传时填写的说明（由调用方拼进 ``rel_prefix`` 以外的上下文）。

约定：``rel_prefix`` 传入的是该图片相对 uploads/ 的路径（如 ``kb/12/示意图.png``），
解析器直接把它作为 image_path 返回，这样引用回显时无需二次拷贝。
"""

from __future__ import annotations

from pathlib import Path

from app.services.parsers.base import BlockBuilder, ParsedBlock


def parse(path: Path, image_dir: Path | None = None, rel_prefix: str = "") -> list[ParsedBlock]:
    builder = BlockBuilder()
    rel_path = rel_prefix or path.name
    builder.add(
        ParsedBlock(
            "image",
            content=f"图片文件：{path.name}",
            page_no=1,
            image_path=rel_path,
            section=path.name,
        )
    )
    return builder.blocks
