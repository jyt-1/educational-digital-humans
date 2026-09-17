# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 测试用例
"""工单19 个性化学习推荐 pytest 用例。

当前覆盖：**前置修复 P0 —— SQLite 外键约束**（见设计文档 3.3.3）。
随工单19 功能落地，本文件继续追加知识点匹配漏斗、画像与时间衰减、
路径上溯、自适应难度、试卷模式、AIGC 错题本、related 惰性补挂等用例。

LLM 全部 mock，测试不依赖真实 API Key 与网络。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.learn import (
    REASON_BANK_EMPTY,
    REASON_NO_QUESTION_FOR_KP,
    REASON_NO_TARGET,
)
from app.db import SessionLocal, foreign_keys_enabled
from app.models.assistant import Conversation, KbChunk, KbDoc, Message
from app.models.learn import (
    DIFFICULTY_HARD,
    DIFFICULTY_MEDIUM,
    Attempt,
    KnowledgePoint,
    KpAlias,
    MessageKp,
    MistakeBook,
    PracticeState,
    Question,
    ScoreImport,
    StudentProfile,
)
from app.models.lesson import ExamQuestion, Exercise, TeachingPlan
from app.services.kp_match import (
    METHOD_ALIAS,
    METHOD_DICT,
    METHOD_EXACT,
    METHOD_NONE,
    METHOD_PLACEHOLDER,
    METHOD_VECTOR,
    ON_UNMATCHED_DROP,
    ON_UNMATCHED_PLACEHOLDER,
    VECTOR_THRESHOLD,
    KpIndex,
    KpNode,
    MatchResult,
    load_index,
    match_label,
    match_text,
    normalize_difficulty,
    normalize_label,
)

# 一个必然不存在的父行 id，用于验证"悬空外键会被拒绝"
_MISSING_ID = 999_999


@pytest.fixture(autouse=True)
def _ensure_schema(client):
    """建表发生在 app 的 lifespan 里，只有 client 夹具会触发它。

    本文件有若干用例直接用 SessionLocal 操作 ORM，若不在它们之前建表，
    会得到 `no such table: kb_chunks` 这种与被测行为无关的失败。
    """


@pytest.fixture(scope="module")
def owner_id(client, teacher_token, auth) -> int:
    """拿一个真实存在的用户 id——外键开启后，子行必须挂在真实父行上。"""
    resp = client.get("/api/auth/me", headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


class TestForeignKeysEnabled:
    """前置修复 P0：SQLite 默认 `PRAGMA foreign_keys=0`，模型里声明的
    `ondelete="CASCADE"` 从不生效；而 `passive_deletes=True` 又让 SQLAlchemy
    把级联完全托付给数据库——两边都不做，子表就静默留下孤儿行。

    工单19 新增的 10 张表全靠外键串联（attempts→questions、
    mistake_book→attempts、knowledge_points 自关联先修链），
    孤儿行会直接污染画像与图谱，故在开工前先把这个口子堵上。
    """

    def test_pragma_is_on(self):
        assert foreign_keys_enabled() is True

    def test_dangling_child_insert_is_rejected(self):
        """判据不是"pragma 读数为 1"，而是"悬空外键真的写不进去"。"""
        db = SessionLocal()
        try:
            db.add(KbChunk(doc_id=_MISSING_ID, chunk_index=0, content="孤儿块"))
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.rollback()
            db.close()

    def test_delete_doc_cascades_to_chunks(self, owner_id):
        db = SessionLocal()
        try:
            doc = KbDoc(
                owner_id=owner_id,
                scope="private",
                filename="外键级联用例.pdf",
                file_path="kb/foreign-key-cascade.pdf",
                file_type="pdf",
                file_size=1,
            )
            db.add(doc)
            db.flush()
            doc_id = doc.id

            db.add_all(
                [
                    KbChunk(doc_id=doc_id, chunk_index=0, content="第一块"),
                    KbChunk(doc_id=doc_id, chunk_index=1, content="第二块"),
                ]
            )
            db.commit()
            assert _count_chunks(db, doc_id) == 2

            # 走 ORM 删除：KbDoc.chunks 声明了 passive_deletes=True，
            # SQLAlchemy 不会替数据库删子行，级联是否真的发生全看 pragma
            db.delete(doc)
            db.commit()

            assert _count_chunks(db, doc_id) == 0, "删文档后切块仍在——外键级联没生效"
        finally:
            db.rollback()
            db.close()

    def test_delete_conversation_cascades_to_messages(self, owner_id):
        db = SessionLocal()
        try:
            conversation = Conversation(user_id=owner_id, title="外键级联用例会话")
            db.add(conversation)
            db.flush()
            conversation_id = conversation.id

            db.add(
                Message(conversation_id=conversation_id, role="user", content="梯度下降是什么？")
            )
            db.commit()
            assert _count_messages(db, conversation_id) == 1

            db.delete(conversation)
            db.commit()

            assert _count_messages(db, conversation_id) == 0, "删会话后消息仍在——外键级联没生效"
        finally:
            db.rollback()
            db.close()


def _count_chunks(db, doc_id: int) -> int:
    return db.query(KbChunk).filter(KbChunk.doc_id == doc_id).count()


def _count_messages(db, conversation_id: int) -> int:
    return db.query(Message).filter(Message.conversation_id == conversation_id).count()


# ============================================================ 知识点匹配（3.2.5）

def _index() -> KpIndex:
    """一张小图谱：足以覆盖全等 / 后缀 / 别名 / 词典 / 占位五条路径。"""
    return KpIndex(
        nodes=(
            KpNode(id=1, name="梯度下降"),
            KpNode(id=2, name="反向传播"),
            KpNode(id=3, name="Adam优化器"),
            KpNode(id=4, name="卷积神经网络"),
            KpNode(id=5, name="神经网络"),
            KpNode(id=99, name="未归类", is_placeholder=True),
        ),
        aliases={"adam": 3, "bp": 2},
        placeholder_id=99,
    )


class TestNormalizeLabel:
    """归一化是「两档上线」第一档的判据，也是别名表 norm_label 的写入格式——
    两边必须走同一个函数，否则别名永远命中不了。"""

    @pytest.mark.parametrize(
        ("raw", "expect"),
        [
            ("梯度下降", "梯度下降"),
            ("梯度下降法", "梯度下降"),  # 剥后缀
            ("梯度下降算法", "梯度下降"),
            ("  反向 传播 ", "反向传播"),  # 去空白
            ("反向传播（BP）", "反向传播bp"),  # 去标点、全角折半角
            ("ＡＤＡＭ", "adam"),  # 全角字母 + 大小写
            ("Adam优化器", "adam优化器"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expect):
        assert normalize_label(raw) == expect

    def test_suffix_strip_keeps_short_names_intact(self):
        """短名不能被剥空——"算法"本身若是个节点名，剥完就没了。"""
        assert normalize_label("算法") == "算法"


class TestNormalizeDifficulty:
    """设计文档 3.2.6 的映射表。汇入时执行，不改工单17 已交付的原列。"""

    @pytest.mark.parametrize(
        ("raw", "expect"),
        [
            ("易", "简单"),
            ("简单", "简单"),
            ("基础", "简单"),
            ("入门", "简单"),
            ("难", "困难"),
            ("困难", "困难"),
            ("较难", "困难"),
            ("进阶", "困难"),
            ("高难", "困难"),
            ("中等", "中等"),
            ("中等偏上", "中等"),
            (None, "中等"),
            ("", "中等"),
            ("随便什么", "中等"),
        ],
    )
    def test_mapping(self, raw, expect):
        assert normalize_difficulty(raw) == expect


class TestMatchLabel:
    def test_exact_after_suffix_normalization(self):
        """工单17 生成的是"梯度下降法"，图谱节点是"梯度下降"——这一档要吃下大部分漂移。"""
        result = match_label("梯度下降法", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert result is not None
        assert (result.kp_id, result.method) == (1, METHOD_EXACT)

    def test_alias_hit(self):
        """别名档排在词典档**之前**：别名本身也并入了词典，若顺序反了这里会返回 dict。"""
        result = match_label("BP", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert result is not None
        assert (result.kp_id, result.method) == (2, METHOD_ALIAS)

    # ---- ③ 词典档（v1.4 插入，实测把未归类从 47.8% 压到 5.4%）----

    def test_phrase_label_matches_via_dict(self):
        """老记录（prompt 修正前生成）的标签是**短语**，与节点不是语义距离远、
        而是形态不同（短语 vs 名词短语），本来就该走词典而不是向量。"""
        result = match_label(
            "反向传播的基本原理与适用范围", index=_index(), on_unmatched=ON_UNMATCHED_DROP
        )
        assert result is not None
        assert (result.kp_id, result.method) == (2, METHOD_DICT)

    def test_dict_returns_canonical_node_name(self):
        """matched_text 回填**节点名**而不是命中的片段。
        否则「待归并清单」里同一节点的多种短语写法会显示成多个不同知识点。"""
        result = match_label("神经网络的基本结构", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert (result.kp_id, result.matched_text) == (5, "神经网络")
        assert result.raw_text == "神经网络的基本结构"  # 原始标签保留，供归并清单回显

    def test_exact_beats_dict(self):
        """全等档更便宜也更准，能全等就不该退到词典。"""
        result = match_label("神经网络", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert (result.kp_id, result.method) == (5, METHOD_EXACT)

    def test_dict_respects_span_claiming(self):
        """"卷积神经网络的基本原理"只挂「卷积神经网络」，不能连带把「神经网络」也挂上。"""
        result = match_label(
            "卷积神经网络的基本原理", index=_index(), on_unmatched=ON_UNMATCHED_DROP
        )
        assert result is not None
        assert (result.kp_id, result.method) == (4, METHOD_DICT)

    def test_compound_node_name_is_a_dead_end(self):
        """实测教训的回归防线：节点名若写成"梯度消失与梯度爆炸"这种**复合名**，
        词典扫描反而匹配不上"梯度消失问题""梯度消失的缓解方法"等真实标签
        （实测少命中 4 道题）。节点名必须用单一概念——故拆成两个节点后应当命中。"""
        compound = KpIndex(nodes=(KpNode(id=1, name="梯度消失与梯度爆炸"),))
        split = KpIndex(nodes=(KpNode(id=1, name="梯度消失"),))

        assert match_label("梯度消失问题", index=compound, on_unmatched=ON_UNMATCHED_DROP) is None

        result = match_label("梯度消失问题", index=split, on_unmatched=ON_UNMATCHED_DROP)
        assert result is not None
        assert (result.kp_id, result.method) == (1, METHOD_DICT)

    def test_unmatched_drops(self):
        assert match_label("量子纠缠", index=_index(), on_unmatched=ON_UNMATCHED_DROP) is None

    def test_unmatched_falls_back_to_placeholder(self):
        """题目同步用 placeholder：题目由 LLM 生成，丢了就没了，一条不丢优先。"""
        result = match_label("量子纠缠", index=_index(), on_unmatched=ON_UNMATCHED_PLACEHOLDER)
        assert result is not None
        assert result.kp_id == 99
        assert result.method == METHOD_PLACEHOLDER
        assert result.raw_text == "量子纠缠"  # 原始标签必须留着，供「待归并清单」回显

    def test_placeholder_node_is_not_matchable(self):
        """占位节点只承接兜底，不该被标签直接命中，否则「未归类」会变成一个大杂烩。"""
        result = match_label("未归类", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert result is None

    def test_empty_text(self):
        assert match_label("   ", index=_index(), on_unmatched=ON_UNMATCHED_DROP) is None


class TestMatchText:
    """整句口语化提问。要点是**先把知识点从句子里抠出来**，而不是对整句做向量匹配。"""

    def test_extracts_alias_substring(self):
        """"Adam 是啥"与"Adam优化器"的余弦并不高，但词典里有短别名 "Adam" 就能直接命中。"""
        results = match_text("Adam 是啥", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert [r.kp_id for r in results] == [3]
        assert results[0].method == METHOD_DICT

    def test_longest_match_wins(self):
        """「卷积神经网络」应当整词命中，不能只挂到「神经网络」上。"""
        results = match_text("卷积神经网络怎么训练", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert [r.kp_id for r in results] == [4]

    def test_shorter_key_inside_longer_claim_is_skipped(self):
        """短词若完全落在长词已占用的区间内，不再重复挂——否则挂靠全是噪声。"""
        results = match_text("说说卷积神经网络", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert 5 not in [r.kp_id for r in results]

    def test_multiple_knowledge_points_in_one_question(self):
        """一条提问可以挂多个知识点（API 返回列表的原因）。"""
        results = match_text(
            "反向传播和梯度下降什么关系", index=_index(), on_unmatched=ON_UNMATCHED_DROP
        )
        assert {r.kp_id for r in results} == {1, 2}

    def test_no_match_returns_empty_list(self):
        assert match_text("今天天气不错", index=_index(), on_unmatched=ON_UNMATCHED_DROP) == []

    def test_placeholder_policy_applies_to_text_too(self):
        results = match_text("今天天气不错", index=_index(), on_unmatched=ON_UNMATCHED_PLACEHOLDER)
        assert [r.kp_id for r in results] == [99]

    def test_empty_text(self):
        assert match_text(None, index=_index(), on_unmatched=ON_UNMATCHED_DROP) == []


class TestVectorFallback:
    """第三档默认关闭——判据是「未归类题目在练习候选集中占比 > 20%」，
    而非全库占比（未归类的题本来就不参与取题）。签名里的开关必须先留好。"""

    def test_off_by_default(self):
        """开关关着时，即使给了 embedder 也不该走向量。"""
        called = []

        def _embed(texts):
            called.append(texts)
            return [[1.0, 0.0] for _ in texts]

        result = match_label(
            "梯度下降法", index=_index(), on_unmatched=ON_UNMATCHED_DROP, embed=_embed
        )
        assert result.method == METHOD_EXACT
        assert called == []  # 第一档就命中了，压根不该去编码

    def test_skipped_when_no_embedder(self):
        """开了开关但没给 embedder：不能炸，退化为未命中。"""
        result = match_label(
            "量子纠缠", index=_index(), on_unmatched=ON_UNMATCHED_DROP, use_vector=True
        )
        assert result is None

    def test_hits_when_enabled(self):
        def _embed(texts):
            # 「量子纠缠」与「梯度下降」在高维空间里对齐，其余正交
            return [[1.0, 0.0] if t in ("量子纠缠", "梯度下降") else [0.0, 1.0] for t in texts]

        result = match_label(
            "量子纠缠",
            index=_index(),
            on_unmatched=ON_UNMATCHED_DROP,
            use_vector=True,
            embed=_embed,
        )
        assert result is not None
        assert (result.kp_id, result.method) == (1, METHOD_VECTOR)
        assert result.confidence >= VECTOR_THRESHOLD

    def test_below_threshold_does_not_match(self):
        def _embed(texts):
            return [[1.0, 0.0] if t == "量子纠缠" else [0.6, 0.8] for t in texts]

        result = match_label(
            "量子纠缠",
            index=_index(),
            on_unmatched=ON_UNMATCHED_DROP,
            use_vector=True,
            embed=_embed,
        )
        assert result is None


class TestMatchResultContract:
    """`/learn/related` 的三个出口、`/kp/sync` 的报告与导入失败明细都依赖这个结构。"""

    def test_to_dict_shape(self):
        result = match_label("梯度下降法", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert result.to_dict() == {
            "raw_text": "梯度下降法",
            "kp_id": 1,
            "matched_text": "梯度下降",
            "method": METHOD_EXACT,
            "confidence": 1.0,
        }

    def test_matched_property(self):
        hit = match_label("梯度下降", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        miss = MatchResult("x", None, None, METHOD_NONE, 0.0)
        assert hit.matched is True
        assert miss.matched is False


class TestLoadIndex:
    """`load_index` 是本模块唯一接触数据库的函数，且只读。"""

    def test_loads_nodes_aliases_and_placeholder(self, client):
        from app.db import SessionLocal
        from app.models.learn import KpAlias, KnowledgePoint

        db = SessionLocal()
        try:
            kp = KnowledgePoint(course="测试课程", name="贝叶斯定理")
            db.add(kp)
            db.flush()
            db.add(KpAlias(raw_label="贝叶斯", norm_label="贝叶斯", kp_id=kp.id, source="manual"))
            db.add(
                KnowledgePoint(course="测试课程", name="未归类", is_placeholder=1, order_no=999)
            )
            db.commit()

            index = load_index(db, course="测试课程")

            assert index.placeholder_id is not None
            assert any(n.name == "贝叶斯定理" for n in index.nodes)
            assert index.aliases.get("贝叶斯") == kp.id
        finally:
            db.rollback()
            db.close()


class TestMigration:
    """工单19 增量迁移：`create_all` 只建缺失的表，**不会给已存在的表加列**。

    测试库每次是全新的，`create_all` 直接把 `kp_id` 建进表里，**走不到 ALTER 分支**，
    所以这里必须手工造一个"工单17/18 已交付、工单19 尚未迁移"的旧库来测。
    """

    def test_adds_kp_id_to_legacy_tables(self, tmp_path):
        from sqlalchemy import create_engine

        from app.migrations import run

        legacy = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
        with legacy.begin() as conn:
            # 模拟旧库：exercises / exam_questions 已存在，但都没有 kp_id
            conn.exec_driver_sql("CREATE TABLE exercises (id INTEGER PRIMARY KEY, stem TEXT NOT NULL)")
            conn.exec_driver_sql(
                "CREATE TABLE exam_questions (id INTEGER PRIMARY KEY, stem TEXT NOT NULL)"
            )

        changes = run(legacy)
        assert any("exercises" in c and "kp_id" in c for c in changes), changes
        assert any("exam_questions" in c and "kp_id" in c for c in changes), changes

        with legacy.connect() as conn:
            for table in ("exercises", "exam_questions"):
                cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
                assert "kp_id" in cols, f"{table} 迁移后仍缺 kp_id"

    def test_is_idempotent(self, tmp_path):
        """重跑迁移不能报错、不能重复加列——它是每次启动都会执行的路径。"""
        from sqlalchemy import create_engine

        from app.migrations import run

        legacy = create_engine(f"sqlite:///{tmp_path / 'legacy2.db'}")
        with legacy.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE exercises (id INTEGER PRIMARY KEY, stem TEXT NOT NULL)")

        first = run(legacy)
        second = run(legacy)

        assert any("kp_id" in c for c in first)
        # 第二次只剩 create_all 那一行说明——没有任何结构改动
        assert len(second) == 1, second

    def test_backfills_existing_rows_with_null(self, tmp_path):
        """加列后老行必须可读：kp_id 为 NULL，由首次 `/kp/sync` 回填。"""
        from sqlalchemy import create_engine

        from app.migrations import run

        legacy = create_engine(f"sqlite:///{tmp_path / 'legacy3.db'}")
        with legacy.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE exercises (id INTEGER PRIMARY KEY, stem TEXT NOT NULL)")
            conn.exec_driver_sql("INSERT INTO exercises (id, stem) VALUES (1, '梯度下降是哪类算法？')")

        run(legacy)

        with legacy.connect() as conn:
            row = conn.exec_driver_sql("SELECT id, stem, kp_id FROM exercises WHERE id = 1").fetchone()
        assert row[1] == "梯度下降是哪类算法？"
        assert row[2] is None


# ============================================================ 工单19 功能
#
# 本段用一张独立的小图谱（COURSE = "工单19测试课程"），避免与工单17/18 的测试数据互相污染。
# 断言一律写成**相对**的（"重跑不翻倍"、"多了几道"），不写绝对条数——
# 同一个临时库里还有工单17 生成的题目，`/kp/sync` 会把它们一并汇入。

COURSE = "工单19测试课程"

# (知识点, 先修, 次序)。刻意含一条两级链：微积分基础 → 链式法则，
# 用于验证"沿图谱上溯到最先修薄弱点"不是只往上走一层
GRAPH_SPEC = (
    ("微积分基础", None),
    ("链式法则", "微积分基础"),
    ("神经网络", None),
    ("反向传播", "神经网络"),
    ("梯度下降", "反向传播"),
)


@pytest.fixture(scope="module")
def graph(client) -> dict[str, int]:
    """建测试图谱 + 每个知识点下挂 4 道题（够验证取题与难度档）。"""
    db = SessionLocal()
    try:
        # 「未归类」全库至多一条（部分唯一索引），故按全库判存在、不按课程：
        # 本文件前面的 P0 用例已经在「测试课程」下建过一条，这里必须复用它。
        placeholder = db.query(KnowledgePoint).filter(
            KnowledgePoint.is_placeholder == 1
        ).first()
        if placeholder is None:
            placeholder = KnowledgePoint(
                course=COURSE, name="未归类", is_placeholder=1, order_no=9999
            )
            db.add(placeholder)
        db.commit()

        for order_no, (name, _prereq) in enumerate(GRAPH_SPEC):
            exists = db.query(KnowledgePoint).filter(
                KnowledgePoint.course == COURSE, KnowledgePoint.name == name
            ).first()
            if not exists:
                db.add(KnowledgePoint(course=COURSE, name=name, order_no=order_no))
        db.commit()

        by_name = {
            node.name: node
            for node in db.query(KnowledgePoint)
            .filter(KnowledgePoint.course == COURSE)
            .all()
        }
        for name, prereq in GRAPH_SPEC:
            if prereq and by_name[name].prereq_id is None:
                by_name[name].prereq_id = by_name[prereq].id
        db.commit()

        # 每个知识点 4 道题：两易一中一难，cover 难度档的升/降
        for name, _prereq in GRAPH_SPEC:
            kp = by_name[name]
            if db.query(Question).filter(Question.kp_id == kp.id).count():
                continue
            for index, difficulty in enumerate(
                ["简单", "简单", "中等", DIFFICULTY_HARD]
            ):
                db.add(
                    Question(
                        kp_id=kp.id,
                        qtype="单选",
                        stem=f"{name} 测试题 {index + 1}",
                        options_json='["A. 正确项", "B. 干扰项"]',
                        answer="A",
                        analysis=f"{name} 的解析 {index + 1}",
                        difficulty=difficulty,
                        # 无来源行：这些题不属于工单17 的任何一次生成，
                        # 也就不该被 `/kp/sync` 的幂等键（source, source_id）管到
                        source=None,
                        source_id=None,
                    )
                )
        db.commit()

        ids = {
            node.name: node.id
            for node in db.query(KnowledgePoint)
            .filter(KnowledgePoint.course == COURSE)
            .all()
        }
        # 占位节点可能不在 COURSE 下（复用了 P0 用例建的），但它不属于任何课程，
        # 单独挂一个键，用例读起来才不必关心它建在哪
        ids["未归类"] = placeholder.id
        return ids
    finally:
        db.close()


_LEARNER_SEQ = count(1)


def _new_student(client) -> tuple[int, dict[str, str]]:
    """**每个用例一个全新学生**。

    画像、路径、难度档这三块的状态全挂在 `student_id` 上，共用一个学生会互相污染——
    更麻烦的是 `read_profile` 靠"缓存时间戳 vs 数据源时间戳"判过期，而 SQLite 的
    `CURRENT_TIMESTAMP` 只到秒：同一秒内写入的作答与缓存比不出先后，用例会时灵时不灵。
    换成一生一用例，每条断言的数据来源就只剩本用例自己写的那几行。
    """
    username = f"student_w19_{next(_LEARNER_SEQ)}"
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "pwd123456",
            "role": "student",
            "display_name": "工单19学生",
        },
    )
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": "pwd123456"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    # `/auth/login` 只回 token 与用户对象，id 从 `/auth/me` 取——顺带验证 token 可用
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["data"]["id"], headers


@pytest.fixture
def learner(client) -> int:
    """只要学生 id（服务层用例用）。"""
    return _new_student(client)[0]


@pytest.fixture
def learner_auth(client) -> tuple[int, dict[str, str]]:
    """`(学生 id, 认证头)`（接口层用例用，需要带 token 发请求）。"""
    return _new_student(client)


def _seed_cache(db, student_id: int, masteries: dict[int, float]) -> None:
    """直接写 `student_profile` 缓存行，用于把画像摆到指定状态。

    确定性来自"该生没有任何 `attempts` / `score_imports`"——没有数据源时间戳，
    `read_profile` 就一定命中缓存，不会拿实时计算的结果把这里摆好的数值覆盖掉。
    """
    db.add_all(
        StudentProfile(student_id=student_id, kp_id=kp_id, mastery=mastery)
        for kp_id, mastery in masteries.items()
    )
    db.commit()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _add_attempt(db, *, student_id: int, question: Question, is_correct: bool, days_ago: float = 0.0):
    """直接造作答记录：时间衰减的用例必须能精确控制时间，走接口做不到。"""
    db.add(
        Attempt(
            student_id=student_id,
            question_id=question.id,
            kp_id=question.kp_id,
            user_answer="A" if is_correct else "B",
            is_correct=is_correct,
            created_at=_utcnow() - timedelta(days=days_ago),
        )
    )


# ------------------------------------------------------------ 判分

class TestJudgeAnswer:
    """LLM 生成的答案形态不可控，判分必须比"字符串相等"宽——
    否则演示时会出现"我明明答对了却判错"，这类问题现场无法解释。"""

    @pytest.mark.parametrize(
        ("user", "correct", "options", "expect"),
        [
            ("A", "A", None, True),
            ("a", "A", None, True),  # 大小写
            (" A ", "A", None, True),  # 空白
            ("A", "A. 链式法则", ["A. 链式法则", "B. 贝叶斯公式"], True),  # 学生答字母
            ("链式法则", "A", ["A. 链式法则", "B. 贝叶斯公式"], True),  # 学生答选项文本
            ("A. 链式法则", "A", ["A. 链式法则"], True),  # 整条选项原文
            ("链式法则", "A. 链式法则", ["A. 链式法则"], True),
            ("对", "正确", None, True),  # 判断题同义
            ("√", "对", None, True),
            ("错", "正确", None, False),
            ("B", "A", ["A. 链式法则", "B. 公式"], False),
            ("AB", "BA", None, True),  # 多选顺序无关
            ("A,B", "BA", None, True),
            ("", "A", None, False),  # 未作答
            (None, "A", None, False),
            ("A", "", None, False),  # 题目没有正确答案
        ],
    )
    def test_judge(self, user, correct, options, expect):
        from app.services.learn_answer import judge_answer

        assert judge_answer(user, correct, options) is expect

    def test_load_options_tolerates_dirty_data(self):
        """`options_json` 是 LLM 写入的自由文本列，脏数据不能中断判分。"""
        from app.services.learn_answer import load_options

        assert load_options(None) == []
        assert load_options("不是 JSON") == []
        assert load_options('{"A": "链式法则"}') == ["A. 链式法则"]
        assert load_options('["A. 甲", "B. 乙"]') == ["A. 甲", "B. 乙"]


# ------------------------------------------------------------ 画像

class TestTimeWeight:
    """7 天内 1.0 / 30 天内 0.7 / 更早 0.4（设计文档 4.3）。"""

    @pytest.mark.parametrize(
        ("days_ago", "expect"),
        [(0, 1.0), (6.9, 1.0), (7.1, 0.7), (29.9, 0.7), (30.1, 0.4), (400, 0.4)],
    )
    def test_decay(self, days_ago, expect):
        from app.services.learn_profile import time_weight

        moment = _utcnow() - timedelta(days=days_ago)
        assert time_weight(moment) == expect

    def test_none_is_oldest(self):
        from app.services.learn_profile import time_weight

        assert time_weight(None) == 0.4

    def test_naive_timestamps_are_treated_as_utc(self):
        """`created_at` 由 SQLite 的 CURRENT_TIMESTAMP 写入，那是 UTC。
        若拿本地时间直接相减，东八区会凭空多出 8 小时，档位边界整体偏移。"""
        from app.services.learn_profile import time_weight

        # 刚写入的 UTC 时间必须是"最近"，不能因为时区差被算成 8 小时前
        assert time_weight(_utcnow()) == 1.0

    def test_aware_timestamps_are_converted(self):
        from app.services.learn_profile import time_weight

        aware = datetime.now(timezone.utc) - timedelta(days=10)
        assert time_weight(aware) == 0.7


class TestComputeMastery:
    def test_weighted_average_with_decay(self, graph, learner):
        """两对一错 + 一道 40 天前的答对：新的权重 1.0、旧的 0.4
        → (1+1+0 + 0.4) / (1+1+1+0.4) = 2.4/3.4 ≈ 0.706。
        **旧的那道把掌握度从 0.667 拉高了**——衰减是"降低旧证据的分量"，
        对答错的旧题同样是降低惩罚，方向不能搞反。"""
        from app.services.learn_profile import compute_mastery

        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.kp_id == graph["梯度下降"]).first()
            _add_attempt(db, student_id=learner, question=question, is_correct=True)
            _add_attempt(db, student_id=learner, question=question, is_correct=True)
            _add_attempt(db, student_id=learner, question=question, is_correct=False)
            _add_attempt(
                db, student_id=learner, question=question, is_correct=True, days_ago=40
            )
            db.commit()

            profile = compute_mastery(db, learner)
            record = profile[graph["梯度下降"]]
            assert record.mastery == pytest.approx(2.4 / 3.4, abs=1e-6)
            assert record.attempt_count == 4
        finally:
            db.rollback()
            db.close()

    def test_score_import_counts_as_ratio(self, graph, learner):
        from app.services.learn_profile import compute_mastery

        db = SessionLocal()
        try:
            db.add(
                ScoreImport(
                    batch_id="批次-画像用例",
                    student_id=learner,
                    kp_id=graph["神经网络"],
                    score=6,
                    total=10,
                    raw_label="神经网络",
                )
            )
            db.commit()
            profile = compute_mastery(db, learner)
            assert profile[graph["神经网络"]].mastery == pytest.approx(0.6, abs=1e-6)
            assert profile[graph["神经网络"]].import_count == 1
        finally:
            db.rollback()
            db.close()

    def test_placeholder_is_filtered(self, graph, learner):
        """「未归类」节点的掌握度没有解释力，出现在雷达图上就是一个永远不满、
        也无法补救的轴（设计文档 2.2 场景三第 8 条）。"""
        from app.services.learn_profile import compute_mastery

        db = SessionLocal()
        try:
            placeholder = graph["未归类"]
            question = Question(
                kp_id=placeholder, stem="未归类题", answer="A", difficulty="简单"
            )
            db.add(question)
            db.flush()
            _add_attempt(db, student_id=learner, question=question, is_correct=False)
            db.commit()

            assert placeholder not in compute_mastery(db, learner)
        finally:
            db.rollback()
            db.close()

    def test_kp_without_evidence_is_absent(self, graph, learner):
        """没有任何作答与成绩的知识点**不进画像**，而不是按 0 分算薄弱——
        否则新学生一登录，整张图谱（70 多个节点）都是薄弱点。

        这里有意只在「链式法则」上留证据：它的先修「微积分基础」一点数据都没有，
        若实现把"无证据"当成 0 分，微积分基础就会出现在画像里。"""
        from app.services.learn_profile import compute_mastery

        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.kp_id == graph["链式法则"]).first()
            _add_attempt(db, student_id=learner, question=question, is_correct=True)
            db.commit()

            profile = compute_mastery(db, learner)
            assert graph["链式法则"] in profile
            assert graph["微积分基础"] not in profile
            assert graph["梯度下降"] not in profile
        finally:
            db.close()


class TestProfileCache:
    """`student_profile` 是纯缓存：权威来源为实时计算，缓存缺失或过期必须兜底重算。"""

    def test_missing_cache_triggers_recompute(self, graph, learner):
        from app.services import learn_profile

        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.kp_id == graph["链式法则"]).first()
            _add_attempt(db, student_id=learner, question=question, is_correct=True)
            db.commit()

            # 模拟缓存丢失（历史脏数据 / 手工清表）
            db.query(StudentProfile).filter(StudentProfile.student_id == learner).delete()
            db.commit()

            profile = learn_profile.read_profile(db, learner)
            assert graph["链式法则"] in profile, "缓存缺失时必须实时兜底重算，不得返回空画像"
            cached = db.query(StudentProfile).filter(StudentProfile.student_id == learner).count()
            assert cached == len(profile), "兜底重算后应把缓存回写"
        finally:
            db.close()

    def test_fresh_cache_is_used_without_recompute(self, graph, learner, monkeypatch):
        """缓存新鲜时**不得**重算：证明这是一条真的缓存路径，
        而不是"每次都现算、`student_profile` 表纯属摆设"。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.kp_id == graph["链式法则"]).first()
            _add_attempt(db, student_id=learner, question=question, is_correct=True)
            db.commit()
            learn_profile.refresh_profile_cache(db, learner)

            def _boom(*_args, **_kwargs):
                raise AssertionError("缓存新鲜却重算了画像")

            monkeypatch.setattr(learn_profile, "compute_mastery", _boom)
            profile = learn_profile.read_profile(db, learner)
            assert profile[graph["链式法则"]].mastery == pytest.approx(1.0)
        finally:
            db.close()

    def test_stale_cache_triggers_recompute(self, graph, learner):
        """缓存落后于数据源时必须重算。把缓存的 `updated_at` 往回拨一天来构造
        "落后"状态——直接连写两笔做不到：SQLite 时间戳只到秒，同一秒内比不出先后。"""
        from sqlalchemy import update

        from app.services import learn_profile

        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.kp_id == graph["链式法则"]).first()
            _add_attempt(db, student_id=learner, question=question, is_correct=True)
            db.commit()
            learn_profile.refresh_profile_cache(db, learner)

            db.execute(
                update(StudentProfile)
                .where(StudentProfile.student_id == learner)
                .values(updated_at=_utcnow() - timedelta(days=1))
            )
            db.commit()

            # 答错一次，掌握度应从 1.0 掉到 0.5
            _add_attempt(db, student_id=learner, question=question, is_correct=False)
            db.commit()

            after = learn_profile.read_profile(db, learner)[graph["链式法则"]].mastery
            assert after == pytest.approx(0.5), "缓存已过期，必须重算而不是接着用旧值"
        finally:
            db.close()


