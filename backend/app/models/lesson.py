# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 备课相关模型
"""智能备课 6 张表：teaching_plans / plan_versions / coursewares / exercises / exam_questions / resources。

LLM 生成内容以 JSON 存储，支持二次编辑；版本快照支持历史回溯与回滚。
生成的习题与试题供工单19 个性化学习的题库使用。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# 五类生成内容（工单17 正文列了"案例"，产出物列了"月考试题"，两者都要有）
CONTENT_TYPES = ("教案", "课件", "习题", "案例", "试题")


class TeachingPlan(Base):
    """备课生成主记录：一次生成任务一条，内容以结构化 JSON 存储以支持二次编辑。"""

    __tablename__ = "teaching_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    course_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    knowledge_points: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    objectives: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)  # 结构化内容
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["PlanVersion"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanVersion.version_no"
    )


class PlanVersion(Base):
    """版本快照：每次保存生成一条，支持历史回溯与回滚（工单17 明确要求）。"""

    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("plan_id", "version_no", name="uq_plan_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("teaching_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    plan: Mapped["TeachingPlan"] = relationship(back_populates="versions")


class Courseware(Base):
    """课件结构化内容（plan_id 关联，slides_json 为 JSON 数组）。"""

    __tablename__ = "coursewares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("teaching_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slides_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Exercise(Base):
    """习题。供工单19 个性化学习抽题。"""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("teaching_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    qtype: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 单选|多选|判断|简答
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_point: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ExamQuestion(Base):
    """试题（月考试题）。供工单19 抽题。"""

    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("teaching_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    qtype: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_point: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Resource(Base):
    """可引用校本资源：支撑工单17"资源检索与引用"（检索结果一键插入正文并标注来源）。"""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 教材/校本/网络
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 关联工单18 的 kb_docs
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
