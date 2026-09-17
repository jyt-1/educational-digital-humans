# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 作答判分与落库
"""练习 / 试卷 / 变式题三条作答路径共用的判分与落库逻辑。

**为什么必须收敛到一处**：三条路径都要"判分 → 写 `attempts` → 入画像 → 答错进错题本"，
各写一套的结果是三种口径——最典型的是判分，练习侧把 "A" 判对、试卷侧把 "A. 链式法则" 判错。

**`practice_state` 只由练习接口推进**（一条规则贯穿三处）：
- 练习（`POST /learn/answer`）：连对 3 升档、答错降档，这是设计文档 2.2 场景三第 5 条。
- 试卷：**不动**。考试是"测量"、练习是"训练"，一次考试波动不该污染自适应档位。
- 变式题：**不动**。它是针对某个错题的定点补救，有独立的 `variant_tries` 计数循环。

**LLM 生成的答案形态不可控**，判分因此写得比"字符串相等"宽：同一条正确答案可能是
"链式法则"（习题的文本答案）或 "B"（选择题字母），学生也可能答字母、答整条选项文本、
答"对/正确/√"。判分器要能把这些等价写法认成同一个，否则演示时会出现
"我明明答对了却判错"——这类问题现场无法解释。
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learn import ANALYZE_PENDING, Attempt, MistakeBook, Question

logger = logging.getLogger(__name__)

# 判断题的同义写法（LLM 出判断题时答案可能是 "对"，学生可能答 "正确"/"√"）
_TRUE_WORDS = {"对", "正确", "是", "true", "t", "yes", "y", "√"}
_FALSE_WORDS = {"错", "错误", "否", "不对", "false", "f", "no", "n", "x", "×"}

# 选项前缀："A." / "A、" / "A)" / "A）" / "A:"
_OPTION_PREFIX_RE = re.compile(r"^([a-z0-9])[.、．)）:：]\s*(.*)$")
_WHITESPACE_RE = re.compile(r"[\s　]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def load_options(options_json: str | None) -> list[str]:
    """解析 `options_json`。脏数据一律当"没有选项"处理，不抛异常中断判分。"""
    if not options_json:
        return []
    try:
        parsed = json.loads(options_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        # 兼容 {"A": "链式法则"} 这种形态
        return [f"{key}. {value}" for key, value in parsed.items()]
    return []


def _normalize(text: str | None) -> str:
    return _WHITESPACE_RE.sub("", str(text or "")).strip().lower()


def _option_text_by_letter(letter: str, options: list[str]) -> str | None:
    """从 "A. 链式法则" 里取出 "链式法则"。取不到返回 None。"""
    for option in options:
        matched = _OPTION_PREFIX_RE.match(_normalize(option))
        if matched and matched.group(1) == letter:
            return matched.group(2)
    return None


def _strip_option_prefix(text: str) -> str:
    """"a.链式法则" → "链式法则"；没有前缀则原样返回。

    正确答案无论是 "A. 链式法则"（整条选项文本）还是 "链式法则"（纯文本），
    学生答另一个写法都该判对——两边各去掉前缀再比，这类等价一次收敛。
    """
    matched = _OPTION_PREFIX_RE.match(text)
    return matched.group(2) if matched else text


def judge_answer(
    user_answer: str | None,
    correct_answer: str | None,
    options: list[str] | None = None,
) -> bool:
    """判分。等价写法（字母 / 选项文本 / 判断词同义）一律认对。"""
    user = _normalize(user_answer)
    correct = _normalize(correct_answer)
    if not user or not correct:
        return False

    if user == correct:
        return True

    # 多选题："BA" 与 "AB" 等价
    user_alnum = _NON_ALNUM_RE.sub("", user)
    correct_alnum = _NON_ALNUM_RE.sub("", correct)
    if len(correct_alnum) > 1 and len(user_alnum) > 1:
        if sorted(user_alnum) == sorted(correct_alnum):
            return True

    # "A. 链式法则" 与 "链式法则" 是同一个答案的两种写法：
    # 选项前缀（"A."）只是排版，不是答案的一部分。LLM 出题时两种写法都会出现。
    if _strip_option_prefix(user) == _strip_option_prefix(correct):
        return True

    # 判断题同义写法
    if user in _TRUE_WORDS and correct in _TRUE_WORDS:
        return True
    if user in _FALSE_WORDS and correct in _FALSE_WORDS:
        return True

    options = options or []

    # 正确答案是选项字母：学生可能答了字母，也可能答了整条选项文本
    if len(correct) == 1 and correct.isalnum():
        if user[:1] == correct:
            return True
        option_text = _option_text_by_letter(correct, options)
        if option_text is not None:
            if _strip_option_prefix(user) == option_text:
                return True

    # 正确答案是文本（无论是 "链式法则" 还是 "A. 链式法则"）：
    # 学生可能答了对应的选项字母
    if len(user) == 1 and user.isalnum():
        option_text = _option_text_by_letter(user, options)
        if option_text is not None and option_text == _strip_option_prefix(correct):
            return True

    return False


# ------------------------------------------------------------------ 落库

def record_attempt(
    db: Session,
    *,
    student_id: int,
    question: Question,
    user_answer: str | None,
    is_variant: bool = False,
    is_exam: bool = False,
) -> tuple[Attempt, bool]:
    """判分并写一条 `attempts`。返回 `(作答记录, 是否答对)`。"""
    is_correct = judge_answer(user_answer, question.answer, load_options(question.options_json))
    attempt = Attempt(
        student_id=student_id,
        question_id=question.id,
        kp_id=question.kp_id,
        user_answer=user_answer,
        is_correct=is_correct,
        is_variant=is_variant,
        is_exam=is_exam,
    )
    db.add(attempt)
    db.flush()
    return attempt, is_correct


def ensure_mistake(
    db: Session, *, student_id: int, question: Question, attempt: Attempt
) -> MistakeBook:
    """答错时把题收进错题本；同一道题重复答错**复用同一行**。

    `mistake_book` 的 DDL 上没有 `UNIQUE(student_id, question_id)`，去重只能在这一层做。
    不去重的后果很直观：同一道题错三次，错题本就出现三条一模一样的记录。

    复用行时**保留已有分析结果**、不自动重新分析——学生对同一道题的再次做错，
    大概率是同一个概念没转过弯，重跑一次 LLM 只会得到几乎一样的结论，白花一次调用。
    需要重做分析时由前端点「重新分析」显式触发。
    """
    existing = db.scalar(
        select(MistakeBook).where(
            MistakeBook.student_id == student_id, MistakeBook.question_id == question.id
        )
    )
    if existing is not None:
        existing.attempt_id = attempt.id
        existing.kp_id = question.kp_id
        if existing.analyze_status not in ("done", "analyzing"):
            existing.analyze_status = ANALYZE_PENDING
        db.flush()
        return existing

    mistake = MistakeBook(
        student_id=student_id,
        question_id=question.id,
        attempt_id=attempt.id,
        kp_id=question.kp_id,
        analyze_status=ANALYZE_PENDING,
    )
    db.add(mistake)
    db.flush()
    return mistake


__all__ = [
    "ensure_mistake",
    "judge_answer",
    "load_options",
    "record_attempt",
]
