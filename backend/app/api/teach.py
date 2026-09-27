# [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 教师侧班级与学情接口
"""班级管理与学情看板接口（设计文档 3.2.2 第(5)组）。

**为什么单开一个文件而不是塞进 `api/learn.py`**：`learn.py` 已 1100+ 行，且"班级"
是**教师侧组织概念**，与"学生自己的学习"不同域；混在一起会让权限口径
（教师管班 vs 学生自学）在同一文件内交织。

**`GET /api/teach/classes` 一个接口两种视角**（教师看自己建的、学生看自己所在的），
不拆成两条：前端两处问的都是"我该看到哪些班"这一个问题。

**越权一律 403**（设计文档 2.2 场景五验收标准写明"教师访问别班 一律 403"）。
注意这与 `api/lesson.py::_get_own_plan` 的 404 口径不同——那里用 404 隐藏
"该 id 是否存在"，这里用 403 是因为班级 id 只在自己的列表里出现、枚举风险低，
且设计文档已把 403 定为验收口径。**以设计文档为准。**
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_teacher
from app.db import get_db
from app.models.teach import Class, ClassMember
from app.models.user import ROLE_STUDENT, ROLE_TEACHER, User
from app.schemas.common import ApiResponse
from app.schemas.teach import (
    ClassCreateRequest,
    MemberAddRequest,
    MemberAddResponse,
    MemberRow,
    StudentRow,
)
from app.services import class_profile, learn_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teach", tags=["班级学情"])


def _get_own_class(db: Session, class_id: int, user: User) -> Class:
    """取本人建的班；不存在或非本人一律 **403**（口径见模块 docstring）。"""
    klass = db.get(Class, class_id)
    if klass is None or klass.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该班级")
    return klass


@router.post("/classes", summary="建班")
def create_class(
    payload: ClassCreateRequest,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    exists = db.scalar(
        select(Class).where(Class.teacher_id == user.id, Class.name == payload.name)
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="同名班级已存在")

    klass = Class(name=payload.name, course_name=payload.course_name, teacher_id=user.id)
    db.add(klass)
    db.commit()
    return ApiResponse.ok(
        {
            "id": klass.id,
            "name": klass.name,
            "course_name": klass.course_name,
            "student_count": 0,
        }
    )


@router.get("/classes", summary="班级列表（教师看自己建的，学生看自己所在的）")
def list_classes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    if user.role == ROLE_TEACHER:
        rows = list(
            db.scalars(select(Class).where(Class.teacher_id == user.id).order_by(Class.id))
        )
    else:
        rows = list(
            db.scalars(
                select(Class)
                .join(ClassMember, ClassMember.class_id == Class.id)
                .where(ClassMember.student_id == user.id)
                .order_by(Class.id)
            )
        )

    items = [
        {
            "id": klass.id,
            "name": klass.name,
            "course_name": klass.course_name,
            "teacher_id": klass.teacher_id,
            "student_count": len(class_profile.member_ids(db, klass.id)),
            "is_mine": klass.teacher_id == user.id,
        }
        for klass in rows
    ]
    return ApiResponse.ok({"items": items})


@router.post("/classes/{class_id}/members", summary="按 username 批量加人")
def add_members(
    class_id: int,
    payload: MemberAddRequest,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    klass = _get_own_class(db, class_id, user)
    existing = set(class_profile.member_ids(db, klass.id))

    items: list[MemberRow] = []
    for username in payload.usernames:
        name = username.strip()
        if not name:
            items.append(MemberRow(username=username, ok=False, reason="登录名为空"))
            continue
        student = db.scalar(select(User).where(User.username == name))
        if student is None:
            items.append(MemberRow(username=name, ok=False, reason="用户不存在"))
            continue
        if student.role != ROLE_STUDENT:
            items.append(MemberRow(username=name, ok=False, reason="该账号不是学生"))
            continue
        if student.id in existing:
            items.append(
                MemberRow(username=name, ok=False, student_id=student.id,
                          display_name=student.display_name, reason="已在班级中")
            )
            continue
        db.add(ClassMember(class_id=klass.id, student_id=student.id))
        existing.add(student.id)
        items.append(
            MemberRow(username=name, ok=True, student_id=student.id,
                      display_name=student.display_name)
        )

    db.commit()
    return ApiResponse.ok(
        MemberAddResponse(
            items=items,
            added=sum(1 for row in items if row.ok),
            failed=sum(1 for row in items if not row.ok),
        ).model_dump()
    )


@router.delete("/classes/{class_id}/members/{student_id}", summary="移出成员")
def remove_member(
    class_id: int,
    student_id: int,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    klass = _get_own_class(db, class_id, user)
    link = db.scalar(
        select(ClassMember).where(
            ClassMember.class_id == klass.id, ClassMember.student_id == student_id
        )
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该学生不在本班")
    db.delete(link)
    db.commit()
    return ApiResponse.ok({"removed": student_id})


@router.get("/classes/{class_id}/students", summary="班级学生清单（供下钻）")
def list_students(
    class_id: int,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    klass = _get_own_class(db, class_id, user)
    ids = class_profile.member_ids(db, klass.id)
    if not ids:
        return ApiResponse.ok({"items": []})

    users = {row.id: row for row in db.scalars(select(User).where(User.id.in_(ids)))}

    items = []
    for student_id in ids:
        student = users.get(student_id)
        if student is None:
            continue
        # 逐个学生算：这一屏是"下钻"，人数有限，清晰优先于省查询。
        # compute_mastery 已过滤「未归类」占位节点，这里不需要再过滤
        records = learn_profile.compute_mastery(db, student_id)
        weak = sum(1 for v in records.values() if v.mastery < learn_profile.WEAK_THRESHOLD)
        items.append(
            StudentRow(
                student_id=student_id,
                username=student.username,
                display_name=student.display_name,
                kp_count=len(records),
                weak_count=weak,
            ).model_dump()
        )
    return ApiResponse.ok({"items": items})


@router.get("/classes/{class_id}/insight", summary="看板主数据（聚合 + 热力图 + brief）")
def get_insight(
    class_id: int,
    top_n: int = 10,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """同时返回三种呈现，**同源**。

    前端学情卡直接用 `brief` 做生成前预览，教师可核对"将要喂给模型的是什么"。
    这正是本功能敢说自己"可核对"的全部依据——若前端另写一套摘要，
    就重新制造了"看到的与喂进去的不一致"这一信任缺口。
    """
    klass = _get_own_class(db, class_id, user)
    data = class_profile.class_insight(db, klass.id, top_n=top_n)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级不存在")
    data["brief"] = class_profile.build_analytics_brief(db, klass.id)
    return ApiResponse.ok(data)
