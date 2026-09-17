# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 题库汇入与知识点归并
"""`/api/learn/kp/sync` 的三种目标、未归类清单与归并（设计文档 3.2.2 接口表、3.2.5）。

**为什么汇入必须先于一切**：`questions` 是统一题库，工单17 的 `exercises` /
`exam_questions` 不直接参与抽题；不汇入，`GET /learn/practice` 就是空题库。
汇入与挂靠是**同一趟**做完的——分两趟会出现"题目进了库但 `kp_id` 为空"的中间态，
此时抽题按 `kp_id` 过滤，题全被过滤掉，症状与"没汇入"一模一样。

**幂等靠 `UNIQUE(source, source_id)` 部分索引**（不是 `create_all`）：UPSERT 而非插入，
重跑一次题量不翻倍。这是本接口敢写成"可重跑"的全部依据。

**别名单的写入方就是三个调用方自己**（`kp_match` 是无状态的，见其模块注释）：
题库汇入落 `exercise`/`exam`、成绩导入落 `score_import`、消息挂靠落 `message`、
人工归并落 `manual`。若此处不写，`kp_alias` 永远是空的，"自学习"就是空话。
"""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assistant import Conversation, Message
from app.models.learn import (
    SOURCE_EXAM,
    SOURCE_EXERCISE,
    SOURCE_MANUAL,
    SOURCE_MESSAGE,
    KnowledgePoint,
    KpAlias,
    KpFaq,
    MessageKp,
    Question,
)
from app.models.lesson import ExamQuestion, Exercise
from app.services.kp_match import (
    METHOD_EXACT,
    METHOD_PLACEHOLDER,
    ON_UNMATCHED_DROP,
    ON_UNMATCHED_PLACEHOLDER,
    load_index,
    match_label,
    match_text,
    normalize_difficulty,
    normalize_label,
)

logger = logging.getLogger(__name__)

# 汇入来源 → 工单17 的模型。顺序即导入顺序，报告里按此顺序累计
SOURCE_MODELS = ((Exercise, SOURCE_EXERCISE), (ExamQuestion, SOURCE_EXAM))

# 跨用户聚合的「常用」判据：同一人问 N 次不算常用（设计文档 2.2 场景三第 7 条）
HOTQ_MIN_USERS = 2


# ------------------------------------------------------------------ ① 题库汇入

