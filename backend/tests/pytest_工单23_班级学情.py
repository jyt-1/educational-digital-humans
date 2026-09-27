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
from app.services import class_profile, learn_profile, llm_client, prompts

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


# ------------------------------------------------------------------ Task 2


def test_compute_keeps_student_dimension(client, kps):
    """内核必须按学生分组返回——这是 mean-of-means 的前提。

    若哪天有人把内核改回"一组学生一个合计"，这条会挂。
    """
    sid_a, sid_b = _new_students(2)
    kp_id = kps["基础概念"]
    _answer(sid_a, kp_id, correct=True)          # A 只答 1 题且对
    for _ in range(9):
        _answer(sid_b, kp_id, correct=False)     # B 答 9 题全错

    with SessionLocal() as db:
        grouped = learn_profile._compute(db, [sid_a, sid_b])

    assert kp_id in grouped, "该知识点应出现在结果里"
    assert set(grouped[kp_id]) == {sid_a, sid_b}, "两个学生都必须各自留一层"
    assert grouped[kp_id][sid_a].mastery == pytest.approx(1.0)
    assert grouped[kp_id][sid_b].mastery == pytest.approx(0.0)


def test_compute_mastery_unchanged_for_single_student(client, kps):
    """单生入口行为不变：仍是 dict[kp_id, MasteryRecord]。"""
    sid = _new_students(1)[0]
    kp_id = kps["基础概念"]
    _answer(sid, kp_id, correct=True)

    with SessionLocal() as db:
        result = learn_profile.compute_mastery(db, sid)

    assert isinstance(result[kp_id], learn_profile.MasteryRecord)
    assert result[kp_id].kp_id == kp_id
    assert result[kp_id].mastery == pytest.approx(1.0)
    assert result[kp_id].attempt_count >= 1


# ------------------------------------------------------------------ Task 3


def test_class_mastery_is_mean_of_means(client, kps):
    """口径：先算每个学生、再对全班取平均——不是把所有作答混在一起算。

    A 答 1 题全对、B 答 9 题全错：
      mean-of-means = 0.5，pooled = 0.1。这条用例必须能区分两者，否则等于没测。
    """
    klass = _make_class("口径班")
    sid_a, sid_b = _new_students(2)
    kp_id = kps["基础概念"]
    _add_members(klass, [sid_a, sid_b])
    _answer(sid_a, kp_id, correct=True)
    for _ in range(9):
        _answer(sid_b, kp_id, correct=False)

    with SessionLocal() as db:
        result = class_profile.class_mastery(db, klass)

    assert result[kp_id].mastery == pytest.approx(0.5), "是 mean-of-means 而非 pooled"
    assert result[kp_id].mastery != pytest.approx(0.1), "若等于 0.1 说明写成了混算"
    assert result[kp_id].student_count == 2
    assert result[kp_id].class_size == 2


def test_class_mastery_coverage_three_cases(client, kps):
    """覆盖率三种情形：空班 / 全员无证据 / 部分学生有证据。

    ② 是全篇最脆的一条：它依赖"这几个学生一条作答都没有"。**必须用 `_new_students`**，
    改成复用既有学生就会静默失真（详见文件头两条铁律）。
    """
    # ① 空班
    empty = _make_class("空班")
    with SessionLocal() as db:
        assert class_profile.class_mastery(db, empty) == {}
        assert class_profile.coverage(db, empty)["class_size"] == 0

    # ② 有成员但全员无任何作答
    silent = _make_class("沉默班")
    _add_members(silent, _new_students(3))
    with SessionLocal() as db:
        assert class_profile.class_mastery(db, silent) == {}
        assert class_profile.coverage(db, silent)["covered_students"] == 0

    # ③ 部分学生有证据
    partial = _make_class("部分班")
    sids = _new_students(4)
    kp_id = kps["基础概念"]
    _add_members(partial, sids)
    _answer(sids[0], kp_id, correct=True)

    with SessionLocal() as db:
        result = class_profile.class_mastery(db, partial)
        cov = class_profile.coverage(db, partial)

    assert result[kp_id].student_count == 1, "只有 1 人有证据"
    assert result[kp_id].class_size == 4, "分母是全班人数，不是有证据的人数"
    assert cov["class_size"] == 4
    assert cov["covered_students"] == 1
    assert cov["rate"] == pytest.approx(0.25)


