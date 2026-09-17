# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 知识库与问答数据结构
"""智能助教的请求/响应模型（Pydantic v2）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.assistant import KbChunk, KbDoc

# 检索范围：all=公共库+我的私有库，public=仅公共库，private=仅我的私有库
SEARCH_SCOPES = ("all", "public", "private")


# ------------------------------------------------------------------ 知识库

class DocOut(BaseModel):
    """文档列表项。"""

    id: int
    owner_id: int | None = None
    owner_name: str | None = None
    scope: str
    filename: str
    file_type: str
    file_size: int
    parse_status: str
    parse_error: str | None = None
    chunk_count: int
    created_at: datetime | None = None


class ChunkOut(BaseModel):
    """切块（多模态：正文/表格/图片/公式）。"""

    id: int
    chunk_index: int
    chunk_type: str
    content: str
    page_no: int | None = None
    image_path: str | None = None
    image_url: str | None = None


class DocDetail(DocOut):
    """文档详情：附块类型统计与内容预览。"""

    chunk_stats: dict[str, int] = Field(default_factory=dict)
    chunks: list[ChunkOut] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """混合检索请求。"""

    question: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=20)
    scope: str = "all"
    use_rerank: bool | None = None

    @field_validator("scope")
    @classmethod
    def _check_scope(cls, value: str) -> str:
        if value not in SEARCH_SCOPES:
            raise ValueError(f"scope 只能是 {'/'.join(SEARCH_SCOPES)}")
        return value


class CitationOut(BaseModel):
    """引用来源（答案角标 [n] 对应项）。"""

    index: int
    chunk_id: int
    doc_id: int
    filename: str
    page_no: int | None = None
    chunk_type: str
    scope: str
    snippet: str
    image_url: str | None = None
    score: float = 0.0
    matched_by: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """检索结果（检索调试页与问答接口共用）。"""

    question: str
    rerank_enabled: bool
    citations: list[CitationOut] = Field(default_factory=list)


# ------------------------------------------------------------------ 问答

class ChatRequest(BaseModel):
    """流式问答请求。"""

    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    scope: str = "all"
    use_rerank: bool | None = None

    @field_validator("scope")
    @classmethod
    def _check_scope(cls, value: str) -> str:
        if value not in SEARCH_SCOPES:
            raise ValueError(f"scope 只能是 {'/'.join(SEARCH_SCOPES)}")
        return value


class MessageOut(BaseModel):
    """会话消息。"""

    id: int
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None


class ConversationOut(BaseModel):
    """会话列表项。"""

    id: int
    title: str | None = None
    created_at: datetime | None = None
    message_count: int = 0


class ConversationDetail(ConversationOut):
    """会话详情：含全部消息与引用。"""

    messages: list[MessageOut] = Field(default_factory=list)


# ------------------------------------------------------------------ 构造函数

def chunk_to_out(chunk: KbChunk) -> ChunkOut:
    return ChunkOut(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        chunk_type=chunk.chunk_type,
        content=chunk.content or "",
        page_no=chunk.page_no,
        image_path=chunk.image_path,
        image_url=f"/api/kb/chunks/{chunk.id}/image" if chunk.chunk_type == "image" else None,
    )


def doc_to_out(doc: KbDoc, owner_name: str | None = None) -> DocOut:
    return DocOut(
        id=doc.id,
        owner_id=doc.owner_id,
        owner_name=owner_name,
        scope=doc.scope,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        parse_status=doc.parse_status,
        parse_error=doc.parse_error,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
    )


def loads_citations(raw: str | None) -> list[dict[str, Any]]:
    """解析消息里的引用 JSON，坏数据不炸接口。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []
