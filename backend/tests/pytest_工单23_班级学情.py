# [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 班级模型、聚合口径、教师接口与备课注入测试
"""工单23 用例。口径依据设计文档 3.2.8：mean-of-means + 强制覆盖率 + class_id 空则不注入。"""

from __future__ import annotations

from itertools import count

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import hash_password
from app.db import SessionLocal
from app.models.learn import Attempt, KnowledgePoint, Question
from app.models.teach import Class, ClassMember
from app.models.user import ROLE_STUDENT, ROLE_TEACHER, User

# 本文件专属课程名。知识点用课程名与工单19 用例的图谱隔开，
# 两边断言互不干扰（唯一约束是 (course, name)，不同课程不会撞）
COURSE = "工单23测试课程"
KP_NAMES = ["基础概念", "关键原理", "进阶算法", "综合应用"]


# ------------------------------------------------------------------ 造数辅助
#
# ⚠️ 两条铁律，都是从 conftest 的实情推出来的（别改成"看起来更省事"的写法）：
#
# 1. **不复用 conftest 的学生，也不复用 `teacher_zhang`。**
#    测试库初始只有 `student_li` **一个**学生——`_student_ids(4)` 根本拿不到 4 个人。
#    教师同理：直接 `where(role=='teacher')` 会随机取到两个教师之一。
# 2. **每个用例都用全新学生**（工单19 的 `_new_student` 就是为此而设）。
#    本文件前面用例写下的作答会永久留在库里，复用学生会让"无证据"类断言
#    （覆盖率、`build_analytics_brief` 返回 None）静默失真——**测试还是绿的，
#    但它验的东西已经不对了**。

_SEQ = count(1)


def _new_students(n: int) -> list[int]:
    """新建 n 个**全新**学生（零作答），返回 id 列表。"""
    created: list[int] = []
    with SessionLocal() as db:
        for _ in range(n):
            index = next(_SEQ)
            student = User(
                username=f"stu23_{index:03d}",
                password_hash=hash_password("pwd123456"),
                role=ROLE_STUDENT,
                display_name=f"学生{index:02d}",
            )
            db.add(student)
            db.flush()
            created.append(student.id)
        db.commit()
    return created


def _owner_id() -> int:
    """班级归属教师。自建而非复用夹具账号——不依赖夹具执行顺序。"""
    with SessionLocal() as db:
        teacher = db.scalar(select(User).where(User.username == "teacher_23"))
        if teacher is None:
            teacher = User(
                username="teacher_23",
                password_hash=hash_password("pwd123456"),
                role=ROLE_TEACHER,
                display_name="工单23教师",
            )
            db.add(teacher)
            db.commit()
        return teacher.id


@pytest.fixture(scope="session")
def kps(client) -> dict[str, int]:
    """本文件专属知识点。会话级——知识点是只读参照数据，建一次即可。"""
    with SessionLocal() as db:
        for order_no, name in enumerate(KP_NAMES):
            exists = db.scalar(
                select(KnowledgePoint).where(
                    KnowledgePoint.course == COURSE, KnowledgePoint.name == name
                )
            )
            if exists is None:
                db.add(KnowledgePoint(course=COURSE, name=name, order_no=order_no))
        db.commit()
        return {
            node.name: node.id
            for node in db.scalars(
                select(KnowledgePoint).where(KnowledgePoint.course == COURSE)
            )
        }


def _make_class(name: str, course: str = COURSE) -> int:
    """建一个班，返回 id。**每条用例各自建班、各自用新学生**。"""
    with SessionLocal() as db:
        klass = Class(name=name, course_name=course, teacher_id=_owner_id())
        db.add(klass)
        db.commit()
        return klass.id


def _add_members(class_id: int, student_ids: list[int]) -> None:
    with SessionLocal() as db:
        for student_id in student_ids:
            db.add(ClassMember(class_id=class_id, student_id=student_id))
        db.commit()


def _question_for(kp_id: int) -> int:
    """取该知识点下的一道题；没有就造一道。

    **`Attempt.question_id` 是 NOT NULL**，作答不能凭空插——必须挂在一道真题上。
    `source`/`source_id` 留空：这两个字段上的部分唯一索引只管「有来源」的题
    （给 `/kp/sync` 的幂等键用），留空即不受它管（同工单19 的造题方式）。
    """
    with SessionLocal() as db:
        existing = db.scalar(select(Question.id).where(Question.kp_id == kp_id).limit(1))
        if existing is not None:
            return existing
        question = Question(
            kp_id=kp_id,
            qtype="单选",
            stem=f"辅助练习题（kp={kp_id}）",
            options_json='["A. 正确项", "B. 干扰项"]',
            answer="A",
            difficulty="中等",
            source=None,
            source_id=None,
        )
        db.add(question)
        db.commit()
        return question.id


def _answer(student_id: int, kp_id: int, *, correct: bool) -> None:
    """直接写一条作答，绕过 `/learn/answer`——掌握度与时间衰减都可预期。

    `is_correct` 是 Boolean，`user_answer` 是列名（**不是 `student_answer`**）。
    """
    question_id = _question_for(kp_id)
    with SessionLocal() as db:
        db.add(
            Attempt(
                student_id=student_id,
                question_id=question_id,
                kp_id=kp_id,
                user_answer="A",
                is_correct=correct,
            )
        )
        db.commit()


# ------------------------------------------------------------------ Task 1


def test_class_tables_created(client):
    """两张新表能被 create_all 建出来。"""
    assert _make_class("冒烟班") is not None


def test_class_member_unique(client):
    """同一学生不能被重复加进同一个班（唯一约束）。"""
    class_id = _make_class("唯一约束班")
    student_id = _new_students(1)[0]
    with SessionLocal() as db:
        db.add(ClassMember(class_id=class_id, student_id=student_id))
        db.commit()
        db.add(ClassMember(class_id=class_id, student_id=student_id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_class_member_cascade(client):
    """删班带走成员行。

    依赖 `app/db.py` 里逐连接开启的 `PRAGMA foreign_keys=ON`——
    SQLite 默认不开，`ondelete="CASCADE"` 会静默失效。
    """
    class_id = _make_class("级联班")
    student_id = _new_students(1)[0]
    with SessionLocal() as db:
        db.add(ClassMember(class_id=class_id, student_id=student_id))
        db.commit()
        db.delete(db.get(Class, class_id))
        db.commit()
        left = db.scalar(select(ClassMember).where(ClassMember.class_id == class_id))
        assert left is None