def sync_questions(db: Session) -> dict:
    """`target=questions`：工单17 的题目 → 统一题库，并挂 `kp_id`。

    返回报告含**未归类占比与 `raw_label` 明细（按出现次数降序）**——
    只给占比不可执行：教师看到"12% 未归类"仍不知道该补哪条别名，
    看到"「误差项的反向传递」出现 2 次"才能一次性归并掉。
    """
    index = load_index(db)
    imported = updated = matched = unclassified = 0
    unmatched_labels: Counter[str] = Counter()
    # norm_label -> 该写入 kp_alias 的内容。同一标签在一个批次里只留一份
    alias_plan: dict[str, dict] = {}

    for model, source in SOURCE_MODELS:
        for row in db.execute(select(model)).scalars():
            result = match_label(
                row.knowledge_point, index=index, on_unmatched=ON_UNMATCHED_PLACEHOLDER
            )
            kp_id = result.kp_id if result is not None else None
            label = (row.knowledge_point or "").strip()

            if result is not None and result.matched:
                matched += 1
                if result.method == METHOD_PLACEHOLDER:
                    unclassified += 1
                    unmatched_labels[label or "(空)"] += 1
                norm = normalize_label(label)
                # 归一化后与节点名全等的标签不必再存一行别名：词典里已经有了
                if norm and result.method != METHOD_EXACT:
                    alias_plan.setdefault(
                        norm,
                        {
                            "raw_label": label,
                            "kp_id": result.kp_id,
                            "confidence": result.confidence,
                            "source": source,
                        },
                    )

            payload = {
                "kp_id": kp_id,
                "qtype": row.qtype,
                "stem": row.stem,
                "options_json": row.options_json,
                "answer": row.answer,
                "analysis": row.analysis,
                # 难度归一化到三档：工单17 的历史列可以是"较难""基础"等自由文本，
                # 而 questions 有 CHECK 约束，不归一化会整行写不进去（见 3.2.6）
                "difficulty": normalize_difficulty(row.difficulty),
            }

            existing = db.scalar(
                select(Question).where(
                    Question.source == source, Question.source_id == row.id
                )
            )
            if existing is None:
                db.add(Question(source=source, source_id=row.id, **payload))
                imported += 1
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                updated += 1

            # 源表也写上 kp_id，让「这道题挂在哪个知识点」在工单17 的页面上同样可见
            row.kp_id = kp_id

    db.flush()

    # hit_count 全量重算（不是累加）：本接口可重跑，累加会让次数随重跑次数虚增
    label_usage = _label_usage(db)
    alias_written = 0
    for norm, plan in alias_plan.items():
        hits = label_usage.get(norm, 0)
        alias = db.scalar(select(KpAlias).where(KpAlias.norm_label == norm))
        if alias is None:
            db.add(
                KpAlias(
                    raw_label=plan["raw_label"],
                    norm_label=norm,
                    kp_id=plan["kp_id"],
                    confidence=plan["confidence"],
                    hit_count=hits,
                    source=plan["source"],
                )
            )
        else:
            alias.raw_label = plan["raw_label"]
            alias.kp_id = plan["kp_id"]
            alias.confidence = plan["confidence"]
            alias.hit_count = hits
            # 人工改判过的行不被自动同步覆盖回去——否则老师刚归并完就被打回占位节点
            if alias.source != SOURCE_MANUAL:
                alias.source = plan["source"]
        alias_written += 1

    # 已存在的别名行也要重算次数（它们不在本批 alias_plan 里，但题目标签可能变了）
    for alias in db.execute(select(KpAlias)).scalars():
        alias.hit_count = label_usage.get(alias.norm_label, 0)

    db.commit()

    total = imported + updated
    return {
        "target": "questions",
        "imported": imported,
        "updated": updated,
        "total": total,
        "matched": matched,
        "unclassified": unclassified,
        "unclassified_ratio": round(unclassified / total, 4) if total else 0.0,
        "unclassified_labels": [
            {"raw_label": label, "count": count} for label, count in unmatched_labels.most_common()
        ],
        "alias_written": alias_written,
    }


def _label_usage(db: Session) -> Counter[str]:
    """每个归一化标签在源表里出现的次数。`hit_count` 的重算依据。"""
    usage: Counter[str] = Counter()
    for model, _source in SOURCE_MODELS:
        for (label,) in db.execute(select(model.knowledge_point)).all():
            norm = normalize_label(label)
            if norm:
                usage[norm] += 1
    return usage


# ------------------------------------------------------------------ ② 消息挂靠

def sync_messages(db: Session, *, student_id: int | None = None, limit: int | None = None) -> dict:
    """`target=messages`：给学生提问挂知识点，落 `message_kp`。

    `student_id` 有值时只扫该生的消息——`/learn/related` 的**惰性补挂**走这条路：
    只补"该生尚无 `message_kp` 的消息"，量极小，避免"刚提问 → 当场看侧栏为空"
    必须等教师先跑一次批处理。
    """
    index = load_index(db)
    query = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.role == "user")
        .order_by(Message.id)
    )
    if student_id is not None:
        query = query.where(Conversation.user_id == student_id)
    messages = list(db.execute(query).scalars())
    if limit:
        messages = messages[:limit]

    scanned = attached = 0
    for message in messages:
        exists = db.scalar(
            select(func.count()).select_from(MessageKp).where(MessageKp.message_id == message.id)
        )
        if exists:
            continue
        scanned += 1
        hits = match_text(message.content, index=index, on_unmatched=ON_UNMATCHED_DROP)
        for hit in hits:
            db.add(
                MessageKp(
                    message_id=message.id,
                    kp_id=hit.kp_id,
                    confidence=hit.confidence,
                    source=hit.method,
                )
            )
            attached += 1
        # 只有"唯一命中"才写别名：一条提问抠出多个知识点时，哪个才是该文本的别名
        # 本身就没有定义，写进去只会污染别名表
        if len(hits) == 1:
            _write_alias(db, hits[0].raw_text, hits[0].kp_id, hits[0].confidence, SOURCE_MESSAGE)

    db.commit()
    return {"target": "messages", "scanned": scanned, "attached": attached}


