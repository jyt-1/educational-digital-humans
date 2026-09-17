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
