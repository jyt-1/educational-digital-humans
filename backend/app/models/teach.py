# [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 班级与班级成员模型
"""教师侧的「班级」组织实体（设计文档 3.3.1/3.3.2）。

**为什么要有这张表**：在此之前仓库里没有一个能回答"我班学生"的实体——
`teaching_plans.course_name` / `questions.course` 都只是**字符串列**，
"人工智能导论"这门课下有哪些学生，系统答不出来。于是 `attempts` / `student_profile`
只能回流给学生自己，教师侧看不到任何学情。这两张表补的就是这一个缺口。

**一处刻意的简化**（设计文档 2.2 场景五第 1 条）：一个班对应一门课，不建"班-课程"
多对多。看板与备课反哺都按课程维度取数，多对多是过度设计。反过来，一个学生
**可以属于多个班**（选修课的现实），这不多花成本，故不加只按 student_id 的唯一约束。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Class(Base):
    """一个教学班。`course_name` 用字符串而非外键，与仓库既有口径一致。"""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    course_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 建班教师。不做 ON DELETE CASCADE：删教师账号不该静默删掉整班数据
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    __table_args__ = (
        Index("idx_classes_teacher", "teacher_id"),
        # 同一教师下班级重名无意义，且会让前端下拉框出现两个一模一样的选项
        UniqueConstraint("teacher_id", "name", name="uq_classes_teacher_name"),
    )


class ClassMember(Base):
    """班级成员。只存"谁在班里"——学生的画像仍由 attempts 现算，此处不冗余。"""

    __tablename__ = "class_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    __table_args__ = (
        UniqueConstraint("class_id", "student_id", name="uq_classmem_class_student"),
        Index("idx_classmem_class", "class_id"),
        Index("idx_classmem_stu", "student_id"),
    )
