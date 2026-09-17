# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 知识库接口
"""知识库接口：上传（异步多模态解析）、列表、详情、删除、重新解析、块回显、混合检索。

权限（设计文档 4.2.3 节三重隔离的第三重）：
- 公共库：所有登录用户可读；**仅教师/管理员可写**（学生不能往公共库塞资料）；
- 私有库：只有 owner 本人可读写，任何接口都强制按 user_id 过滤。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models.assistant import (
    CHUNK_TYPES,
    SCOPE_PRIVATE,
    SCOPE_PUBLIC,
    SCOPES,
    KbChunk,
    KbDoc,
)
from app.models.user import ROLE_ADMIN, ROLE_TEACHER, User
from app.schemas.assistant import (
    ChunkOut,
    CitationOut,
    DocDetail,
    DocOut,
    SearchRequest,
    SearchResponse,
    chunk_to_out,
    doc_to_out,
)
from app.schemas.common import ApiResponse
from app.services import embedding, kb_ingest, retriever, rerank

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kb", tags=["智能助教·知识库"])

# 文档详情页最多返回多少个块预览
_PREVIEW_CHUNKS = 50

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
}


# ------------------------------------------------------------------ 权限工具

def _visible_filter(user: User):
    """当前用户可见的文档范围：公共库 + 自己的私有库。"""
    return or_(
        KbDoc.scope == SCOPE_PUBLIC,
        and_(KbDoc.scope == SCOPE_PRIVATE, KbDoc.owner_id == user.id),
    )


def can_write(user: User, doc: KbDoc) -> bool:
    """公共库仅教师/管理员可写；私有库仅本人可写。"""
    if doc.scope == SCOPE_PUBLIC:
        return user.role in (ROLE_TEACHER, ROLE_ADMIN)
    return doc.owner_id == user.id


def can_read(user: User, doc: KbDoc) -> bool:
    if doc.scope == SCOPE_PUBLIC:
        return True
    return doc.owner_id == user.id


def _get_doc(db: Session, doc_id: int) -> KbDoc:
    doc = db.scalar(select(KbDoc).where(KbDoc.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return doc


def _owner_names(db: Session, docs: list[KbDoc]) -> dict[int, str]:
    ids = {doc.owner_id for doc in docs if doc.owner_id}
    if not ids:
        return {}
    rows = db.execute(
        select(User.id, User.display_name, User.username).where(User.id.in_(ids))
    ).all()
    return {row[0]: (row[1] or row[2]) for row in rows}


# ------------------------------------------------------------------ 文档 CRUD

@router.post("/upload", summary="上传文档并异步解析入库")
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(..., description="PDF/Word/PPT/Excel/图像"),
    scope: str = Form(SCOPE_PRIVATE, description="public=公共库(仅教师) / private=我的私有库"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DocOut]:
    """上传后立即返回，解析在后台进行，前端轮询 parse_status 即可。"""
    if scope not in SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"scope 只能是 {'/'.join(SCOPES)}",
        )
    if scope == SCOPE_PUBLIC and user.role not in (ROLE_TEACHER, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="公共知识库仅教师/管理员可上传，学生可上传到自己的私有知识库",
        )

    content = await file.read()
    try:
        doc = kb_ingest.create_doc(
            db,
            user=user,
            filename=file.filename or "未命名文档",
            content=content,
            scope=scope,
        )
    except kb_ingest.KbUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    background.add_task(kb_ingest.parse_and_index, doc.id)
    return ApiResponse.ok(
        doc_to_out(doc, owner_name=user.display_name or user.username),
        msg="上传成功，正在后台解析",
    )


@router.get("/docs", summary="文档列表")
def list_docs(
    scope: str | None = Query(None, description="public / private，缺省为全部可见"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[DocOut]]:
    stmt = select(KbDoc).where(_visible_filter(user))
    if scope == SCOPE_PUBLIC:
        stmt = stmt.where(KbDoc.scope == SCOPE_PUBLIC)
    elif scope == SCOPE_PRIVATE:
        stmt = stmt.where(KbDoc.scope == SCOPE_PRIVATE, KbDoc.owner_id == user.id)

    docs = list(db.scalars(stmt.order_by(KbDoc.id.desc())).all())
    names = _owner_names(db, docs)
    return ApiResponse.ok([doc_to_out(doc, names.get(doc.owner_id or 0)) for doc in docs])


@router.get("/docs/{doc_id}", summary="文档详情（含块统计与预览）")
def doc_detail(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DocDetail]:
    doc = _get_doc(db, doc_id)
    if not can_read(user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该文档")

    stats = dict(
        db.execute(
            select(KbChunk.chunk_type, func.count(KbChunk.id))
            .where(KbChunk.doc_id == doc.id)
            .group_by(KbChunk.chunk_type)
        ).all()
    )
    chunk_stats = {key: int(stats.get(key, 0)) for key in CHUNK_TYPES}
    chunk_stats["total"] = int(sum(stats.values()))

    chunks = list(
        db.scalars(
            select(KbChunk)
            .where(KbChunk.doc_id == doc.id)
            .order_by(KbChunk.chunk_index)
            .limit(_PREVIEW_CHUNKS)
        ).all()
    )
    base = doc_to_out(doc, _owner_names(db, [doc]).get(doc.owner_id or 0))
    return ApiResponse.ok(
        DocDetail(
            **base.model_dump(),
            chunk_stats=chunk_stats,
            chunks=[chunk_to_out(chunk) for chunk in chunks],
        )
    )


@router.delete("/docs/{doc_id}", summary="删除文档及其向量")
def delete_doc(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    doc = _get_doc(db, doc_id)
    if not can_write(user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该文档")
    kb_ingest.purge_doc(db, doc)
    return ApiResponse.ok({"doc_id": doc_id}, msg="已删除")


@router.post("/docs/{doc_id}/reparse", summary="重新解析（切块/向量重建）")
def reparse_doc(
    doc_id: int,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DocOut]:
    doc = _get_doc(db, doc_id)
    if not can_write(user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该文档")
    kb_ingest.reset_for_reparse(db, doc)
    background.add_task(kb_ingest.parse_and_index, doc.id)
    return ApiResponse.ok(doc_to_out(doc), msg="已开始重新解析")


# ------------------------------------------------------------------ 块与图片回显

@router.get("/chunks/{chunk_id}", summary="切块详情（引用原文）")
def chunk_detail(
    chunk_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ChunkOut]:
    chunk = db.scalar(select(KbChunk).where(KbChunk.id == chunk_id))
    if chunk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="内容块不存在")
    doc = _get_doc(db, chunk.doc_id)
    if not can_read(user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该内容块")
    return ApiResponse.ok(chunk_to_out(chunk))


@router.get("/chunks/{chunk_id}/image", summary="图片块原图（引用回显）")
def chunk_image(
    chunk_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    chunk = db.scalar(select(KbChunk).where(KbChunk.id == chunk_id))
    if chunk is None or not chunk.image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该内容块没有图片")
    doc = _get_doc(db, chunk.doc_id)
    if not can_read(user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该图片")

    abs_path = settings.upload_dir / chunk.image_path
    # 必须 is_file()：早期 image_parser 存过目录（"kb/5"），exists() 对目录也返回 True，
    # 于是 FileResponse 打开目录在发送时才炸成 500。老数据靠这里兜住，报 404 而不是 500。
    if not abs_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片文件已丢失")
    media_type = _MEDIA_TYPES.get(Path(chunk.image_path).suffix.lower(), "application/octet-stream")
    return FileResponse(path=str(abs_path), media_type=media_type)


# ------------------------------------------------------------------ 混合检索

@router.post("/search", summary="混合检索（向量 + 关键词 + 可选重排）")
async def search(
    payload: SearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SearchResponse]:
    try:
        hits = await retriever.search(
            db,
            question=payload.question,
            user=user,
            top_k=payload.top_k,
            scope=payload.scope,
            use_rerank=payload.use_rerank,
        )
    except embedding.EmbeddingNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    effective_rerank = (
        payload.use_rerank if payload.use_rerank is not None else rerank.is_enabled()
    )
    return ApiResponse.ok(
        SearchResponse(
            question=payload.question,
            rerank_enabled=bool(effective_rerank),
            citations=[CitationOut(**hit.to_citation(i)) for i, hit in enumerate(hits, start=1)],
        )
    )
