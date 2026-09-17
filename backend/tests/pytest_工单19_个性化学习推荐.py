# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 测试用例
"""工单19 个性化学习推荐 pytest 用例。

当前覆盖：**前置修复 P0 —— SQLite 外键约束**（见设计文档 3.3.3）。
随工单19 功能落地，本文件继续追加知识点匹配漏斗、画像与时间衰减、
路径上溯、自适应难度、试卷模式、AIGC 错题本、related 惰性补挂等用例。

LLM 全部 mock，测试不依赖真实 API Key 与网络。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, foreign_keys_enabled
from app.models.assistant import Conversation, KbChunk, KbDoc, Message
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
        result = match_label("BP", index=_index(), on_unmatched=ON_UNMATCHED_DROP)
        assert result is not None
        assert (result.kp_id, result.method) == (2, METHOD_ALIAS)

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
