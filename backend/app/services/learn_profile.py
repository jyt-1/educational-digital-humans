# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 学习画像、路径推荐与自适应难度
"""工单19 的三块核心算法（设计文档 2.2 场景三、4.3）。

**画像的权威来源是实时计算**（设计文档 3.3.3 写死）：读 `attempts` ∪ `score_imports`
现算 `mastery`，`student_profile` 表**仅作缓存**。缓存只存 `mastery` 一列，而它完全
可由历史重算（递推状态 `difficulty` / `streak_correct` 另存于 `practice_state`），
因此**不承载任何不可重算的信息**——这是本模块敢在缓存判过期时直接重算的前提。

三个刻意的口径选择，都是为了避免"演示时看起来不对"：

1. **只对"有证据"的知识点算掌握度**。没有任何作答与成绩记录的知识点**不进画像**，
   而不是按 0 分算薄弱——否则新学生一登录，70 个知识点全是 0，路径页会吐出整张图谱。
2. **试卷作答计入画像，但不改 `practice_state`**。考试是"测量"、练习是"训练"，
   一次考试波动不该污染自适应档位（设计文档 2.2 场景三第 5 条）。
3. **时间衰减以 UTC 计时**。`created_at` 由 SQLite 的 `CURRENT_TIMESTAMP` 写入，
   那是 UTC；若拿本地 `datetime.now()` 直接相减，在东八区会凭空多出 8 小时，
   7 天 / 30 天的档位边界会整体偏移。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.learn import (
    DIFFICULTY_EASY,
    DIFFICULTY_MEDIUM,
    DIFFICULTIES,
    Attempt,
    KnowledgePoint,
    PracticeState,
    Question,
    ScoreImport,
    StudentProfile,
)

logger = logging.getLogger(__name__)

# 时间衰减：7 天内 1.0 / 30 天内 0.7 / 更早 0.4（设计文档 4.3「画像算法」）
DECAY_RECENT_DAYS = 7
DECAY_MID_DAYS = 30
DECAY_RECENT = 1.0
DECAY_MID = 0.7
DECAY_OLD = 0.4

# 薄弱判据与自适应升降档规则（设计文档 2.2 场景三）
WEAK_THRESHOLD = 0.6
PROMOTE_STREAK = 3


def utcnow() -> datetime:
    """当前 UTC 时间（naive）。与 SQLite `CURRENT_TIMESTAMP` 写入的格式对齐。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(moment: datetime | None) -> datetime | None:
    """统一成 naive UTC。tz-aware 的输入先换算，naive 的按已是 UTC 处理。"""
    if moment is None:
        return None
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _to_second(moment: datetime | None) -> datetime | None:
    """截断到秒。**时间戳比较必须先过这一手**。

    `created_at` 由 SQLite 的 `CURRENT_TIMESTAMP` 写入，精度是**秒**；而由 Python
    显式赋值的 `datetime` 会带上微秒。两者混在一起比大小，同一瞬间写的两行会分出
    "先后"——`10:00:00.123456 > 10:00:00`，于是缓存被永久判为过期，
    每次读画像都重算一遍（正确性不受影响，但缓存等于没有）。
    截断到秒后，比较的粒度与"缓存是否落后于一整秒"这个语义一致。
    """
    moment = _as_naive_utc(moment)
    return moment.replace(microsecond=0) if moment is not None else None


def time_weight(moment: datetime | None, *, now: datetime | None = None) -> float:
    """时间衰减权重。越近的作答越能代表当前水平。"""
    moment = _as_naive_utc(moment)
    if moment is None:
        return DECAY_OLD
    now = now or utcnow()
    days = (now - moment).total_seconds() / 86400
    if days <= DECAY_RECENT_DAYS:
        return DECAY_RECENT
    if days <= DECAY_MID_DAYS:
        return DECAY_MID
    return DECAY_OLD


# ------------------------------------------------------------------ 掌握度

@dataclass(frozen=True)
class MasteryRecord:
    """一个知识点的掌握度及其证据来源，供仪表盘与路径页展示"依据是什么"。"""

    kp_id: int
    mastery: float
    attempt_count: int  # 单题作答次数
    import_count: int  # 历史成绩导入条数
    last_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "kp_id": self.kp_id,
            "mastery": round(self.mastery, 4),
            "attempt_count": self.attempt_count,
            "import_count": self.import_count,
            "last_at": self.last_at.isoformat() if self.last_at else None,
        }