def _write_alias(db: Session, raw_label: str, kp_id: int | None, confidence: float, source: str) -> None:
    """UPSERT 一行别名。人工改判过的行不覆盖——否则老师刚归并完就被自动同步打回去。"""
    norm = normalize_label(raw_label)
    if not norm or kp_id is None:
        return
    alias = db.scalar(select(KpAlias).where(KpAlias.norm_label == norm))
    if alias is None:
        db.add(
            KpAlias(
                raw_label=raw_label.strip(),
                norm_label=norm,
                kp_id=kp_id,
                confidence=confidence,
                hit_count=0,
                source=source,
            )
        )
    elif alias.source != SOURCE_MANUAL:
        alias.kp_id = kp_id
        alias.confidence = confidence
        alias.source = source


# ------------------------------------------------------------------ ③ 常用问题

def sync_faq(db: Session) -> dict:
    """`target=faq`：跨用户聚合的常用问题写入 `kp_faq`（`source='user'`）。

    **`ask_count` 是覆盖而非累加**——本接口可重跑，累加会让次数随重跑次数虚增。

    试点期只有 demo 学生一个账号，按 `COUNT(DISTINCT user_id) >= 2` 统计的"全站高频"
    必然为空。这不影响验收：冷启动靠 `seed_learn.py` 灌的 `kp_faq` 种子行，
    本接口是锦上添花（设计文档 2.2 场景三第 7 条已写明）。
    """
    rows = db.execute(
        select(
            MessageKp.kp_id,
            Message.content,
            func.count(func.distinct(Conversation.user_id)).label("users"),
            func.count().label("asks"),
        )
        .join(Message, Message.id == MessageKp.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.role == "user")
        .group_by(MessageKp.kp_id, Message.content)
        .having(func.count(func.distinct(Conversation.user_id)) >= HOTQ_MIN_USERS)
    ).all()

    written = 0
    for kp_id, question, _users, asks in rows:
        faq = db.scalar(
            select(KpFaq).where(KpFaq.kp_id == kp_id, KpFaq.question == question)
        )
        if faq is None:
            db.add(KpFaq(kp_id=kp_id, question=question, ask_count=asks, source="user"))
        else:
            faq.ask_count = asks
            faq.source = "user"
        written += 1

    db.commit()
    return {"target": "faq", "written": written}


# ------------------------------------------------------------------ 未归类与归并

def list_unclassified(db: Session) -> dict:
    """未归类清单：挂到占位节点上的别名行，按 `source` 分组、`hit_count` 降序。

    次数取 `kp_alias.hit_count`——该值由 `/kp/sync` 全量**重算赋值**，
    因此与回扫源表统计的结果一致，不存在"只从建表之后才开始累计"的偏差。
    """
    rows = db.execute(
        select(KpAlias, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == KpAlias.kp_id)
        .where(KnowledgePoint.is_placeholder == 1)
        .order_by(KpAlias.source, KpAlias.hit_count.desc())
    ).all()

    groups: dict[str, list[dict]] = {}
    for alias, _kp_name in rows:
        groups.setdefault(alias.source or "unknown", []).append(
            {
                "alias_id": alias.id,
                "raw_label": alias.raw_label,
                "norm_label": alias.norm_label,
                "hit_count": alias.hit_count,
                "source": alias.source,
            }
        )
    return {
        "total": len(rows),
        "groups": [{"source": key, "items": items} for key, items in groups.items()],
        "items": [item for items in groups.values() for item in items],
    }


