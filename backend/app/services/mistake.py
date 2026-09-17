# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— AIGC 错题分析
"""错题分析：组装 Prompt（设计文档 3.2.7）→ 调 LLM → 落 `mistake_book`。

两处设计上必须讲清楚的地方：

1. **变式题要落成 `questions` 行，不能只躺在 JSON 里。** `attempts.question_id` 是
   外键且 NOT NULL，变式题作答若要记进 `attempts`（`is_variant=1` 这一列的存在正说明
   它该被记录），就必须先有题目行。`questions` 的部分唯一索引 `WHERE source_id IS NOT NULL`
   正是为这种"无来源行"留的口子——`source=NULL, source_id=NULL` 合法且不参与去重。
2. **重新分析时清理旧的、无人作答过的变式题行**，避免反复点「重新分析」把该知识点的
   题池灌满变式题；已被作答过的保留——那些行被 `attempts` 外键引用，删了就报约束错，
   而且它们本就是该知识点下的合法题目。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learn import (
    ANALYZE_ANALYZING,
    ANALYZE_DONE,
    ANALYZE_FAILED,
    DIFFICULTY_MEDIUM,
    Attempt,
    KnowledgePoint,
    MistakeBook,
    Question,
)
from app.services import llm_client, prompts
from app.services.learn_answer import load_options

logger = logging.getLogger(__name__)

# 先修链最多上溯几层。给 LLM 的上下文不是越长越好——链路太长会稀释归因的针对性
PREREQ_CHAIN_MAX = 5

VARIANT_COUNT = 3


# ------------------------------------------------------------------ 取数

def _prereq_chain(db: Session, kp: KnowledgePoint | None) -> list[str]:
    """沿 `prereq_id` 上溯的先修链（由远及近），供"从先修补起"的建议。"""
    chain: list[str] = []
    cursor = kp.prereq_id if kp else None
    seen: set[int] = set()
    while cursor is not None and len(chain) < PREREQ_CHAIN_MAX and cursor not in seen:
        seen.add(cursor)
        node = db.get(KnowledgePoint, cursor)
        if node is None:
            break
        chain.append(node.name)
        cursor = node.prereq_id
    return list(reversed(chain))


def _common_misconceptions(kp: KnowledgePoint | None) -> list[str]:
    """该知识点「预设的常见错误类型」。脏数据一律当空处理——它是可空列、不做校验，
    解析失败也不能让它成为新的失败点（设计文档 3.2.7）。"""
    if kp is None or not kp.common_misconceptions:
        return []
    try:
        parsed = json.loads(kp.common_misconceptions)
    except (json.JSONDecodeError, TypeError):
        logger.warning("知识点 %s 的 common_misconceptions 不是合法 JSON，按空处理", kp.id)
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _latest_wrong_attempt(db: Session, mistake: MistakeBook) -> Attempt | None:
    """该生在该题上**最近一次答错**的作答——Prompt 要的是学生的真实错答。"""
    return db.scalar(
        select(Attempt)
        .where(
            Attempt.student_id == mistake.student_id,
            Attempt.question_id == mistake.question_id,
            Attempt.is_correct.is_(False),
        )
        .order_by(Attempt.created_at.desc(), Attempt.id.desc())
    )


# ------------------------------------------------------------------ 变式题落库

def _materialize_variants(
    db: Session,
    *,
    kp_id: int | None,
    difficulty: str | None,
    items: list[dict],
) -> list[dict]:
    """把 LLM 给的变式题写成 `questions` 行，返回带 `question_id` 的变式题列表。"""
    variants: list[dict] = []
    for item in items:
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        options = item.get("options") or item.get("选项") or []
        if isinstance(options, dict):
            options = [f"{key}. {value}" for key, value in options.items()]
        if not isinstance(options, list):
            options = []
        options = [str(option).strip() for option in options if str(option).strip()]

        question = Question(
            kp_id=kp_id,
            qtype="单选" if options else "简答",
            stem=stem,
            options_json=json.dumps(options, ensure_ascii=False) if options else None,
            answer=str(item.get("answer") or item.get("答案") or "").strip() or None,
            analysis=str(item.get("analysis") or item.get("解析") or "").strip() or None,
            difficulty=difficulty if difficulty in ("简单", "中等", "困难") else DIFFICULTY_MEDIUM,
            # 无来源行：不属于工单17 的任何一次生成，只服务于这道错题的补救练习
            source=None,
            source_id=None,
        )
        db.add(question)
        db.flush()

        variants.append(
            {
                "question_id": question.id,
                "stem": stem,
                "options": options,
                "answer": question.answer,
                "analysis": question.analysis,
            }
        )
    return variants


def _drop_unused_variants(db: Session, previous_json: str | None) -> int:
    """删掉上一轮生成、且从未被作答过的变式题行（见模块注释第 2 点）。"""
    if not previous_json:
        return 0
    try:
        previous = json.loads(previous_json)
    except (json.JSONDecodeError, TypeError):
        return 0
    if not isinstance(previous, list):
        return 0

    dropped = 0
    for item in previous:
        question_id = item.get("question_id") if isinstance(item, dict) else None
        if not question_id:
            continue
        question = db.get(Question, question_id)
        if question is None or question.source_id is not None:
            continue
        answered = db.scalar(
            select(Attempt.id).where(Attempt.question_id == question_id).limit(1)
        )
        if answered:
            continue
        db.delete(question)
        dropped += 1
    return dropped


# ------------------------------------------------------------------ 主流程

async def analyze_mistake(db: Session, mistake: MistakeBook, *, variant_count: int = VARIANT_COUNT) -> dict:
    """跑一次错题分析，把结果写回 `mistake_book`。返回落库后的分析结构。

    LLM 调用失败时把状态置为 `failed` 并**原样抛出**——接口层据此返回可读的错误，
    而不是假装成功再让前端显示一个空解析（那种情况现场无法解释"为什么没有内容"）。
    """
    question = db.get(Question, mistake.question_id)
    if question is None:
        raise ValueError("错题对应的题目不存在")

    kp = db.get(KnowledgePoint, mistake.kp_id) if mistake.kp_id else None
    attempt = _latest_wrong_attempt(db, mistake)

    messages = prompts.build_mistake_messages(
        stem=question.stem,
        options=load_options(question.options_json),
        user_answer=attempt.user_answer if attempt else None,
        correct_answer=question.answer,
        kp_name=kp.name if kp else None,
        prereq_chain=_prereq_chain(db, kp),
        common_misconceptions=_common_misconceptions(kp),
        qtype=question.qtype,
    )

    mistake.analyze_status = ANALYZE_ANALYZING
    db.commit()

    try:
        parsed = await llm_client.chat_json(messages)
    except Exception:
        mistake.analyze_status = ANALYZE_FAILED
        db.commit()
        raise

    if not isinstance(parsed, dict):
        mistake.analyze_status = ANALYZE_FAILED
        db.commit()
        raise ValueError("LLM 返回的错题分析结构不是对象")

    raw_variants = parsed.get("variant_questions") or parsed.get("变式题") or []
    if isinstance(raw_variants, dict):
        raw_variants = [raw_variants]
    if not isinstance(raw_variants, list):
        raw_variants = []

    _drop_unused_variants(db, mistake.variant_questions)
    variants = _materialize_variants(
        db,
        kp_id=mistake.kp_id,
        difficulty=question.difficulty,
        items=[item for item in raw_variants[:variant_count] if isinstance(item, dict)],
    )

    analysis = {
        "analysis": str(parsed.get("analysis") or parsed.get("题目解析") or "").strip(),
        "misconception": str(parsed.get("misconception") or parsed.get("错误原因诊断") or "").strip(),
        "misconception_type": str(parsed.get("misconception_type") or "").strip(),
        "inferred_misconceptions": [
            str(item).strip()
            for item in (parsed.get("inferred_misconceptions") or [])
            if str(item).strip()
        ]
        if isinstance(parsed.get("inferred_misconceptions"), list)
        else [],
        # 归因是"用预设"还是"先推断"由服务端判定，不采信模型自述——
        # 这个字段要出现在页面上，必须与 Prompt 实际走了哪条分支一致
        "misconception_source": "preset" if _common_misconceptions(kp) else "inferred",
    }

    mistake.ai_analysis = json.dumps(analysis, ensure_ascii=False)
    mistake.variant_questions = json.dumps(variants, ensure_ascii=False)
    mistake.analyze_status = ANALYZE_DONE
    db.commit()

    return {"analysis": analysis, "variant_questions": variants}


def load_analysis(mistake: MistakeBook) -> dict | None:
    """读取已存的分析结果（详情页用）。脏数据按"未分析"处理。"""
    if not mistake.ai_analysis:
        return None
    try:
        parsed = json.loads(mistake.ai_analysis)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def load_variants(mistake: MistakeBook) -> list[dict]:
    """读取已存的变式题（详情页用）。"""
    if not mistake.variant_questions:
        return []
    try:
        parsed = json.loads(mistake.variant_questions)
    except (json.JSONDecodeError, TypeError):
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


__all__ = [
    "VARIANT_COUNT",
    "analyze_mistake",
    "load_analysis",
    "load_variants",
]