def _placeholder_ids(db: Session) -> set[int]:
    """「未归类」占位节点。**画像、路径、练习一律过滤**——它的掌握度没有解释力。"""
    rows = db.execute(
        select(KnowledgePoint.id).where(KnowledgePoint.is_placeholder == 1)
    ).scalars()
    return set(rows)


def compute_mastery(db: Session, student_id: int) -> dict[int, MasteryRecord]:
    """实时计算画像：`正确 × 时间衰减权重` 的加权平均（设计文档 4.3）。

    数据源两路，粒度不同但都归一到 [0,1]：`attempts`（单题级，对/错 → 1/0）、
    `score_imports`（知识点级，得分/满分）。历史成绩不写进 `attempts` 的原因见 3.3.3。
    """
    placeholders = _placeholder_ids(db)

    weighted: dict[int, float] = {}
    total_weight: dict[int, float] = {}
    attempts: dict[int, int] = {}
    imports: dict[int, int] = {}
    last_at: dict[int, datetime] = {}

    now = utcnow()

    def _accumulate(kp_id: int | None, score: float, moment: datetime | None) -> None:
        if kp_id is None or kp_id in placeholders:
            return
        weight = time_weight(moment, now=now)
        weighted[kp_id] = weighted.get(kp_id, 0.0) + score * weight
        total_weight[kp_id] = total_weight.get(kp_id, 0.0) + weight
        naive = _as_naive_utc(moment)
        if naive is not None and (kp_id not in last_at or naive > last_at[kp_id]):
            last_at[kp_id] = naive

    for kp_id, is_correct, created_at in db.execute(
        select(Attempt.kp_id, Attempt.is_correct, Attempt.created_at).where(
            Attempt.student_id == student_id
        )
    ).all():
        _accumulate(kp_id, 1.0 if is_correct else 0.0, created_at)
        if kp_id is not None and kp_id not in placeholders:
            attempts[kp_id] = attempts.get(kp_id, 0) + 1

    for kp_id, score, total, created_at in db.execute(
        select(
            ScoreImport.kp_id, ScoreImport.score, ScoreImport.total, ScoreImport.created_at
        ).where(ScoreImport.student_id == student_id)
    ).all():
        # total 有 CHECK (total > 0) 约束兜底，这里再防一次浮点脏数据
        ratio = (score / total) if total else 0.0
        _accumulate(kp_id, max(0.0, min(1.0, ratio)), created_at)
        if kp_id is not None and kp_id not in placeholders:
            imports[kp_id] = imports.get(kp_id, 0) + 1

    return {
        kp_id: MasteryRecord(
            kp_id=kp_id,
            mastery=(weighted[kp_id] / total_weight[kp_id]) if total_weight[kp_id] else 0.0,
            attempt_count=attempts.get(kp_id, 0),
            import_count=imports.get(kp_id, 0),
            last_at=last_at.get(kp_id),
        )
        for kp_id in total_weight
    }


def refresh_profile_cache(db: Session, student_id: int) -> dict[int, MasteryRecord]:
    """重算并覆写 `student_profile` 缓存。调用时机固定为三处（设计文档 3.3.3）：

    `POST /learn/answer`、`POST /learn/profile/import`、`DELETE /learn/profile/import-batches/{id}`。

    实现为"整表删该生 + 重插"而不是逐行 UPSERT：该表按设计是**纯缓存**，
    重建不丢信息，而整删整插天然不会留下"已撤销批次仍在画像里"的残影。
    """
    computed = compute_mastery(db, student_id)
    db.execute(delete(StudentProfile).where(StudentProfile.student_id == student_id))
    db.add_all(
        StudentProfile(student_id=student_id, kp_id=kp_id, mastery=record.mastery)
        for kp_id, record in computed.items()
    )
    db.commit()
    return computed