def list_aliases(db: Session, *, only_placeholder: bool = False) -> list[dict]:
    """全部别名（教师端「全部别名」页签）。误挂的纠正入口在这里，不在未归类清单里——
    词典最长子串必然会把"随机梯度下降"挂到"梯度下降"，这类错误**不在未归类清单中**，
    必须能从一份全量列表里改判。
    """
    query = (
        select(KpAlias, KnowledgePoint.name, KnowledgePoint.is_placeholder)
        .join(KnowledgePoint, KnowledgePoint.id == KpAlias.kp_id)
        .order_by(KpAlias.hit_count.desc(), KpAlias.id)
    )
    if only_placeholder:
        query = query.where(KnowledgePoint.is_placeholder == 1)

    return [
        {
            "alias_id": alias.id,
            "raw_label": alias.raw_label,
            "norm_label": alias.norm_label,
            "kp_id": alias.kp_id,
            "kp_name": kp_name,
            "is_placeholder": bool(is_placeholder),
            "hit_count": alias.hit_count,
            "confidence": alias.confidence,
            "source": alias.source,
        }
        for alias, kp_name, is_placeholder in db.execute(query).all()
    ]


def merge_alias(db: Session, *, raw_label: str, target_kp_id: int) -> dict:
    """把任意 `raw_label` 从当前挂靠节点改判到目标节点。

    改一行 `kp_alias` 之外，还要把**原先挂在该标签下的题目与消息**一并迁走，
    否则界面上"归并成功了"但题还是挂在「未归类」上，下次抽题依然抽不到。
    """
    target = db.get(KnowledgePoint, target_kp_id)
    if target is None:
        raise ValueError("目标知识点不存在")
    if target.is_placeholder:
        raise ValueError("不能把标签归并到「未归类」占位节点")

    label = (raw_label or "").strip()
    norm = normalize_label(label)
    if not norm:
        raise ValueError("标签不能为空")

    alias = db.scalar(select(KpAlias).where(KpAlias.norm_label == norm))
    if alias is None:
        alias = KpAlias(
            raw_label=label, norm_label=norm, kp_id=target_kp_id, hit_count=0, source=SOURCE_MANUAL
        )
        db.add(alias)
    else:
        alias.kp_id = target_kp_id
        alias.source = SOURCE_MANUAL
    db.flush()

    moved_questions = _migrate_questions(db, norm, target_kp_id)
    moved_messages = _migrate_messages(db, norm, target_kp_id)
    alias.hit_count = _label_usage(db).get(norm, 0)
    db.commit()

    return {
        "raw_label": label,
        "norm_label": norm,
        "target_kp_id": target_kp_id,
        "target_kp_name": target.name,
        "moved_questions": moved_questions,
        "moved_messages": moved_messages,
    }


def _migrate_questions(db: Session, norm: str, target_kp_id: int) -> int:
    """把标签为 `norm` 的题目改挂到目标知识点（源表 + 统一题库两处一起改）。"""
    moved = 0
    for model, source in SOURCE_MODELS:
        ids = [
            row.id
            for row in db.execute(select(model)).scalars()
            if normalize_label(row.knowledge_point) == norm
        ]
        if not ids:
            continue
        db.query(model).filter(model.id.in_(ids)).update({"kp_id": target_kp_id}, synchronize_session=False)
        db.query(Question).filter(
            Question.source == source, Question.source_id.in_(ids)
        ).update({"kp_id": target_kp_id}, synchronize_session=False)
        moved += len(ids)
    return moved


def _migrate_messages(db: Session, norm: str, target_kp_id: int) -> int:
    """把文本里含该标签的消息挂靠迁到目标知识点。

    只在 `message_kp` 现挂的节点与目标不同、且消息正文确实含该标签时才迁——
    否则会把同一条消息上其他知识点的挂靠一并误伤。
    """
    moved = 0
    for relation in db.execute(select(MessageKp)).scalars():
        if relation.kp_id == target_kp_id:
            continue
        message = db.get(Message, relation.message_id)
        if message is None or norm not in normalize_label(message.content):
            continue
        relation.kp_id = target_kp_id
        moved += 1
    return moved


__all__ = [
    "HOTQ_MIN_USERS",
    "SOURCE_MODELS",
    "list_aliases",
    "list_unclassified",
    "merge_alias",
    "sync_faq",
    "sync_messages",
    "sync_questions",
]
