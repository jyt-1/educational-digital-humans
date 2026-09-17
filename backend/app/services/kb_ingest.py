# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 知识库入库流水线
"""上传 → 解析（多模态）→ 切块 → 向量化 → 落库，并维护解析状态与失败原因。

流水线（工单18「用户流程 1. 知识库构建」）：
    kb_docs(pending) → 后台解析 → kb_chunks + Chroma 向量 → kb_docs(done/failed)

解析在后台任务里跑（BackgroundTasks），上传接口立即返回，前端轮询状态；
解析耗时长的大文档不会阻塞请求。任何一步失败都会写 failed 与可读原因，
前端列表能直接看到「哪一步失败、为什么失败」。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.assistant import (
    PARSE_DONE,
    PARSE_FAILED,
    PARSE_PARSING,
    PARSE_PENDING,
    KbChunk,
    KbDoc,
)
from app.models.user import User
from app.services import embedding, retriever, vector_store
from app.services.chunking import chunk_blocks
from app.services.parsers import detect_file_type, parse_document

logger = logging.getLogger(__name__)


class KbUploadError(ValueError):
    """上传校验失败（大小/格式），接口层转 400。"""


def validate_upload(filename: str, content: bytes) -> str:
    """校验并返回文件类型。"""
    file_type = detect_file_type(filename, content[:16])
    if file_type is None:
        raise KbUploadError(
            f"暂不支持的文件格式：{filename}。"
            "支持 PDF / Word(doc,docx) / PPT(ppt,pptx) / Excel(xls,xlsx) / 图像。"
        )
    limit = settings.KB_MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > limit:
        raise KbUploadError(
            f"文件过大（{len(content) / 1024 / 1024:.1f}MB），单文档上限 {settings.KB_MAX_UPLOAD_MB}MB"
        )
    if not content:
        raise KbUploadError("文件内容为空")
    return file_type


def create_doc(
    db: Session,
    *,
    user: User,
    filename: str,
    content: bytes,
    scope: str,
) -> KbDoc:
    """落盘 + 建 kb_docs 记录（状态 pending）。解析由调用方另行触发。"""
    file_type = validate_upload(filename, content)

    doc = KbDoc(
        owner_id=user.id,
        scope=scope,
        filename=Path(filename).name,
        file_path="",
        file_type=file_type,
        file_size=len(content),
        parse_status=PARSE_PENDING,
    )
    db.add(doc)
    db.flush()  # 先拿到 doc.id，文件按 id 归档

    suffix = Path(filename).suffix.lower() or f".{file_type}"
    stored_name = f"{uuid.uuid4().hex[:8]}{suffix}"
    rel_path = f"kb/{doc.id}/{stored_name}"
    abs_path = settings.upload_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)

    doc.file_path = rel_path
    db.commit()
    db.refresh(doc)
    logger.info("知识库文档已入库：id=%s %s（%s，%d 字节）", doc.id, doc.filename, scope, len(content))
    return doc


async def parse_and_index(doc_id: int) -> None:
    """后台任务：解析文档 → 切块 → 向量化 → 写 kb_chunks 与向量库。

    使用独立 Session：后台任务不依赖请求依赖的生命周期。
    """
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        doc = db.scalar(select(KbDoc).where(KbDoc.id == doc_id))
        if doc is None:
            logger.warning("待解析文档不存在：id=%s", doc_id)
            return

        doc.parse_status = PARSE_PARSING
        doc.parse_error = None
        db.commit()

        try:
            chunk_count = await _index_doc(db, doc)
        except Exception as exc:  # noqa: BLE001 - 失败原因要落到文档状态里给用户看
            db.rollback()
            logger.exception("文档解析失败：id=%s", doc_id)
            doc = db.scalar(select(KbDoc).where(KbDoc.id == doc_id))
            if doc is not None:
                doc.parse_status = PARSE_FAILED
                doc.parse_error = str(exc)[:500]
                doc.chunk_count = 0
                db.commit()
            vector_store.delete_doc_vectors(doc_id, doc.scope if doc else "", doc.owner_id if doc else None)
            return

        doc.parse_status = PARSE_DONE
        doc.parse_error = None
        doc.chunk_count = chunk_count
        db.commit()
        retriever.invalidate_index_cache()
        logger.info("文档解析完成：id=%s，%d 块", doc_id, chunk_count)
    finally:
        db.close()


async def _index_doc(db: Session, doc: KbDoc) -> int:
    """解析并索引单篇文档，返回切块数。"""
    abs_path = settings.upload_dir / doc.file_path
    if not abs_path.exists():
        raise FileNotFoundError(f"源文件不存在：{doc.file_path}")

    image_dir = settings.kb_image_dir / str(doc.id)
    rel_prefix = f"kb/{doc.id}"

    # 1) 多模态解析（各格式解析器见 services/parsers/）
    blocks = parse_document(
        abs_path, file_type=doc.file_type, image_dir=image_dir, rel_prefix=rel_prefix
    )

    # 2) 切块（约 500 字、重叠 80）
    chunks = chunk_blocks(
        blocks, size=settings.KB_CHUNK_SIZE, overlap=settings.KB_CHUNK_OVERLAP
    )
    if not chunks:
        raise ValueError("文档未解析出任何可入库内容（可能是空文档或纯扫描件）")

    # 3) 先清旧数据（重新解析场景），再写入
    db.execute(delete(KbChunk).where(KbChunk.doc_id == doc.id))
    db.flush()
    vector_store.delete_doc_vectors(doc.id, doc.scope, doc.owner_id)

    rows = [
        KbChunk(
            doc_id=doc.id,
            chunk_index=chunk.chunk_index,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            image_path=chunk.image_path,
            page_no=chunk.page_no,
        )
        for chunk in chunks
    ]
    db.add_all(rows)
    db.flush()  # 拿到 chunk.id 作为向量元数据

    # 4) 向量化（表格/图片块的 content 即其检索入口）
    vectors = await embedding.embed_texts([row.content for row in rows])
    if len(vectors) != len(rows):
        raise ValueError("向量化结果数量与切块数不一致，已中止入库")

    items = [
        {
            "chunk_id": row.id,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "chunk_type": row.chunk_type,
            "page_no": row.page_no,
        }
        for row in rows
    ]
    vector_store.upsert_chunks(
        doc_id=doc.id,
        scope=doc.scope,
        owner_id=doc.owner_id,
        filename=doc.filename,
        items=items,
        embeddings=vectors,
    )

    for row, vector in zip(rows, vectors, strict=True):
        row.vector_id = f"{doc.id}:{row.chunk_index}"
    db.flush()
    return len(rows)


def reset_for_reparse(db: Session, doc: KbDoc) -> None:
    """把文档状态重置为待解析，并清空旧块与向量（重新解析入口）。"""
    db.execute(delete(KbChunk).where(KbChunk.doc_id == doc.id))
    doc.parse_status = PARSE_PENDING
    doc.parse_error = None
    doc.chunk_count = 0
    db.commit()
    vector_store.delete_doc_vectors(doc.id, doc.scope, doc.owner_id)
    retriever.invalidate_index_cache()


def purge_doc(db: Session, doc: KbDoc) -> None:
    """彻底删除文档：向量 → 切块 → 源文件与抽出的图片 → 记录。"""
    vector_store.delete_doc_vectors(doc.id, doc.scope, doc.owner_id)
    retriever.invalidate_index_cache()

    abs_path = settings.upload_dir / doc.file_path
    image_dir = settings.kb_image_dir / str(doc.id)
    _remove(abs_path)
    if image_dir.exists():
        for item in image_dir.iterdir():
            _remove(item)
        _remove(image_dir, allow_dir=True)

    db.execute(delete(KbChunk).where(KbChunk.doc_id == doc.id))
    db.delete(doc)
    db.commit()
    logger.info("知识库文档已删除：id=%s %s", doc.id, doc.filename)


def _remove(path: Path, *, allow_dir: bool = False) -> None:
    try:
        if path.is_dir() and allow_dir:
            path.rmdir()
        elif path.is_file():
            path.unlink()
    except OSError as exc:  # noqa: BLE001 - 文件清理失败不影响数据库一致性
        logger.warning("清理文件失败：%s（%s）", path, exc)