def read_profile(db: Session, student_id: int) -> dict[int, MasteryRecord]:
    """读画像：缓存新鲜就用缓存，**缺失或过期则实时重算并回写**。

    过期判据是两条时间戳的比较——缓存的 `updated_at` 落后于任一数据源的
    `created_at`，就说明有新的作答或导入还没进画像。这样"答题后仪表盘立即更新"
    与"撤销批次后立即消失"都不依赖刷新时序；最坏情况下漏刷一处，只是慢一次查询，
    不会当着验收的面失败。
    """
    cached_latest = db.scalar(
        select(func.max(StudentProfile.updated_at)).where(
            StudentProfile.student_id == student_id
        )
    )
    if cached_latest is None:
        return refresh_profile_cache(db, student_id)

    source_latest = db.scalar(
        select(func.max(Attempt.created_at)).where(Attempt.student_id == student_id)
    )
    import_latest = db.scalar(
        select(func.max(ScoreImport.created_at)).where(ScoreImport.student_id == student_id)
    )
    newest_source = max(
        [_to_second(m) for m in (source_latest, import_latest) if m is not None],
        default=None,
    )
    if newest_source is not None and newest_source > _to_second(cached_latest):
        logger.info("学生 %s 的画像缓存已过期，实时重算", student_id)
        return refresh_profile_cache(db, student_id)

    rows = db.execute(
        select(StudentProfile.kp_id, StudentProfile.mastery).where(
            StudentProfile.student_id == student_id
        )
    ).all()
    if not rows:
        # 缓存行数为 0 但时间戳存在（历史脏数据）：仍然重算，不得返回空画像
        return refresh_profile_cache(db, student_id)

    placeholders = _placeholder_ids(db)
    counts = _evidence_counts(db, student_id)
    return {
        kp_id: MasteryRecord(
            kp_id=kp_id,
            mastery=mastery,
            attempt_count=counts.get(kp_id, (0, 0))[0],
            import_count=counts.get(kp_id, (0, 0))[1],
            last_at=None,
        )
        for kp_id, mastery in rows
        if kp_id not in placeholders
    }


def _evidence_counts(db: Session, student_id: int) -> dict[int, tuple[int, int]]:
    """缓存命中路径下的证据条数（次数是展示信息，不参与判过期）。"""
    counts: dict[int, tuple[int, int]] = {}
    for kp_id, total in db.execute(
        select(Attempt.kp_id, func.count())
        .where(Attempt.student_id == student_id, Attempt.kp_id.isnot(None))
        .group_by(Attempt.kp_id)
    ).all():
        counts[kp_id] = (total, 0)
    for kp_id, total in db.execute(
        select(ScoreImport.kp_id, func.count())
        .where(ScoreImport.student_id == student_id)
        .group_by(ScoreImport.kp_id)
    ).all():
        attempts, _ = counts.get(kp_id, (0, 0))
        counts[kp_id] = (attempts, total)
    return counts


# ------------------------------------------------------------------ 学习路径

def _load_nodes(db: Session, course: str | None = None) -> dict[int, KnowledgePoint]:
    """图谱节点（**过滤占位节点**）。"""
    query = select(KnowledgePoint).where(KnowledgePoint.is_placeholder == 0)
    if course:
        query = query.where(KnowledgePoint.course == course)
    return {node.id: node for node in db.execute(query).scalars()}


