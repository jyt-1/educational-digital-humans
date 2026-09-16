# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 用户模型（跨工单基础）
"""用户与角色。工单18 的私有知识库隔离、工单19 的 student_id、工单20 的上报人均依赖本模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ROLE_ADMIN = "admin"
VALID_ROLES = (ROLE_TEACHER, ROLE_STUDENT, ROLE_ADMIN)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # 只存哈希，禁止明文或可逆加密（设计文档 5.1 节）
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_STUDENT)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