def test_heatmap_shape(client, kps):
    """热力图数据形状：cells 是 `[学生下标, 知识点下标, 掌握度]`，缺失格不出现。

    两个学生里只有 sids[0] 答了题，于是网格应当是 1 列 × 1 行、1 个格子。
    断言写死具体下标，是为了防住"行列转置"这类看不出来的错——转置后
    形状对得上、图却画反了。
    """
    klass = _make_class("热力班")
    sids = _new_students(2)
    kp_id = kps["基础概念"]
    _add_members(klass, sids)
    _answer(sids[0], kp_id, correct=True)   # 只有 sids[0] 有数据

    with SessionLocal() as db:
        grid = class_profile.class_heatmap(db, klass)

    assert grid["kp_ids"] == [kp_id], "只有一个知识点有证据"
    assert grid["student_ids"] == [sids[0]], "只列有证据的学生，否则整片空白"
    assert grid["cells"] == [[0, 0, 1.0]], "1 学生 × 1 知识点，答对 → 1.0"
    assert len(grid["students"]) == 1 and grid["students"][0], "x 轴标签要有名字"


def test_build_analytics_brief_none_when_no_evidence(client):
    """全班无任何证据时必须返回 None——否则教案模板会出现"要求依据下方数据、
    下方却没有数据"的自相矛盾提示词。"""
    klass = _make_class("无证据班")
    _add_members(klass, _new_students(2))
    with SessionLocal() as db:
        assert class_profile.build_analytics_brief(db, klass) is None


def test_build_analytics_brief_states_denominator(client, kps):
    """有数据时 brief 必须写明分母与"不得编造"约束（设计文档 3.2.8 第(3)条）。"""
    klass = _make_class("文本班")
    sids = _new_students(3)
    kp_id = kps["基础概念"]
    _add_members(klass, sids)
    for _ in range(3):
        _answer(sids[0], kp_id, correct=False)  # 1/3 有证据且全错

    with SessionLocal() as db:
        brief = class_profile.build_analytics_brief(db, klass)

    assert brief is not None
    assert "不得编造" in brief
    assert "3 人中 1 人" in brief, "必须写明分母：3 人中的 1 人 ≠ 全班 1 人"
    assert "文本班" in brief


# ------------------------------------------------------------------ Task 4


