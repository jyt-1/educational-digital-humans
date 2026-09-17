# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 图像文档解析器
"""图片类文档（PNG/JPG/BMP/GIF/WEBP/TIFF）入库。

多模态处理（工单18）：图像本身作为 image 块入库，原文件即引用回显源（不复制、不转码）。
本机无 GPU、不做 OCR（CLAUDE.md 第 8 节已确认降级），因此图片的检索入口是
文件名 + 上传时填写的说明（由调用方拼进 ``rel_prefix`` 以外的上下文）。

约定：``rel_prefix`` 与其余解析器一致，是**目录**前缀（如 ``kb/12``），
解析器把文件名接在后面得到 ``kb/12/示意图.png``——即该图片相对 uploads/ 的完整路径。
图片**不复制、不转码**，原文件本身就是引用回显的源，故这里只登记路径。
"""

from __future__ import annotations

from pathlib import Path

from app.services.parsers.base import BlockBuilder, ParsedBlock


def parse(path: Path, image_dir: Path | None = None, rel_prefix: str = "") -> list[ParsedBlock]:
    builder = BlockBuilder()
    # rel_prefix 是目录（见 ``base.save_image_bytes``：它也是把文件名接在前缀后面的）。
    # 早期这里写成直接取 rel_prefix，存进去的就成了目录本身 "kb/5"，
    # 引用回显时 FileResponse 打开一个目录 → 500。图片类型的文档必须走拼接。
    rel_path = f"{rel_prefix.strip('/')}/{path.name}" if rel_prefix.strip("/") else path.name
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