def recommend_path(
    db: Session,
    student_id: int,
    *,
    course: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """学习路径推荐：定位薄弱点 → 沿图谱上溯到最先修薄弱点 → 输出顺序与可解释理由。

    **只对"有证据"的知识点判薄弱**：没有任何作答与成绩记录的知识点不进路径，
    否则新学生一登录就会拿到整张图谱当作"薄弱点"。

    上溯得到的"最先修薄弱点"用 `is_entry` 标出：同一入口下的薄弱点按图谱序跟在它后面。
    返回的是**全部薄弱点**而非只有入口——入口只回答"该从哪开始"，
    后面那些同样没掌握的点仍要出现在路径里，否则路径是不完整的。
    """
    profile = read_profile(db, student_id)
    nodes = _load_nodes(db, course)

    weak = {
        kp_id: record
        for kp_id, record in profile.items()
        if kp_id in nodes and record.mastery < WEAK_THRESHOLD
    }
    if not weak:
        return []

    # 沿先修链上溯：只要父节点也薄弱就继续往上，得到的即"最先修薄弱点"
    entry_of: dict[int, int] = {}
    for kp_id in weak:
        cursor = kp_id
        visited = {cursor}
        while True:
            parent = nodes[cursor].prereq_id
            if parent is None or parent not in weak or parent in visited:
                break
            visited.add(parent)
            cursor = parent
        entry_of[kp_id] = cursor

    # 入口按图谱序（seed 的 order_no 即拓扑序：先修总是先于后继被登记），
    # 同一入口内再按图谱序——这样"先修补完再补后继"的顺序天然成立
    ordered = sorted(
        weak,
        key=lambda kp_id: (nodes[entry_of[kp_id]].order_no, nodes[kp_id].order_no),
    )

    # 每个入口带上"它挡在谁前面"，理由才有说服力
    blocked: dict[int, list[str]] = {}
    for kp_id, entry in entry_of.items():
        if kp_id != entry:
            blocked.setdefault(entry, []).append(nodes[kp_id].name)

    items: list[dict] = []
    for index, kp_id in enumerate(ordered, start=1):
        node = nodes[kp_id]
        record = weak[kp_id]
        entry = entry_of[kp_id]
        percent = f"{record.mastery:.0%}"

        if kp_id == entry:
            reason = f"掌握度 {percent}，未达到 {WEAK_THRESHOLD:.0%} 的达标线"
            names = blocked.get(kp_id)
            if names:
                preview = "、".join(f"「{name}」" for name in names[:3])
                suffix = " 等" if len(names) > 3 else ""
                reason += f"；且它是 {preview}{suffix} 的前置知识点，需先补"
        else:
            reason = (
                f"掌握度 {percent}，未达标；其前置「{nodes[entry].name}」同样薄弱，"
                f"应先补完前置再学这里"
            )

        items.append(
            {
                "order": index,
                "kp_id": kp_id,
                "name": node.name,
                "mastery": round(record.mastery, 4),
                "is_entry": kp_id == entry,
                "entry_kp_id": entry,
                "entry_name": nodes[entry].name,
                "reason": reason,
            }
        )

    return items[:limit] if limit else items


# ------------------------------------------------------------------ 自适应难度

def promote(difficulty: str) -> str:
    """升一档，到顶不再升。"""
    index = DIFFICULTIES.index(difficulty) if difficulty in DIFFICULTIES else 0
    return DIFFICULTIES[min(index + 1, len(DIFFICULTIES) - 1)]


def demote(difficulty: str) -> str:
    """降一档，到底不再降。"""
    index = DIFFICULTIES.index(difficulty) if difficulty in DIFFICULTIES else 0
    return DIFFICULTIES[max(index - 1, 0)]


def get_practice_state(db: Session, student_id: int, kp_id: int) -> PracticeState:
    """取该生在该知识点上的练习档位；没有就按「简单」起步（新知识点从最易开始）。"""
    state = db.scalar(
        select(PracticeState).where(
            PracticeState.student_id == student_id, PracticeState.kp_id == kp_id
        )
    )
    if state is None:
        state = PracticeState(
            student_id=student_id, kp_id=kp_id, difficulty=DIFFICULTY_EASY, streak_correct=0
        )
        db.add(state)
        db.flush()
    return state


def apply_answer_to_state(state: PracticeState, is_correct: bool) -> str:
    """按一次作答推进难度档：连对 3 题升档，答错降档（设计文档 2.2 场景三第 5 条）。

    升档后 `streak_correct` 归零重新计数——否则连对 4 题会连升两档。
    """
    if is_correct:
        state.streak_correct += 1
        if state.streak_correct >= PROMOTE_STREAK:
            state.difficulty = promote(state.difficulty)
            state.streak_correct = 0
    else:
        state.difficulty = demote(state.difficulty)
        state.streak_correct = 0
    return state.difficulty


def pick_questions(
    db: Session,
    *,
    kp_id: int,
    difficulty: str,
    count: int,
    exclude_ids: set[int] | None = None,
) -> list:
    """按难度档取题，题量不足时按"离当前档最近"的顺序补足。

    补足是必要的：某个知识点在某一档下可能只有 2 道题，而 `count` 是 5；
    与其返回 2 道，不如把相邻档的题也拿来用——练习的价值是"练"，不是"分档"。
    """
    if count <= 0:
        return []

    candidates = list(
        db.execute(select(Question).where(Question.kp_id == kp_id)).scalars()
    )
    if exclude_ids:
        candidates = [q for q in candidates if q.id not in exclude_ids]
    if not candidates:
        return []

    center = DIFFICULTIES.index(difficulty) if difficulty in DIFFICULTIES else 0

    def _distance(question) -> tuple[int, int]:
        index = (
            DIFFICULTIES.index(question.difficulty)
            if question.difficulty in DIFFICULTIES
            else DIFFICULTIES.index(DIFFICULTY_MEDIUM)
        )
        return (abs(index - center), question.id)

    candidates.sort(key=_distance)
    return candidates[:count]


__all__ = [
    "DECAY_MID_DAYS",
    "DECAY_RECENT_DAYS",
    "MasteryRecord",
    "PROMOTE_STREAK",
    "WEAK_THRESHOLD",
    "apply_answer_to_state",
    "compute_mastery",
    "demote",
    "get_practice_state",
    "pick_questions",
    "promote",
    "read_profile",
    "recommend_path",
    "refresh_profile_cache",
    "time_weight",
    "utcnow",
]
