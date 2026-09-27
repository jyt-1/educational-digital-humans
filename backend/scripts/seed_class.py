# [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 30 人演示班级数据
"""造一个"看得见学情"的演示班级：30 名学生，作答分布刻意做成有梯度的。

**为什么必须有真实分布**：学情看板的价值全在"数字看起来是真的"。若 30 人里有
28 人没有任何作答，看板会满屏"覆盖 1/30"——功能是对的，演示是废的。
所以在 10 个知识点上铺开作答，让覆盖率落在 60% 左右、且有 4~5 个明确薄弱点。

**幂等**：按班级名与用户名判存在，重复跑不会造重复数据。
**不碰演示账号**：`demo_student` 由 seed_learn.py 负责，本脚本只加 30 个新学生。

用法：
    cd backend
    python scripts/seed_class.py            # 造数据
    python scripts/seed_class.py --reset    # 先删本脚本造的班与学生再重造
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models.learn import Attempt, KnowledgePoint, Question, StudentProfile  # noqa: E402
from app.models.teach import Class, ClassMember  # noqa: E402
from app.models.user import ROLE_STUDENT, User  # noqa: E402

CLASS_NAME = "人工智能2401班"
COURSE_NAME = "人工智能导论"
STUDENT_PASSWORD = "demo123456"
STUDENT_TOTAL = 30
# 固定种子：每次重造得到同一份分布，截图与文档里的数字才对得上
RANDOM_SEED = 20260927

# 知识点 -> (班级平均正确率, 参与作答的学生比例)。数字是刻意排的：
# 前 4 个明显薄弱（看板的主要看点），中间几个接近达标线，后几个已掌握
KP_PROFILE: list[tuple[str, float, float]] = [
    ("反向传播", 0.32, 0.70),
    ("梯度下降", 0.38, 0.80),
    ("损失函数", 0.44, 0.77),
    ("矩阵运算", 0.51, 0.90),
    ("神经网络", 0.63, 0.87),
    ("激活函数", 0.68, 0.83),
    ("过拟合与正则化", 0.72, 0.67),
    ("卷积神经网络", 0.79, 0.60),
    ("循环神经网络", 0.86, 0.53),
    ("注意力机制", 0.91, 0.47),
]


def _kp_by_name(db) -> dict[str, KnowledgePoint]:
    rows = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.is_placeholder == 0)
    ).all()
    return {node.name: node for node in rows}


def _question_for(db, node: KnowledgePoint) -> Question:
    """取该知识点下的一道题；没有就造一道（`Attempt.question_id` 是 NOT NULL）。"""
    existing = db.scalar(select(Question).where(Question.kp_id == node.id).limit(1))
    if existing is not None:
        return existing
    question = Question(
        kp_id=node.id, qtype="单选", stem=f"{node.name} 基础练习", answer="A", difficulty="中等"
    )
    db.add(question)
    db.flush()
    return question


def reset(db) -> None:
    klass = db.scalar(select(Class).where(Class.name == CLASS_NAME))
    if klass is None:
        return
    student_ids = list(
        db.scalars(select(ClassMember.student_id).where(ClassMember.class_id == klass.id))
    )
    db.execute(delete(ClassMember).where(ClassMember.class_id == klass.id))
    db.execute(delete(Class).where(Class.id == klass.id))
    if student_ids:
        db.execute(delete(Attempt).where(Attempt.student_id.in_(student_ids)))
        db.execute(delete(StudentProfile).where(StudentProfile.student_id.in_(student_ids)))
        db.execute(delete(User).where(User.id.in_(student_ids)))
    db.commit()
    print(f"[reset] 已删除「{CLASS_NAME}」及其 {len(student_ids)} 名学生")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="先删本脚本造的班与学生")
    ap.add_argument("--teacher", default="demo_teacher", help="班级归属的教师登录名")
    args = ap.parse_args()

    init_db()
    rng = random.Random(RANDOM_SEED)

    with SessionLocal() as db:
        if args.reset:
            reset(db)

        teacher = db.scalar(select(User).where(User.username == args.teacher))
        if teacher is None:
            raise SystemExit(f"找不到教师账号 {args.teacher}，先跑 seed_learn.py")

        klass = db.scalar(
            select(Class).where(Class.teacher_id == teacher.id, Class.name == CLASS_NAME)
        )
        if klass is None:
            klass = Class(name=CLASS_NAME, course_name=COURSE_NAME, teacher_id=teacher.id)
            db.add(klass)
            db.flush()
            print(f"[建班] {CLASS_NAME}（id={klass.id}）")
        else:
            print(f"[已存在] {CLASS_NAME}（id={klass.id}）")

        # ---- 30 名学生 ----
        students: list[User] = []
        for index in range(1, STUDENT_TOTAL + 1):
            username = f"stu2401{index:02d}"
            student = db.scalar(select(User).where(User.username == username))
            if student is None:
                student = User(
                    username=username,
                    password_hash=hash_password(STUDENT_PASSWORD),
                    role=ROLE_STUDENT,
                    display_name=f"学生{index:02d}",
                )
                db.add(student)
                db.flush()
            students.append(student)

        linked = set(
            db.scalars(select(ClassMember.student_id).where(ClassMember.class_id == klass.id))
        )
        added = 0
        for student in students:
            if student.id not in linked:
                db.add(ClassMember(class_id=klass.id, student_id=student.id))
                added += 1
        db.flush()
        print(f"[成员] 新增 {added} 人，共 {len(students)} 人")

        # ---- 作答分布 ----
        student_ids = [s.id for s in students]
        has_data = db.scalar(
            select(Attempt.id).where(Attempt.student_id.in_(student_ids)).limit(1)
        )
        if has_data is not None:
            print("[跳过] 已有作答记录，不重复铺数据（要重来请加 --reset）")
        else:
            nodes = _kp_by_name(db)
            written = 0
            covered = 0
            for kp_name, rate, participation in KP_PROFILE:
                node = nodes.get(kp_name)
                if node is None:
                    print(f"[警告] 知识点「{kp_name}」不在图谱里，跳过")
                    continue
                covered += 1
                question = _question_for(db, node)
                for student in students:
                    if rng.random() > participation:
                        continue
                    for _ in range(rng.randint(2, 5)):
                        db.add(
                            Attempt(
                                student_id=student.id,
                                question_id=question.id,
                                kp_id=node.id,
                                user_answer="A",
                                is_correct=rng.random() < rate,
                            )
                        )
                        written += 1
            db.commit()
            print(f"[作答] 写入 {written} 条，覆盖 {covered}/{len(KP_PROFILE)} 个知识点")

        member_count = len(
            list(db.scalars(select(ClassMember.id).where(ClassMember.class_id == klass.id)))
        )

    print(f"\n完成。班级「{CLASS_NAME}」共 {member_count} 人，学生口令 {STUDENT_PASSWORD}")
    print("下一步：以 demo_teacher 登录，进「班级学情 → 我的班级」查看看板")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
