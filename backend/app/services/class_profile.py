# [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 班级学情聚合与备课注入渲染
"""把"一群学生的画像"聚合成教师看得懂、且模型能直接吃的几组形态（设计文档 3.2.8）。

**多个出口，一份数据**：

- `class_heatmap()` → 知识点 × 学生网格，喂看板热力图（场景五功能清单第 3 条）；
- `class_insight()` → 结构化聚合 + 薄弱排行，喂看板其余部分；
- `build_analytics_brief()` → 渲染好的文字，喂 LLM 与前端**生成前预览**。

它们同源是刻意的：教师预览到的就是模型看到的。若前端另写一套摘要，
就重新制造了"看到的与喂进去的不一致"这一信任缺口（设计文档 3.2.8 末注）。

**口径两条，都是被用例守着的**：

1. **mean-of-means**：先算每个学生的掌握度，再对全班取平均。不是把所有作答
   混在一起算——混算时答得多的人会主导班级数字，而教师说"我班平均掌握度"时
   想的是每人一票。
2. **强制覆盖率**：没有覆盖率这个功能就是负资产。"掌握度 42%"若只来自 30 人
   中的 1 人，教师照着它备课就被误导了——**误导比没有更糟**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learn import KnowledgePoint
from app.models.teach import Class, ClassMember
from app.models.user import User
from app.services import learn_profile

# 注入提示词的薄弱点条数上限。太多会稀释重点，也让提示词变长拖慢生成
BRIEF_TOP_N = 6
# 热力图行数上限。30 学生 × 12 知识点的格子还能看，再多就成了噪声
HEATMAP_TOP_N = 12
# 难度分档线：掌握度 >= 0.8 配困难题、>= 0.6 配中等题、其余配简单题
HARD_LINE = 0.8


@dataclass(frozen=True)
class ClassMastery:
    """班级在某个知识点上的聚合值，**永远带着分母**。"""

    kp_id: int
    mastery: float       # mean-of-means
    student_count: int   # 该知识点有证据的学生数
    class_size: int      # 班总人数

    @property
    def coverage(self) -> float:
        return (self.student_count / self.class_size) if self.class_size else 0.0

    def to_dict(self) -> dict:
        return {
            "kp_id": self.kp_id,
            "mastery": round(self.mastery, 4),
            "student_count": self.student_count,
            "class_size": self.class_size,
            "coverage": round(self.coverage, 4),
        }


def member_ids(db: Session, class_id: int) -> list[int]:
    """班级学生 id 列表。**排序**是为了让同样的输入产出同样的提示词——
    否则同一份学情每次生成的 brief 行序都可能不同，教师会以为数据变了。
    """
    return list(
        db.scalars(
            select(ClassMember.student_id)
            .where(ClassMember.class_id == class_id)
            .order_by(ClassMember.id)
        )
    )


def class_mastery(db: Session, class_id: int) -> dict[int, ClassMastery]:
    """班级知识点聚合（口径见模块 docstring）。无成员的班返回空 dict。"""
    ids = member_ids(db, class_id)
    if not ids:
        return {}

    grouped = learn_profile._compute(db, ids)
    class_size = len(ids)
    return {
        kp_id: ClassMastery(
            kp_id=kp_id,
            # 分母是"该知识点有证据的学生"而非全班：没作答的学生不是"掌握度 0"，
            # 是"没有证据"。把他们按 0 分算会把班级数字整体压低且毫无解释力
            mastery=sum(record.mastery for record in per_student.values())
            / len(per_student),
            student_count=len(per_student),
            class_size=class_size,
        )
        for kp_id, per_student in grouped.items()
        if per_student
    }


def coverage(db: Session, class_id: int) -> dict:
    """班级整体参与度：全班多少人、多少人留下了证据。

    与 `class_mastery` 里逐知识点的覆盖率是**两个不同的问题**——这个回答
    "这个班的数据能不能看"，那个回答"某个知识点的数字能不能看"。
    """
    ids = member_ids(db, class_id)
    if not ids:
        return {"class_size": 0, "covered_students": 0, "rate": 0.0}
    grouped = learn_profile._compute(db, ids)
    covered = len({sid for per_student in grouped.values() for sid in per_student})
    return {
        "class_size": len(ids),
        "covered_students": covered,
        "rate": round(covered / len(ids), 4),
    }


def _node_map(db: Session) -> dict[int, KnowledgePoint]:
    """非占位知识点。与画像、路径用同一套过滤口径。"""
    return {
        node.id: node
        for node in db.scalars(
            select(KnowledgePoint).where(KnowledgePoint.is_placeholder == 0)
        )
    }


def _blocked_by(nodes: dict[int, KnowledgePoint]) -> dict[int, list[str]]:
    """图谱上的直接后继：`prereq_id → [后继名]`。回答"这个点没掌握会挡住谁"。"""
    blocked: dict[int, list[str]] = {}
    for node in nodes.values():
        if node.prereq_id is not None:
            blocked.setdefault(node.prereq_id, []).append(node.name)
    return blocked


def _display_names(db: Session, student_ids: list[int]) -> dict[int, str]:
    rows = db.execute(
        select(User.id, User.display_name, User.username).where(User.id.in_(student_ids))
    ).all()
    return {row.id: (row.display_name or row.username) for row in rows}


def class_heatmap(db: Session, class_id: int, *, top_n: int = HEATMAP_TOP_N) -> dict:
    """知识点 × 学生 网格，喂 ECharts heatmap（场景五功能清单第 3 条）。

    **列的是全部有证据的知识点、按掌握度升序取前 `top_n`**，不是只列薄弱点：
    只画薄弱点的热力图是自我实现的——满屏红，看不出"哪些已经掌握"，
    教师也就失去了"这节课不用讲什么"这一半信息。

    **只列有证据的学生**：把没作答的学生也铺进去，图上会是一整片空白，
    而"有人没交"这件事已经由 `coverage` 单独说了，不需要用空白格再说一遍。

    `cells` 里**只出现有数据的格子**；缺格由 ECharts 自然留白——
    这与"掌握度 0"在视觉上是可区分的，正是覆盖率要求的那条底线。
    """
    stats = class_mastery(db, class_id)
    if not stats:
        return {"kps": [], "students": [], "cells": [], "kp_ids": [], "student_ids": []}

    nodes = _node_map(db)
    ordered = sorted(
        ((kp_id, stat) for kp_id, stat in stats.items() if kp_id in nodes),
        key=lambda item: (item[1].mastery, nodes[item[0]].order_no),
    )[:top_n]
    kp_ids = [kp_id for kp_id, _ in ordered]
    kp_names = [nodes[kp_id].name for kp_id in kp_ids]

    ids = member_ids(db, class_id)
    grouped = learn_profile._compute(db, ids)
    # 在选中知识点上至少有一条证据的学生，保持班级成员顺序
    student_ids = [
        sid
        for sid in ids
        if any(sid in grouped.get(kp_id, {}) for kp_id in kp_ids)
    ]
    names = _display_names(db, student_ids)

    index_of = {sid: index for index, sid in enumerate(student_ids)}
    cells = [
        [index_of[sid], kp_index, round(grouped[kp_id][sid].mastery, 4)]
        for kp_index, kp_id in enumerate(kp_ids)
        for sid in student_ids
        if sid in grouped.get(kp_id, {})
    ]

    return {
        "kps": kp_names,
        "students": [names.get(sid, str(sid)) for sid in student_ids],
        "cells": cells,
        "kp_ids": kp_ids,
        "student_ids": student_ids,
    }


def _difficulty_mix(rows: list[ClassMastery]) -> dict[str, int]:
    """按各知识点掌握度分档，给出简单/中等/困难的**知识点条数**配比依据。

    统计单位是"知识点"而不是"题目"——题目还没生成，此时能确定的只有
    "哪些点需要出难题"。给出条数后由模型自行换算成题量比例。

    **入参必须是全班有证据的知识点**（设计文档 3.2.8 第④条："按**班级**掌握度算出"），
    不能只传薄弱点：薄弱点按定义全部低于 `WEAK_THRESHOLD`，那样"中等/困难"两档
    永远为零，这行会退化成恒定的"简单 100%"——既没信息量，还会误导模型把整套题
    都出成简单题，恰恰放弃了对已掌握知识点的区分度。
    """
    mix = {"简单": 0, "中等": 0, "困难": 0}
    for stat in rows:
        if stat.mastery >= HARD_LINE:
            mix["困难"] += 1
        elif stat.mastery >= learn_profile.WEAK_THRESHOLD:
            mix["中等"] += 1
        else:
            mix["简单"] += 1
    return mix


def class_insight(db: Session, class_id: int, *, top_n: int = 10) -> dict:
    """看板主数据：班级信息 + 覆盖率 + 薄弱排行（含下游影响）+ 热力图。"""
    klass = db.get(Class, class_id)
    if klass is None:
        return {}

    stats = class_mastery(db, class_id)
    nodes = _node_map(db)
    blocked = _blocked_by(nodes)

    rows = [
        (nodes[kp_id], stat)
        for kp_id, stat in stats.items()
        if kp_id in nodes and stat.mastery < learn_profile.WEAK_THRESHOLD
    ]
    rows.sort(key=lambda item: (item[1].mastery, item[0].order_no))

    weak_points = []
    for node, stat in rows[:top_n]:
        item = stat.to_dict()
        item.update(
            {
                "name": node.name,
                "course": node.course,
                "order_no": node.order_no,
                "blocks": blocked.get(node.id, []),
            }
        )
        weak_points.append(item)

    return {
        "class": {
            "id": klass.id,
            "name": klass.name,
            "course_name": klass.course_name,
        },
        "coverage": coverage(db, class_id),
        "heatmap": class_heatmap(db, class_id),
        "kp_count": len(stats),
        "weak_count": len(rows),
        "weak_points": weak_points,
    }


def _preset_misconceptions(node: KnowledgePoint | None) -> list[str]:
    """读 `common_misconceptions`（工单19 预置的常见错误类型）。**有值才带**。

    复用 `mistake.py` 同一列的解析口径；解析失败按空处理而不是抛异常——
    学情注入失败不该让整个备课流程挂掉。
    """
    if node is None or not node.common_misconceptions:
        return []
    try:
        parsed = json.loads(node.common_misconceptions)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def build_analytics_brief(db: Session, class_id: int, *, top_n: int = BRIEF_TOP_N) -> str | None:
    """把班级学情渲染成**将注入 LLM 的那段文字**。

    **全班无任何证据时返回 `None`**（不是空串、不是"暂无数据"）。理由：教案模板
    在拿到学情时会要求"依据下方数据引用具体数字"，若这时塞进去一段"暂无数据"，
    提示词就自相矛盾了。返回 `None` 让上层干净地退回原表述。
    """
    insight = class_insight(db, class_id)
    if not insight:
        return None
    cov = insight["coverage"]
    if not cov["covered_students"]:
        return None

    # 已算好的聚合值。难度配比直接用这里的对象，不从 weak_points 的 dict 反构——
    # 反构会多一道无谓的转换，也让"这份数据来自哪"变得含糊
    stats = class_mastery(db, class_id)

    head = (
        f"【本班学情】{insight['class']['name']}（{insight['class']['course_name']}），"
        f"共 {cov['class_size']} 人，其中 {cov['covered_students']} 人有作答或成绩记录。"
    )
    guard = "以下为本班真实学情数据，只能引用，不得编造、不得外推。"

    weak = insight["weak_points"][:top_n]
    if not weak:
        # 有数据但不薄弱：仍要注入，让模型知道"本班已达标"，不要瞎补前置复习
        return (
            f"{head}\n"
            f"所有已采集到的知识点平均掌握度均达到 "
            f"{learn_profile.WEAK_THRESHOLD:.0%} 的达标线，本课无需额外安排前置复习。\n"
            f"{guard}"
        )

    nodes = _node_map(db)
    lines = [
        head,
        guard,
        "",
        f"薄弱知识点（平均掌握度低于 {learn_profile.WEAK_THRESHOLD:.0%} 的达标线，"
        f"共 {insight['weak_count']} 个，按掌握度升序列出前 {len(weak)} 个）：",
    ]
    for index, item in enumerate(weak, start=1):
        line = (
            f"{index}. {item['name']}：平均掌握度 {item['mastery']:.0%}"
            f"（{item['class_size']} 人中 {item['student_count']} 人有作答记录）"
        )
        presets = _preset_misconceptions(nodes.get(item["kp_id"]))
        if presets:
            line += f"；常见错误：{'、'.join(presets[:3])}"
        if item["blocks"]:
            line += f"；该知识点未掌握会直接影响：{'、'.join(item['blocks'][:3])}"
        lines.append(line)

    # 分档口径是**全班有证据的知识点**，不是上面列出的薄弱点（理由见 _difficulty_mix）
    mix = _difficulty_mix(list(stats.values()))
    total = sum(mix.values()) or 1
    ratio = "、".join(f"{name} {value / total:.0%}" for name, value in mix.items())
    lines += [
        "",
        f"建议难度配比：{ratio}"
        f"（按本班 {total} 个有证据的知识点各自的掌握度分档统计；"
        f"难度不是越高越好，按此比例出题才能同时覆盖补弱与拔高）。",
        f"课堂设计请针对前 {min(3, len(weak))} 个薄弱点安排前置复习或导入环节。",
    ]
    return "\n".join(lines)