def test_class_crud_and_permissions(client, teacher_token, student_token, other_teacher_token, auth):
    """建班 / 列表 / 加人 / 移人 / 越权。"""
    # 学生不能建班
    resp = client.post(
        "/api/teach/classes",
        json={"name": "学生建的班", "course_name": "人工智能导论"},
        headers=auth(student_token),
    )
    assert resp.status_code == 403

    # 教师建班
    resp = client.post(
        "/api/teach/classes",
        json={"name": "接口班", "course_name": "人工智能导论"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    class_id = resp.json()["data"]["id"]

    # 教师列表看得到自己的班
    resp = client.get("/api/teach/classes", headers=auth(teacher_token))
    assert any(item["id"] == class_id for item in resp.json()["data"]["items"])

    # 别的教师看不见
    resp = client.get("/api/teach/classes", headers=auth(other_teacher_token))
    assert all(item["id"] != class_id for item in resp.json()["data"]["items"])

    # 别的教师不能往这个班加人（越权一律 403，设计文档 2.2 场景五验收标准）
    resp = client.post(
        f"/api/teach/classes/{class_id}/members",
        json={"usernames": ["student_li"]},
        headers=auth(other_teacher_token),
    )
    assert resp.status_code == 403

    # 按 username 批量加人，逐行返回明细
    resp = client.post(
        f"/api/teach/classes/{class_id}/members",
        json={"usernames": ["student_li", "不存在的人"]},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    rows = {row["username"]: row for row in resp.json()["data"]["items"]}
    assert rows["student_li"]["ok"] is True
    assert rows["不存在的人"]["ok"] is False
    assert rows["不存在的人"]["reason"], "失败行必须给出原因"
    assert resp.json()["data"]["added"] == 1

    # 学生看得到自己在的班（同一接口两种视角）
    resp = client.get("/api/teach/classes", headers=auth(student_token))
    assert any(item["id"] == class_id for item in resp.json()["data"]["items"])

    # 学生不能看班级学生清单
    resp = client.get(f"/api/teach/classes/{class_id}/students", headers=auth(student_token))
    assert resp.status_code == 403

    # 教师可以
    resp = client.get(f"/api/teach/classes/{class_id}/students", headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    student_id = next(
        row["student_id"] for row in resp.json()["data"]["items"]
        if row["username"] == "student_li"
    )

    # 移出成员
    resp = client.delete(
        f"/api/teach/classes/{class_id}/members/{student_id}", headers=auth(teacher_token)
    )
    assert resp.status_code == 200
    resp = client.get(f"/api/teach/classes/{class_id}/students", headers=auth(teacher_token))
    assert all(row["student_id"] != student_id for row in resp.json()["data"]["items"])


def test_class_name_conflict(client, teacher_token, auth):
    """同一教师下班级重名返回 400，不是 500。"""
    payload = {"name": "重名班", "course_name": "人工智能导论"}
    client.post("/api/teach/classes", json=payload, headers=auth(teacher_token))
    resp = client.post("/api/teach/classes", json=payload, headers=auth(teacher_token))
    assert resp.status_code == 400


def test_insight_returns_structured_and_rendered(client, teacher_token, student_token, auth, kps):
    """/insight 同时给出结构化聚合、热力图与渲染好的 brief——教师能核对将喂给模型什么。"""
    resp = client.post(
        "/api/teach/classes",
        json={"name": "看板班", "course_name": "人工智能导论"},
        headers=auth(teacher_token),
    )
    class_id = resp.json()["data"]["id"]
    sid = _new_students(1)[0]
    _add_members(class_id, [sid])
    kp_id = kps["基础概念"]
    for _ in range(2):
        _answer(sid, kp_id, correct=False)

    resp = client.get(f"/api/teach/classes/{class_id}/insight", headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["coverage"]["covered_students"] == 1
    assert data["weak_points"], "全错的学生应产生薄弱点"
    assert data["heatmap"]["cells"], "热力图应有格子"
    assert data["brief"] and "不得编造" in data["brief"]

    # 学生无权访问看板
    resp = client.get(f"/api/teach/classes/{class_id}/insight", headers=auth(student_token))
    assert resp.status_code == 403


# ------------------------------------------------------------------ Task 5

# 词表：出现任何一个都说明学情泄漏进了不该有的提示词里。
# **不含「不得编造」**——那句防幻觉约束在**两个分支都有**（未绑班级时同样要拦住
# 模型自己编人数），把它放进词表会让本用例对着正常输出报假警。词表只收
# "只有拿到学情才可能出现的词"。（已核对：这几个词在当前 prompts.py 中一个都没有。）
_ANALYTICS_WORDS = ("本班学情", "薄弱知识点", "掌握度", "覆盖率", "难度配比")


def test_prompt_has_no_analytics_when_class_id_absent(client):
    """class_id 为空 → 提示词中不得出现任何学情字样（词表断言，不是"看起来没有"）。"""
    messages = prompts.build_messages(
        "教案",
        subject="人工智能",
        course_name="人工智能导论",
        chapter="第三章",
        knowledge_points=["反向传播"],
        difficulty="中等",
        objectives=[],
    )
    text = "".join(message["content"] for message in messages)
    leaked = [word for word in _ANALYTICS_WORDS if word in text]
    assert not leaked, f"未绑班级却出现了学情字样：{leaked}"


def test_prompt_injects_analytics_when_class_id_present(client, kps):
    """class_id 非空 → 提示词含学情段，且数字与 /insight 一致（不是"含某句话"这种弱断言）。"""
    klass = _make_class("注入班")
    sids = _new_students(3)
    kp_id = kps["基础概念"]
    _add_members(klass, sids)
    for _ in range(3):
        _answer(sids[0], kp_id, correct=False)

    with SessionLocal() as db:
        brief = class_profile.build_analytics_brief(db, klass)
    assert brief is not None

    messages = prompts.build_messages(
        "教案",
        subject="人工智能",
        course_name="人工智能导论",
        chapter="第三章",
        knowledge_points=["反向传播"],
        difficulty="中等",
        objectives=[],
        profile_context=brief,
    )
    text = "".join(message["content"] for message in messages)
    assert "本班学情" in text
    assert "3 人中 1 人" in text, "分母必须原样出现在提示词里"
    # 教案模板的分支应已切到"引用具体数字"
    assert "引用具体数字" in text
    assert "结合高职学生的知识基础与常见认知障碍简要分析" not in text


def test_lesson_template_falls_back_without_analytics(client):
    """未带学情时教案模板退回原表述——不得出现"要求依据下方数据、下方却没有数据"。"""
    messages = prompts.build_messages(
        "教案",
        subject=None,
        course_name="人工智能导论",
        chapter=None,
        knowledge_points=[],
        difficulty=None,
        objectives=[],
    )
    text = messages[1]["content"]
    assert "结合高职学生的知识基础与常见认知障碍简要分析" in text
    assert "引用具体数字" not in text


def test_generate_endpoint_injects_class_analytics(client, teacher_token, auth, monkeypatch, kps):
    """走 HTTP 确认 class_id 真的被转换成提示词里的学情段。

    不真调 LLM：monkeypatch 掉 chat_stream，把收到的 messages 截下来。

    **班级必须经 HTTP 建成，不能用 `_make_class`**：后者把班挂在本文件自建的
    `teacher_23` 名下，而这里的请求是以 `teacher_zhang` 发出的——注入逻辑会
    按设计静默忽略"非本班"。用 `_make_class` 会让这条用例验的是忽略分支。
    """
    resp = client.post(
        "/api/teach/classes",
        json={"name": "端到端班", "course_name": "人工智能导论"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    klass = resp.json()["data"]["id"]

    sids = _new_students(2)
    kp_id = kps["基础概念"]
    _add_members(klass, sids)
    _answer(sids[0], kp_id, correct=False)

    captured: dict = {}

    async def fake_stream(messages, **kwargs):
        captured["messages"] = messages
        yield "## 一、教学目标\n（测试桩产出）"

    monkeypatch.setattr(llm_client, "chat_stream", fake_stream)

    resp = client.post(
        "/api/lesson/generate",
        json={
            "content_type": "教案",
            "course_name": "人工智能导论",
            "subject": "人工智能",
            "knowledge_points": ["反向传播"],
            "class_id": klass,
        },
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    assert captured.get("messages"), "chat_stream 应已被调用"
    text = "".join(m["content"] for m in captured["messages"])
    assert "本班学情" in text
    assert "2 人中 1 人" in text


def test_generate_ignores_class_id_of_other_teacher(
    client, teacher_token, other_teacher_token, auth, monkeypatch, kps
):
    """拿别班的 class_id 生成：**不报错、也不注入**（静默忽略）。

    这条守的是 `api/lesson.py` 里那段"非本班一律忽略"的分支。它的存在理由
    是"生成是主流程，不能因为一个失效 id 整个失败"——若哪天被改成抛 403/
    500，或反过来把别班学情注了进去，这里会挂。
    """
    resp = client.post(
        "/api/teach/classes",
        json={"name": "别班", "course_name": "人工智能导论"},
        headers=auth(other_teacher_token),
    )
    other_class = resp.json()["data"]["id"]
    sids = _new_students(2)
    kp_id = kps["基础概念"]
    _add_members(other_class, sids)
    _answer(sids[0], kp_id, correct=False)

    captured: dict = {}

    async def fake_stream(messages, **kwargs):
        captured["messages"] = messages
        yield "## 一、教学目标\n（测试桩产出）"

    monkeypatch.setattr(llm_client, "chat_stream", fake_stream)

    resp = client.post(
        "/api/lesson/generate",
        json={
            "content_type": "教案",
            "course_name": "人工智能导论",
            "class_id": other_class,   # 别班的 id
        },
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    text = "".join(m["content"] for m in captured["messages"])
    assert "本班学情" not in text, "别班学情不得注入"
    assert "别班" not in text, "连班级名都不该出现"
