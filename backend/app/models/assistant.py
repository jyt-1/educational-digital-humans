# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 知识库与问答模型
"""智能助教 4 张表：kb_docs / kb_chunks / conversations / messages。

表结构与设计文档-工单16 第三章「数据库设计 · 工单18 智能助教」一致：
- 知识库分 public（全用户共享）与 private（按 owner_id 隔离）两类；
- 切块支持多模态类型（text / table / image / formula），citation 元数据齐备以支撑引用溯源；
- 问答会话与消息落库，消息带 citations_json 引用快照。
向量索引与本文档表一一对应，另存于 ChromaDB（collection：public / u_{user_id}）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

SCOPE_PUBLIC = "public"
SCOPE_PRIVATE = "private"
SCOPES = (SCOPE_PUBLIC, SCOPE_PRIVATE)

# 解析状态机：pending → parsing → done / failed
PARSE_PENDING = "pending"
PARSE_PARSING = "parsing"
PARSE_DONE = "done"
PARSE_FAILED = "failed"

# 块类型（工单18 要求的多模态内容）
CHUNK_TEXT = "text"
CHUNK_TABLE = "table"
CHUNK_IMAGE = "image"
CHUNK_FORMULA = "formula"
CHUNK_TYPES = (CHUNK_TEXT, CHUNK_TABLE, CHUNK_IMAGE, CHUNK_FORMULA)

# 支持解析的文档格式（工单原文：PDF、Office 文档 DOC/DOCX/PPT/PPTX/XLS/XLSX、图像）
FILE_TYPE_EXTS: dict[str, tuple[str, ...]] = {
    "pdf": (".pdf",),
    "docx": (".docx",),
    "doc": (".doc",),
    "pptx": (".pptx",),
    "ppt": (".ppt",),
    "xlsx": (".xlsx",),
    "xls": (".xls",),
    "image": (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff"),
}
ALLOWED_EXTS = tuple(ext for exts in FILE_TYPE_EXTS.values() for ext in exts)


class KbDoc(Base):
    """知识库文档。public 库的 owner_id 记录上传教师（学生不可写公共库）。"""

    __tablename__ = "kb_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_PRIVATE)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)  # 相对 uploads/ 的路径
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="pdf")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default=PARSE_PENDING)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    chunks: Mapped[list["KbChunk"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", passive_deletes=True
    )


class KbChunk(Base):
    """文档切块。表格转 Markdown、图片存路径、公式保留原文与上下文，均可被引用回显。"""

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kb_docs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 块序号（即段落号）
    chunk_type: Mapped[str] = mapped_column(String(16), nullable=False, default=CHUNK_TEXT)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    doc: Mapped["KbDoc"] = relationship(back_populates="chunks")


class Conversation(Base):
    """问答会话，按 user_id 隔离。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    """会话消息。citations_json 为回答所依据的引用快照（文件名/页码/块类型/片段）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