# ------------------------------------------------------------ 自适应难度

class TestAdaptiveDifficulty:
    def test_promote_after_three_correct(self, graph, learner):
        from app.services import learn_profile

        db = SessionLocal()
        try:
            state = learn_profile.get_practice_state(db, learner, graph["链式法则"])
            assert state.difficulty == "简单", "新知识点从最易档起步"
            assert learn_profile.apply_answer_to_state(state, True) == "简单"
            assert learn_profile.apply_answer_to_state(state, True) == "简单"
            assert learn_profile.apply_answer_to_state(state, True) == DIFFICULTY_MEDIUM
            assert state.streak_correct == 0, "升档后连对数归零，否则连对 4 题会连升两档"
        finally:
            db.rollback()
            db.close()

    def test_wrong_answer_demotes(self, graph, learner):
        from app.services import learn_profile

        db = SessionLocal()
        try:
            state = learn_profile.get_practice_state(db, learner, graph["反向传播"])
            state.difficulty = DIFFICULTY_HARD
            state.streak_correct = 2
            assert learn_profile.apply_answer_to_state(state, False) == DIFFICULTY_MEDIUM
            assert state.streak_correct == 0
        finally:
            db.rollback()
            db.close()

    @pytest.mark.parametrize(
        ("difficulty", "up", "down"),
        [
            ("简单", "中等", "简单"),
            ("中等", "困难", "简单"),
            ("困难", "困难", "中等"),
        ],
    )
    def test_ladder_is_clamped(self, difficulty, up, down):
        from app.services.learn_profile import demote, promote

        assert promote(difficulty) == up
        assert demote(difficulty) == down

    def test_pick_questions_prefers_current_difficulty(self, graph):
        from app.services import learn_profile

        db = SessionLocal()
        try:
            picked = learn_profile.pick_questions(
                db, kp_id=graph["梯度下降"], difficulty="简单", count=2
            )
            assert len(picked) == 2
            assert all(question.difficulty == "简单" for question in picked)
        finally:
            db.close()

    def test_pick_questions_tops_up_from_neighbours(self, graph):
        """某档题量不足时必须从相邻档补足——练习的价值是"练"，不是"分档"。
        只有 1 道困难题，要 3 道就只能补中等/简单。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            picked = learn_profile.pick_questions(
                db, kp_id=graph["梯度下降"], difficulty=DIFFICULTY_HARD, count=3
            )
            assert len(picked) == 3
            assert picked[0].difficulty == DIFFICULTY_HARD, "当前档的题必须排在最前"
        finally:
            db.close()


# ------------------------------------------------------------ 学习路径

class TestRecommendPath:
    def test_ascent_stops_when_prereq_is_not_weak(self, graph, learner):
        """先修不薄弱时，"最先修薄弱点"就是薄弱点自己，不该无脑往上爬。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            _seed_cache(
                db, learner, {graph["微积分基础"]: 0.7, graph["链式法则"]: 0.3}
            )
            path = learn_profile.recommend_path(db, learner)

            assert [item["name"] for item in path] == ["链式法则"]
            assert path[0]["is_entry"] is True
            assert "30%" in path[0]["reason"], "理由要给出掌握度数字，否则学生无从判断"
        finally:
            db.close()

    def test_weak_prereq_becomes_the_entry(self, graph, learner):
        """先修也薄弱时，入口应上溯到先修，且后继的理由要说明"应先补前置"。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            _seed_cache(
                db, learner, {graph["微积分基础"]: 0.2, graph["链式法则"]: 0.3}
            )
            path = learn_profile.recommend_path(db, learner)

            names = [item["name"] for item in path]
            assert names == ["微积分基础", "链式法则"], names

            entry = path[0]
            assert entry["is_entry"] is True
            assert "链式法则" in entry["reason"], "入口要说明它挡在谁前面"

            follower = path[1]
            assert follower["is_entry"] is False
            assert follower["entry_name"] == "微积分基础"
            assert "微积分基础" in follower["reason"], "后继要指明该先补哪个前置"
        finally:
            db.close()

    def test_ascent_is_cycle_safe(self, graph, learner):
        """图谱是人手工维护的，出现环不该让接口转不出来。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            node = db.get(KnowledgePoint, graph["微积分基础"])
            original = node.prereq_id
            node.prereq_id = graph["链式法则"]  # 微积分基础 ← 链式法则，成环
            db.commit()
            try:
                _seed_cache(
                    db, learner, {graph["微积分基础"]: 0.2, graph["链式法则"]: 0.3}
                )
                path = learn_profile.recommend_path(db, learner)
                assert len(path) == 2, "成环时仍应返回全部薄弱点，只是入口取不到最上游"
            finally:
                node.prereq_id = original
                db.commit()
        finally:
            db.close()

    def test_no_evidence_means_no_path(self, graph):
        """一点数据都没有的学生不该拿到"整张图谱都是薄弱点"的路径。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            assert learn_profile.recommend_path(db, 987_654_321) == []
        finally:
            db.close()

    def test_above_threshold_is_not_weak(self, graph, learner):
        """掌握度 0.6 恰好达标，不该再出现在路径里（阈值是 <0.6 而非 ≤0.6）。"""
        from app.services import learn_profile

        db = SessionLocal()
        try:
            _seed_cache(db, learner, {graph["梯度下降"]: 0.6})
            assert learn_profile.recommend_path(db, learner) == []
        finally:
            db.close()

    def test_limit_truncates_to_the_entry(self, graph, learner):
        from app.services import learn_profile

        db = SessionLocal()
        try:
            _seed_cache(
                db, learner, {graph["微积分基础"]: 0.2, graph["链式法则"]: 0.3}
            )
            path = learn_profile.recommend_path(db, learner, limit=1)
            assert [item["name"] for item in path] == ["微积分基础"]
        finally:
            db.close()


# ------------------------------------------------------------ 题库汇入与归并

W19_STEM_PREFIX = "【工单19测试题】"
# 刻意造两个匹配层级：一个与节点名全等，一个是需要走词典扫描的长短语
LABEL_EXACT = "梯度下降"
LABEL_DICT = "反向传播的基本原理与适用范围"
LABEL_UNKNOWN = "工单19测试用的不存在知识点"


@pytest.fixture(scope="module")
def source_rows(client, graph) -> dict[str, list[int]]:
    """造源表题目：`exercises` 3 条 + `exam_questions` 1 条，覆盖三种匹配层级。"""
    db = SessionLocal()
    try:
        ids = {"exercise": [], "exam": []}
        for index, label in enumerate((LABEL_EXACT, LABEL_DICT, LABEL_UNKNOWN)):
            row = db.query(Exercise).filter(
                Exercise.stem == f"{W19_STEM_PREFIX}习题{index}"
            ).first()
            if row is None:
                row = Exercise(
                    qtype="单选",
                    stem=f"{W19_STEM_PREFIX}习题{index}",
                    options_json='["A. 甲", "B. 乙"]',
                    answer="A",
                    knowledge_point=label,
                    difficulty="基础",  # 归一化到三档的用例，见 3.2.6
                )
                db.add(row)
                db.flush()
            ids["exercise"].append(row.id)

        exam = db.query(ExamQuestion).filter(
            ExamQuestion.stem == f"{W19_STEM_PREFIX}试题0"
        ).first()
        if exam is None:
            exam = ExamQuestion(
                qtype="简答",
                stem=f"{W19_STEM_PREFIX}试题0",
                answer="链式法则",
                knowledge_point="链式法则",
                difficulty="中等",
                score=10,
            )
            db.add(exam)
            db.flush()
        ids["exam"].append(exam.id)

        db.commit()
        return ids
    finally:
        db.close()


class TestSyncQuestions:
    def test_imports_and_attaches(self, client, teacher_token, auth, graph, source_rows):
        from app.services import learn_sync

        db = SessionLocal()
        try:
            report = learn_sync.sync_questions(db)
        finally:
            db.close()

        assert report["total"] > 0
        # 占位节点存在时**一条都不该丢**：词典没命中的落到「未归类」，仍算 matched
        assert report["matched"] == report["total"], "有题目没落到任何节点上"
        assert report["unclassified"] <= report["total"]
        assert report["unclassified_ratio"] == pytest.approx(
            report["unclassified"] / report["total"], abs=1e-4
        )
        # 未归类明细的计数之和必须等于 unclassified，否则教师照着清单归并也归不干净
        assert sum(item["count"] for item in report["unclassified_labels"]) == report["unclassified"]

        # 三种匹配层级各自落到了预期节点
        db = SessionLocal()
        try:
            by_stem = {
                row.stem: row
                for row in db.query(Question)
                .filter(Question.stem.like(f"{W19_STEM_PREFIX}%"))
                .all()
            }
            assert by_stem[f"{W19_STEM_PREFIX}习题0"].kp_id == graph[LABEL_EXACT]
            assert by_stem[f"{W19_STEM_PREFIX}习题1"].kp_id == graph["反向传播"]
            placeholder = db.query(KnowledgePoint).filter(
                KnowledgePoint.is_placeholder == 1
            ).one()
            assert by_stem[f"{W19_STEM_PREFIX}习题2"].kp_id == placeholder.id
            assert by_stem[f"{W19_STEM_PREFIX}试题0"].kp_id == graph["链式法则"]
            # 难度归一化：源表的"基础"在 questions 里必须是三档之一（有 CHECK 约束）
            assert by_stem[f"{W19_STEM_PREFIX}习题0"].difficulty in ("简单", "中等", "困难")
        finally:
            db.close()

        # 未归类明细要给到 `raw_label`，教师才知道该补哪条别名
        labels = {item["raw_label"] for item in report["unclassified_labels"]}
        assert LABEL_UNKNOWN in labels

    def test_rerun_is_idempotent(self, client, teacher_token, auth, graph, source_rows):
        """`/kp/sync` 是演示前置步骤，会被反复执行——重跑一次题量不能翻倍。"""
        from app.services import learn_sync

        db = SessionLocal()
        try:
            before = db.query(Question).count()
            report = learn_sync.sync_questions(db)
            after = db.query(Question).count()
        finally:
            db.close()

        assert report["imported"] == 0, "第二次汇入不应有新插入"
        assert report["updated"] > 0
        assert after == before, f"重跑后题量从 {before} 变成了 {after}"

    def test_alias_written_once_and_hit_count_recomputed(
        self, client, teacher_token, auth, graph, source_rows
    ):
        """别名表的 `hit_count` 必须**全量重算**而非累加，否则跑三次就虚增三倍。"""
        from app.services import learn_sync

        db = SessionLocal()
        try:
            learn_sync.sync_questions(db)
            first = {
                row.norm_label: row.hit_count
                for row in db.query(KpAlias).all()
            }
            learn_sync.sync_questions(db)
            second = {
                row.norm_label: row.hit_count
                for row in db.query(KpAlias).all()
            }
            # 与节点名全等的标签不写别名行（词典里已经有了）
            assert normalize_label(LABEL_EXACT) not in second
            assert normalize_label(LABEL_UNKNOWN) in second
        finally:
            db.close()

        assert first == second, "重跑后 hit_count 变了，说明是累加而非重算"

    def test_source_table_gets_kp_id_back(
        self, client, teacher_token, auth, graph, source_rows
    ):
        """源表也回写 `kp_id`：教师要在工单17 的页面上看到这道题挂在哪个知识点。"""
        from app.services import learn_sync

        db = SessionLocal()
        try:
            learn_sync.sync_questions(db)
            row = db.get(Exercise, source_rows["exercise"][0])
            assert row.kp_id == graph[LABEL_EXACT]
        finally:
            db.close()

    def test_sync_requires_teacher(self, client, learner_auth):
        """汇入会重写全库题库与别名表，是管理动作，学生不得触发（设计文档 5a）。"""
        _student_id, headers = learner_auth
        resp = client.post("/api/learn/kp/sync?target=questions", headers=headers)
        assert resp.status_code == 403, resp.text


class TestMergeAlias:
    def test_merge_moves_alias_and_questions(self, client, teacher_token, auth, graph, source_rows):
        """归并只改 `kp_alias` 是不够的：题还挂在「未归类」上，下次抽题依然抽不到。"""
        from app.services import learn_sync

        db = SessionLocal()
        try:
            learn_sync.sync_questions(db)
            before = learn_sync.list_unclassified(db)
            assert any(
                item["raw_label"] == LABEL_UNKNOWN for item in before["items"]
            ), "前置条件：该标签此刻应挂在「未归类」上"

            report = learn_sync.merge_alias(
                db, raw_label=LABEL_UNKNOWN, target_kp_id=graph["梯度下降"]
            )
            assert report["moved_questions"] >= 1
            assert report["target_kp_name"] == "梯度下降"

            row = db.get(Exercise, source_rows["exercise"][2])
            assert row.kp_id == graph["梯度下降"]
            question = select_question(db, "exercise", source_rows["exercise"][2])
            assert question.kp_id == graph["梯度下降"]

            after = learn_sync.list_unclassified(db)
            assert not any(item["raw_label"] == LABEL_UNKNOWN for item in after["items"])
        finally:
            db.close()

    def test_manual_alias_survives_resync(
        self, client, teacher_token, auth, graph, source_rows
    ):
        """人工改判必须扛得住下一次自动同步——否则老师刚归并完就被打回占位节点。"""
        from app.services import learn_sync

        db = SessionLocal()
        try:
            learn_sync.merge_alias(
                db, raw_label=LABEL_UNKNOWN, target_kp_id=graph["梯度下降"]
            )
            learn_sync.sync_questions(db)
            alias = select_alias(db, normalize_label(LABEL_UNKNOWN))
            assert alias.kp_id == graph["梯度下降"]
            assert alias.source == "manual"
        finally:
            db.close()

    def test_merge_rejects_placeholder_target(self, client, teacher_token, auth, graph):
        from app.services import learn_sync

        db = SessionLocal()
        try:
            placeholder = db.query(KnowledgePoint).filter(
                KnowledgePoint.is_placeholder == 1
            ).one()
            with pytest.raises(ValueError):
                learn_sync.merge_alias(
                    db, raw_label="随便一个标签", target_kp_id=placeholder.id
                )
        finally:
            db.close()

    def test_merge_rejects_unknown_target(self, client, teacher_token, auth, graph):
        from app.services import learn_sync

        db = SessionLocal()
        try:
            with pytest.raises(ValueError):
                learn_sync.merge_alias(db, raw_label="标签", target_kp_id=_MISSING_ID)
        finally:
            db.close()

    def test_merge_via_api(self, client, teacher_token, auth, graph, source_rows):
        resp = client.post(
            "/api/learn/kp/merge",
            headers=auth(teacher_token),
            json={"raw_label": LABEL_UNKNOWN, "target_kp_id": graph["神经网络"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["target_kp_id"] == graph["神经网络"]

        bad = client.post(
            "/api/learn/kp/merge",
            headers=auth(teacher_token),
            json={"raw_label": LABEL_UNKNOWN, "target_kp_id": _MISSING_ID},
        )
        assert bad.status_code == 400, bad.text


def select_question(db, source: str, source_id: int) -> Question:
    return db.scalar(
        select(Question).where(Question.source == source, Question.source_id == source_id)
    )


def select_alias(db, norm_label: str) -> KpAlias:
    return db.scalar(select(KpAlias).where(KpAlias.norm_label == norm_label))


# ------------------------------------------------------------ 接口层

# 假的 LLM 错题分析结果。字段名刻意混用中英文键——`mistake.py` 两种都收，
# 这条用例同时就是在验证那个兼容分支不会在真实返回上崩掉
FAKE_MISTAKE_ANALYSIS = {
    "analysis": "梯度下降沿负梯度方向迭代更新参数。",
    "错误原因诊断": "把学习率的方向与大小混为一谈。",
    "misconception_type": "概念混淆",
    "变式题": [
        {
            "stem": "变式题一：学习率过大最可能导致什么？",
            "选项": {"A": "震荡不收敛", "B": "收敛更快"},
            "答案": "A",
            "解析": "步长过大时会在最优点两侧来回跳。",
        },
        {"stem": "变式题二：请简述梯度的含义。", "答案": "函数上升最快的方向", "解析": "略"},
    ],
}


class TestLearnApi:
    def test_answer_forbidden_for_teacher(self, client, teacher_token, auth, graph):
        """作答类写接口是学生专属：教师账号点进练习页也不该能交卷。"""
        resp = client.post(
            "/api/learn/answer",
            headers=auth(teacher_token),
            json={"question_id": 1, "user_answer": "A"},
        )
        assert resp.status_code == 403, resp.text

    def test_exam_submit_forbidden_for_teacher(self, client, teacher_token, auth):
        resp = client.post(
            "/api/learn/exam/submit",
            headers=auth(teacher_token),
            json={"plan_id": 1, "answers": []},
        )
        assert resp.status_code == 403, resp.text

    def test_kp_sync_forbidden_for_student(self, client, learner_auth):
        _student_id, headers = learner_auth
        resp = client.post("/api/learn/kp/sync?target=all", headers=headers)
        assert resp.status_code == 403, resp.text

    def test_practice_requires_target_when_no_evidence(self, client, learner_auth, graph):
        """新学生第一次进练习页：没有薄弱点可推荐，但**不能报错**——
        要返回可执行的下一步提示，而不是一片空白。"""
        _student_id, headers = learner_auth
        resp = client.get("/api/learn/practice", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["questions"] == []
        assert data["reason"] in (REASON_NO_TARGET, REASON_BANK_EMPTY)
        assert data["message"]

    def test_practice_reports_empty_bank(self, client, learner_auth, graph, monkeypatch):
        """题库为空时必须明说"先去同步题库"，否则前端只能显示一个空列表。"""
        from app.api import learn as learn_api

        _student_id, headers = learner_auth
        monkeypatch.setattr(learn_api, "_bank_is_empty", lambda _db: True)
        resp = client.get("/api/learn/practice", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["reason"] == REASON_BANK_EMPTY
        assert "kp/sync" in data["message"]

    def test_practice_hides_answers(self, client, learner_auth, graph):
        """取题接口**不能**带答案，否则打开开发者工具就能看到正确项。"""
        _student_id, headers = learner_auth
        resp = client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=2", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["questions"]) == 2
        assert data["kp_name"] == "梯度下降"
        assert data["promote_streak"] == 3
        for question in data["questions"]:
            assert "answer" not in question
            assert "analysis" not in question

    def test_answer_flow_wrong_then_right(self, client, learner_auth, graph):
        """主路径：答错 → 进错题本 → 再答对 → 更新画像。"""
        student_id, headers = learner_auth

        practice = client.get(
            f"/api/learn/practice?kp_id={graph['链式法则']}&count=1", headers=headers
        ).json()["data"]
        question_id = practice["questions"][0]["question_id"]

        wrong = client.post(
            "/api/learn/answer",
            headers=headers,
            json={"question_id": question_id, "user_answer": "B"},
        )
        assert wrong.status_code == 200, wrong.text
        payload = wrong.json()["data"]
        assert payload["is_correct"] is False
        assert payload["correct_answer"], "判错时必须回传正确答案，否则学生无从订正"
        assert payload["mistake_id"] is not None
        assert payload["mastery"] == pytest.approx(0.0)

        right = client.post(
            "/api/learn/answer",
            headers=headers,
            json={"question_id": question_id, "user_answer": payload["correct_answer"]},
        )
        assert right.status_code == 200, right.text
        assert right.json()["data"]["is_correct"] is True
        assert right.json()["data"]["mistake_id"] is None
        assert right.json()["data"]["mastery"] == pytest.approx(0.5)

        # 画像接口与作答结果一致
        profile = client.get("/api/learn/profile", headers=headers).json()["data"]
        row = next(
            item for item in profile["items"] if item["kp_id"] == graph["链式法则"]
        )
        assert row["mastery"] == pytest.approx(0.5)
        assert row["attempt_count"] == 2

    def test_three_correct_promotes_difficulty(self, client, learner_auth, graph):
        """连对 3 题升档（答对靠把正确答案直接提给接口，绕开题目本身）。"""
        _student_id, headers = learner_auth

        practice = client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=5", headers=headers
        ).json()["data"]
        assert practice["difficulty"] == "简单"

        db = SessionLocal()
        try:
            answers = {
                row.id: row.answer
                for row in db.query(Question)
                .filter(Question.id.in_([q["question_id"] for q in practice["questions"]]))
                .all()
            }
        finally:
            db.close()

        for question in practice["questions"][:3]:
            resp = client.post(
                "/api/learn/answer",
                headers=headers,
                json={
                    "question_id": question["question_id"],
                    "user_answer": answers[question["question_id"]],
                },
            )
            assert resp.json()["data"]["is_correct"] is True, resp.text

        assert resp.json()["data"]["difficulty"] == "中等"

        again = client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=1", headers=headers
        ).json()["data"]
        assert again["difficulty"] == "中等"

    def test_mistake_detail_and_analysis(self, client, learner_auth, graph, monkeypatch):
        """答错 → 触发分析 → 详情页拿到解析与变式题 → 变式题可再答。"""
        from app.services import llm_client

        calls = {"n": 0}

        async def fake_chat_json(_messages, **_kwargs):
            calls["n"] += 1
            return FAKE_MISTAKE_ANALYSIS

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)

        _student_id, headers = learner_auth
        practice = client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=1", headers=headers
        ).json()["data"]
        wrong = client.post(
            "/api/learn/answer",
            headers=headers,
            json={"question_id": practice["questions"][0]["question_id"], "user_answer": "B"},
        ).json()["data"]
        mistake_id = wrong["mistake_id"]

        listed = client.get("/api/learn/mistakes", headers=headers).json()["data"]
        assert listed["total"] == 1
        assert listed["items"][0]["analysis_status"] == "pending"

        analyzed = client.post(
            f"/api/learn/mistakes/{mistake_id}/analyze", headers=headers
        )
        assert analyzed.status_code == 200, analyzed.text
        assert calls["n"] == 1

        detail = client.get(
            f"/api/learn/mistakes/{mistake_id}", headers=headers
        ).json()["data"]
        assert detail["analysis_status"] == "done"
        assert detail["analysis"]["analysis"]
        assert detail["analysis"]["misconception"]
        assert len(detail["variant_questions"]) == 2
        # 变式题必须带 question_id，否则前端无法提交作答
        variant = detail["variant_questions"][0]
        assert variant["question_id"]

        # 答对变式题：不重新分析
        variant_right = client.post(
            f"/api/learn/mistakes/{mistake_id}/variant-answer",
            headers=headers,
            json={"question_id": variant["question_id"], "user_answer": "A"},
        )
        assert variant_right.status_code == 200, variant_right.text
        assert variant_right.json()["data"]["is_correct"] is True
        assert variant_right.json()["data"]["reanalyzed"] is False

        # 答错变式题：重新分析，`variant_tries` 累加
        variant_wrong = client.post(
            f"/api/learn/mistakes/{mistake_id}/variant-answer",
            headers=headers,
            json={"question_id": variant["question_id"], "user_answer": "B"},
        )
        assert variant_wrong.status_code == 200, variant_wrong.text
        body = variant_wrong.json()["data"]
        assert body["is_correct"] is False
        assert body["reanalyzed"] is True
        assert body["variant_tries"] == 1
        assert calls["n"] == 2
        # 变式题不动难度档（有独立的 variant_tries 循环）
        assert client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=1", headers=headers
        ).json()["data"]["difficulty"] == "简单"

    def test_mistake_analysis_failure_is_visible(self, client, learner_auth, graph, monkeypatch):
        """LLM 调不通时要给出可读原因并把状态置 failed——
        演示时最怕的是"点了没反应"，而不是"报了错"。"""
        from app.services import llm_client

        async def boom(_messages, **_kwargs):
            raise RuntimeError("模拟：LLM 连接失败")

        monkeypatch.setattr(llm_client, "chat_json", boom)

        _student_id, headers = learner_auth
        practice = client.get(
            f"/api/learn/practice?kp_id={graph['微积分基础']}&count=1", headers=headers
        ).json()["data"]
        wrong = client.post(
            "/api/learn/answer",
            headers=headers,
            json={"question_id": practice["questions"][0]["question_id"], "user_answer": "B"},
        ).json()["data"]

        resp = client.post(
            f"/api/learn/mistakes/{wrong['mistake_id']}/analyze", headers=headers
        )
        assert resp.status_code == 502, resp.text
        assert "模拟：LLM 连接失败" in resp.json()["msg"]

        detail = client.get(
            f"/api/learn/mistakes/{wrong['mistake_id']}", headers=headers
        ).json()["data"]
        assert detail["analysis_status"] == "failed"

    def test_mistake_of_others_is_404(self, client, learner_auth, graph):
        """越权与不存在统一 404，不泄露他人数据是否存在。"""
        _student_id, headers = learner_auth
        practice = client.get(
            f"/api/learn/practice?kp_id={graph['神经网络']}&count=1", headers=headers
        ).json()["data"]
        wrong = client.post(
            "/api/learn/answer",
            headers=headers,
            json={"question_id": practice["questions"][0]["question_id"], "user_answer": "B"},
        ).json()["data"]
        assert wrong["mistake_id"] is not None

        _other_id, other_headers = _new_student(client)
        resp = client.get(
            f"/api/learn/mistakes/{wrong['mistake_id']}", headers=other_headers
        )
        assert resp.status_code == 404, resp.text
        # 另一个学生的错题本必须是空的
        assert client.get("/api/learn/mistakes", headers=other_headers).json()["data"]["total"] == 0

    def test_related_lazily_attaches_recent_question(self, client, learner_auth, graph):
        """刚在助教里问过 → 当场打开侧栏就该看到它，不必等教师跑批处理。"""
        student_id, headers = learner_auth

        db = SessionLocal()
        try:
            conversation = Conversation(user_id=student_id, title="工单19侧栏用例")
            db.add(conversation)
            db.flush()
            db.add(
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="梯度下降的学习率该怎么选？",
                )
            )
            db.commit()
        finally:
            db.close()

        resp = client.get(
            f"/api/learn/related?kp_id={graph['梯度下降']}", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["kp_name"] == "梯度下降"
        assert any(
            "学习率" in item["question"] and item["source"] == "own"
            for item in data["questions"]
        ), data["questions"]
        assert len(data["exercises"]) >= 1
        assert "hotq_enabled" in data

    def test_related_rejects_placeholder(self, client, learner_auth, graph):
        db = SessionLocal()
        try:
            placeholder_id = db.query(KnowledgePoint).filter(
                KnowledgePoint.is_placeholder == 1
            ).one().id
        finally:
            db.close()
        _student_id, headers = learner_auth
        resp = client.get(f"/api/learn/related?kp_id={placeholder_id}", headers=headers)
        assert resp.status_code == 404, resp.text


# ------------------------------------------------------------ 试卷模式（抉择2 → A）

EXAM_SPEC = (
    ("梯度下降", 10, "A"),
    ("反向传播", 20, "A"),
    ("神经网络", 30, "A"),
)
EXAM_OPTIONS = '["A. 正确项", "B. 干扰项"]'


@pytest.fixture(scope="module")
def exam_plan(client, owner_id, graph) -> int:
    """一套试卷 + 汇入题库。**分值只在 `exam_questions.score` 上**，
    故 `/exam` 必须回连源表取分，不能在 `questions` 里找（见 3.3.2）。"""
    from app.services import learn_sync

    db = SessionLocal()
    try:
        plan = db.query(TeachingPlan).filter(TeachingPlan.title == "工单19试卷用例").first()
        if plan is None:
            plan = TeachingPlan(
                owner_id=owner_id,
                content_type="试题",
                course_name=COURSE,
                title="工单19试卷用例",
                content_json="{}",
            )
            db.add(plan)
            db.flush()
            for index, (kp_name, score, answer) in enumerate(EXAM_SPEC):
                db.add(
                    ExamQuestion(
                        plan_id=plan.id,
                        qtype="单选",
                        stem=f"【工单19试卷】第{index + 1}题（{kp_name}）",
                        options_json=EXAM_OPTIONS,
                        answer=answer,
                        analysis=f"{kp_name} 的解析",
                        knowledge_point=kp_name,
                        score=score,
                        difficulty="中等",
                    )
                )
            db.commit()
        plan_id = plan.id
        # 试卷必须先进统一题库，`/exam` 才拿得到题
        learn_sync.sync_questions(db)
        return plan_id
    finally:
        db.close()


class TestExamMode:
    def test_paper_has_scores_and_total(self, client, learner_auth, exam_plan):
        _student_id, headers = learner_auth
        resp = client.get(f"/api/learn/exam?plan_id={exam_plan}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert data["plan_id"] == exam_plan
        assert data["question_count"] == len(EXAM_SPEC)
        assert data["total_score"] == sum(score for _kp, score, _a in EXAM_SPEC)
        assert [item["score"] for item in data["questions"]] == [
            score for _kp, score, _a in EXAM_SPEC
        ]
        for question in data["questions"]:
            assert "answer" not in question, "组卷接口不能带答案"

    def test_submit_scores_and_counts_blanks_as_wrong(self, client, learner_auth, exam_plan):
        """未作答按错处理：跳过就是没拿到分，画像理应反映这一点。"""
        _student_id, headers = learner_auth
        paper = client.get(
            f"/api/learn/exam?plan_id={exam_plan}", headers=headers
        ).json()["data"]
        questions = paper["questions"]

        # 第 1 题答对、第 2 题答错、第 3 题留空
        resp = client.post(
            "/api/learn/exam/submit",
            headers=headers,
            json={
                "plan_id": exam_plan,
                "answers": [
                    {"question_id": questions[0]["question_id"], "user_answer": "A"},
                    {"question_id": questions[1]["question_id"], "user_answer": "B"},
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert data["question_count"] == len(EXAM_SPEC)
        assert data["correct_count"] == 1
        assert data["score"] == EXAM_SPEC[0][1] == 10
        assert data["total_score"] == sum(score for _kp, score, _a in EXAM_SPEC)
        assert [item["is_correct"] for item in data["items"]] == [True, False, False]
        assert data["items"][2]["user_answer"] is None
        assert data["items"][2]["earned"] == 0

        # 逐题都写了 attempts（含未作答那条）
        db = SessionLocal()
        try:
            attempts = (
                db.query(Attempt)
                .filter(Attempt.student_id == _student_id, Attempt.is_exam.is_(True))
                .all()
            )
            assert len(attempts) == len(EXAM_SPEC)
            assert all(attempt.is_variant is False for attempt in attempts)
        finally:
            db.close()

    def test_exam_does_not_touch_practice_state(self, client, learner_auth, exam_plan, graph):
        """考试是"测量"、练习是"训练"：考砸了不该把自适应档位打下去。"""
        _student_id, headers = learner_auth
        paper = client.get(
            f"/api/learn/exam?plan_id={exam_plan}", headers=headers
        ).json()["data"]

        before = client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=1", headers=headers
        ).json()["data"]["difficulty"]
        assert before == "简单"

        client.post(
            "/api/learn/exam/submit",
            headers=headers,
            json={
                "plan_id": exam_plan,
                "answers": [
                    {"question_id": paper["questions"][0]["question_id"], "user_answer": "B"}
                ],
            },
        )

        after = client.get(
            f"/api/learn/practice?kp_id={graph['梯度下降']}&count=1", headers=headers
        ).json()["data"]["difficulty"]
        assert after == "简单", "试卷作答改了练习难度档"

        # 但画像必须计入：考试答错同样算一次不利证据
        profile = client.get("/api/learn/profile", headers=headers).json()["data"]
        row = next(
            item for item in profile["items"] if item["kp_id"] == graph["梯度下降"]
        )
        assert row["attempt_count"] >= 1
        assert row["mastery"] == pytest.approx(0.0)

    def test_submit_rejects_foreign_question(self, client, learner_auth, exam_plan, graph):
        """混进不属于本试卷的题号必须报错，不能静默忽略——
        静默忽略会让"我明明答了这道题"变成一笔糊涂账。"""
        _student_id, headers = learner_auth
        db = SessionLocal()
        try:
            foreign_id = db.scalar(
                select(Question).where(Question.kp_id == graph["链式法则"]).limit(1)
            ).id
        finally:
            db.close()

        resp = client.post(
            "/api/learn/exam/submit",
            headers=headers,
            json={
                "plan_id": exam_plan,
                "answers": [{"question_id": foreign_id, "user_answer": "A"}],
            },
        )
        assert resp.status_code == 400, resp.text
        assert "不属于本试卷" in resp.json()["msg"]

    def test_unknown_plan_is_404(self, client, learner_auth, exam_plan):
        _student_id, headers = learner_auth
        resp = client.get("/api/learn/exam?plan_id=99999999", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["questions"] == []
        assert resp.json()["data"]["reason"] == REASON_BANK_EMPTY

        submit = client.post(
            "/api/learn/exam/submit",
            headers=headers,
            json={"plan_id": 99999999, "answers": []},
        )
        assert submit.status_code == 404, submit.text
