# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 知识点统一匹配模块
"""知识点统一匹配（设计文档 3.2.5）。

系统里的知识点标签有**三个来源，全是自由文本**：工单17 由 LLM 生成的题目
`knowledge_point`、学生导入成绩表里人工填写的知识点、助教里学生口语化的提问。
三者都要挂到图谱节点 `kp_id` 上才能参与画像与推荐——**若三个调用方各写一套匹配
逻辑，后期必然互相打架**，故统一收敛到本模块。

两个入口的差异不在阈值，而在匹配模式：

| 入口 | 适用输入 | 匹配方式 |
| --- | --- | --- |
| `match_label` | 短标签、单元格文本 | 归一化全等 → 别名表 →（可选）向量 |
| `match_text` | 整句口语化提问 | 图谱词典最长子串扫描 →（可选）向量 |

**为什么整句不能直接做向量匹配**：口语问句与知识点名词短语的语义空间不对齐——
"Adam 是啥"与"Adam优化器"的余弦相似度并不高，且要在 40+ 候选里命中 0.85 很难。
正确做法是**先把知识点从句子里"抠"出来**：词典里命中子串 "Adam" 即可直接挂到
「Adam优化器」，又准又便宜。这也正是 `kp_alias` 存短别名的意义。

**无状态约定**：本模块**不持有 session、不写任何表**，只做纯匹配计算。
`load_index()` 是唯一的读库函数（显式接收 `db` 参数，只读不写）；
**写 `kp_alias` 由各调用方自行负责**——`/kp/sync?target=questions` 落
`exercise`/`exam`，成绩导入落 `score_import`，消息挂靠落 `message`，人工归并落 `manual`。
这一条必须写死：若三个调用方都不写库，"自学习"就是空话。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 匹配方法。`none` 表示未命中，`placeholder` 表示按调用方策略落到「未归类」节点
METHOD_EXACT = "exact"
METHOD_ALIAS = "alias"
METHOD_DICT = "dict"
METHOD_VECTOR = "vector"
METHOD_PLACEHOLDER = "placeholder"
METHOD_NONE = "none"

# 兜底策略（由调用方传参决定，本模块最关键的约定）
ON_UNMATCHED_PLACEHOLDER = "placeholder"  # 题目同步：丢了就没了，宁可挂「未归类」也要一条不丢
ON_UNMATCHED_DROP = "drop"  # 成绩导入 / 问题挂靠：改一下重传成本极低，混进「未归类」会脏初始画像

# 常见后缀：归一化时剥掉，让"梯度下降"/"梯度下降法"落到同一节点。
# 顺序有关系——长后缀在前，"梯度下降算法"要剥成"梯度下降"而不是"梯度下降算"。
# 刻意保守：剥得太狠会让本该区分开的节点撞车（如同时存在"神经网络"与"神经网络模型"），
# 且剥完必须还剩 ≥ 2 个字（见 normalize_label 的长度守卫），否则"算法"本身会被剥空。
_SUFFIXES = ("算法", "方法", "技术", "模型", "机制", "原理", "理论", "基础", "法")

# 归一化只保留：数字、字母、汉字。其余（空白/标点/全角符号）一律去掉
_KEEP_RE = re.compile(r"[^0-9a-z一-鿿]+")

VECTOR_THRESHOLD = 0.85


@dataclass(frozen=True)
class KpNode:
    """匹配用的图谱节点快照（调用方从库里读出后传入）。"""

    id: int
    name: str
    is_placeholder: bool = False


@dataclass(frozen=True)
class MatchResult:
    """三个调用方共用的返回结构。

    `/api/learn/related` 的三个出口、`/kp/sync` 的报告与导入失败明细**都依赖这个结构**，
    不预先定义就会出现三套字段。
    """

    raw_text: str
    kp_id: int | None
    matched_text: str | None
    method: str
    confidence: float

    @property
    def matched(self) -> bool:
        return self.kp_id is not None

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "kp_id": self.kp_id,
            "matched_text": self.matched_text,
            "method": self.method,
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True)
class KpIndex:
    """一次匹配所需的全部只读数据：图谱节点 + 别名表 + 占位节点。"""

    nodes: tuple[KpNode, ...] = ()
    aliases: Mapping[str, int] = field(default_factory=dict)  # norm_label -> kp_id
    placeholder_id: int | None = None

    def node_by_id(self) -> dict[int, KpNode]:
        return {n.id: n for n in self.nodes}


# ------------------------------------------------------------------ 归一化

def normalize_label(text: str | None) -> str:
    """标签归一化：全半角统一 → 小写 → 去空白与标点 → 剥常见后缀。

    这是「两档上线」里第一档的判据，也是别名表 `norm_label` 的写入格式——
    两边必须走同一个函数，否则别名永远命中不了。
    """
    if not text:
        return ""
    # NFKC 把全角字母数字、罗马数字等折成半角，比手写映射表可靠
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = _KEEP_RE.sub("", normalized)

    for suffix in _SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def normalize_difficulty(raw: str | None) -> str:
    """把 LLM 或人工填写的难度词归一到三档（设计文档 3.2.6 的映射表）。

    只作用于 `questions` 汇入，**不修改** `exercises` / `exam_questions` 的原列——
    那两张表是展示与导出的依据，且工单17 已交付、不加 CHECK 约束。
    """
    text = (raw or "").strip()
    if not text:
        return "中等"
    if any(word in text for word in ("易", "简单", "基础", "入门")):
        return "简单"
    if any(word in text for word in ("难", "困难", "挑战", "进阶", "高难")):
        return "困难"
    return "中等"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ------------------------------------------------------------------ 入口一：短标签

def match_label(
    text: str | None,
    *,
    index: KpIndex,
    on_unmatched: str = ON_UNMATCHED_DROP,
    use_vector: bool = False,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> MatchResult | None:
    """匹配单条短标签（题目的 `knowledge_point`、成绩表的单元格）。

    漏斗：① 归一化后与节点名全等 → ② 查 `kp_alias` 别名表 → ③（可选）向量余弦 ≥ 0.85。
    返回 `None` 即未命中且策略为 `drop`；策略为 `placeholder` 时返回挂到「未归类」的结果。
    """
    raw = (text or "").strip()
    norm = normalize_label(raw)

    if not norm:
        return _unmatched(raw, index, on_unmatched)

    by_norm = _nodes_by_norm(index.nodes)

    # ① 归一化全等。工单17 的 prompt 修正后，新题目标签会从上下文【涉及知识点】
    #    原样选取，配合后缀归一化足以吃掉大部分历史漂移——这是"两档上线"的主要命中路径
    node = by_norm.get(norm)
    if node is not None:
        return MatchResult(raw, node.id, node.name, METHOD_EXACT, 1.0)

    # ② 别名表：命中过一次的标签，之后直接走这里
    alias_id = index.aliases.get(norm)
    if alias_id is not None:
        node = index.node_by_id().get(alias_id)
        if node is not None:
            return MatchResult(raw, node.id, node.name, METHOD_ALIAS, 0.95)
        logger.warning("kp_alias 指向不存在的知识点 %s（norm=%s），已忽略", alias_id, norm)

    # ③ 词典最长子串扫描——与 match_text 共用同一套词典（v1.4 插入，实测把未归类
    #    从 47.8% 压到 10.9%）。吃的正是"反向传播的基本原理与适用范围"这类**短语式标签**：
    #    它们与图谱节点不是语义距离远，而是**形态不同**（短语 vs 名词短语），
    #    本来就该走词典而不是向量。规则确定性、零 API 成本、结果可解释。
    hits = scan_dict(norm, index)
    if hits:
        kp_id, hit_word, _length = hits[0]  # 最长命中优先
        node = index.node_by_id().get(kp_id)
        return MatchResult(raw, kp_id, node.name if node else hit_word, METHOD_DICT, 0.9)

    # ④ 向量兜底：仅在判据（未归类题目在练习候选集中占比 > 20%）超线后才打开
    if use_vector and embed is not None:
        hit = _vector_match(raw, index.nodes, embed)
        if hit is not None:
            return hit

    return _unmatched(raw, index, on_unmatched)


# ------------------------------------------------------------------ 入口二：整句提问

def match_text(
    text: str | None,
    *,
    index: KpIndex,
    on_unmatched: str = ON_UNMATCHED_DROP,
    use_vector: bool = False,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[MatchResult]:
    """从句子里抠出知识点（**一条提问可挂多个知识点**，故返回列表）。

    词典 = `knowledge_points.name` ∪ `kp_alias.raw_label`，40~200 条纯字符串，
    用最长子串扫描即可，成本近乎为零。
    """
    raw = (text or "").strip()
    norm = normalize_label(raw)
    if not norm:
        return _unmatched_list(raw, index, on_unmatched)

    node_map = index.node_by_id()
    results = [
        MatchResult(raw, kp_id, node_map[kp_id].name if kp_id in node_map else hit_word, METHOD_DICT, 0.9)
        for kp_id, hit_word, _length in scan_dict(norm, index)
    ]

    if results:
        return results

    if use_vector and embed is not None:
        hit = _vector_match(raw, index.nodes, embed)
        if hit is not None:
            return [hit]

    return _unmatched_list(raw, index, on_unmatched)


# ------------------------------------------------------------------ 词典扫描

def build_dict(index: KpIndex) -> dict[str, int]:
    """合成匹配词典：图谱节点名 ∪ 别名，键为归一化文本。

    节点里带有短别名的（`kp_alias` 存的就是短别名，如 "adam"）能让口语提问
    "Adam 是啥"直接命中「Adam优化器」——这正是别名表存短别名的意义。
    占位节点**不进词典**：它只承接兜底，不该被任何标签主动命中。
    """
    entries: dict[str, int] = {}
    for node in index.nodes:
        if node.is_placeholder:
            continue
        key = normalize_label(node.name)
        if key:
            entries.setdefault(key, node.id)
    for alias_norm, kp_id in index.aliases.items():
        if alias_norm:
            entries.setdefault(alias_norm, kp_id)
    return entries


def scan_dict(norm_text: str, index: KpIndex) -> list[tuple[int, str, int]]:
    """在归一化文本里做最长子串扫描，返回 `[(kp_id, 命中词, 词长)]`，长的在前。

    **跨度占位**是关键：长词先扫，短词若完全落在已占用的区间内就跳过——
    否则"卷积神经网络"会连带把"神经网络"也挂一遍，挂靠结果全是噪声。
    """
    entries = build_dict(index)
    matched: list[tuple[int, str, int]] = []
    seen: set[int] = set()
    claimed: list[tuple[int, int]] = []

    for key in sorted(entries, key=len, reverse=True):
        start = norm_text.find(key)
        if start < 0:
            continue
        end = start + len(key)
        if any(span_start <= start and end <= span_end for span_start, span_end in claimed):
            continue
        claimed.append((start, end))

        kp_id = entries[key]
        if kp_id in seen:
            continue
        seen.add(kp_id)
        matched.append((kp_id, key, len(key)))

    return matched


# ------------------------------------------------------------------ 内部工具

def _nodes_by_norm(nodes: Iterable[KpNode]) -> dict[str, KpNode]:
    """归一化键 → 节点。占位节点**不进词典**——它只承接兜底，不该被标签命中。"""
    by_norm: dict[str, KpNode] = {}
    for node in nodes:
        if node.is_placeholder:
            continue
        key = normalize_label(node.name)
        if not key:
            continue
        if key in by_norm:
            # 归一化让两个节点撞车时必须有人看得见，否则是静默错配
            logger.warning(
                "知识点归一化冲突：%r 与 %r 都归一为 %r，后者将被忽略",
                by_norm[key].name,
                node.name,
                key,
            )
            continue
        by_norm[key] = node
    return by_norm


def _placeholder_node(index: KpIndex) -> KpNode | None:
    for node in index.nodes:
        if node.is_placeholder:
            return node
    return None


def _unmatched(raw: str, index: KpIndex, on_unmatched: str) -> MatchResult | None:
    if on_unmatched == ON_UNMATCHED_PLACEHOLDER:
        node = _placeholder_node(index)
        if node is not None:
            return MatchResult(raw, node.id, node.name, METHOD_PLACEHOLDER, 0.0)
        logger.warning("策略为 placeholder 但索引中没有「未归类」节点，降级为未命中")
    return None


def _unmatched_list(raw: str, index: KpIndex, on_unmatched: str) -> list[MatchResult]:
    hit = _unmatched(raw, index, on_unmatched)
    return [hit] if hit is not None else []


def _vector_match(
    raw: str,
    nodes: Sequence[KpNode],
    embed: Callable[[list[str]], list[list[float]]],
) -> MatchResult | None:
    """向量兜底：把待匹配文本与节点名**一次批量编码**后取最大余弦。

    刻意不做进程内缓存。曾按"节点快照"做缓存，但缓存键不含 embedder 身份，
    换一个 embedder（测试里换个假实现）就会拿到上一轮的陈旧向量——
    表现为**跨用例串味**。而向量档按设计是默认关闭、超线才开的兜底路径，
    省这点开销不值得引入一个会静默给错答案的全局可变状态。
    真正的性能要求落在调用方：批量场景必须把文本数组一次传给 `embed`（见 3.2.5 性能约定）。
    """
    pool = [n for n in nodes if not n.is_placeholder]
    if not pool:
        return None

    vectors = embed([raw] + [n.name for n in pool])
    if not vectors or len(vectors) != len(pool) + 1:
        logger.warning("embedder 返回的向量条数与输入不符，跳过向量兜底")
        return None
    query, node_vectors = vectors[0], vectors[1:]

    best_node, best_score = None, 0.0
    for node, vector in zip(pool, node_vectors):
        score = cosine(query, vector)
        if score > best_score:
            best_node, best_score = node, score

    if best_node is not None and best_score >= VECTOR_THRESHOLD:
        return MatchResult(raw, best_node.id, best_node.name, METHOD_VECTOR, best_score)
    return None


# ------------------------------------------------------------------ 读库（唯一一处）

def load_index(db, course: str | None = None) -> KpIndex:
    """从库里读出匹配所需的索引。**只读不写**，是本模块唯一接触数据库的函数。

    `course` 为 None 时取全图——口径放宽以避免把记录挡在门外（见 3.2.5「候选集」）。
    """
    from app.models.learn import KpAlias, KnowledgePoint

    query = db.query(KnowledgePoint)
    if course:
        query = query.filter(KnowledgePoint.course == course)
    rows = query.all()

    nodes = tuple(
        KpNode(id=row.id, name=row.name, is_placeholder=bool(row.is_placeholder)) for row in rows
    )
    placeholder = next((n.id for n in nodes if n.is_placeholder), None)

    aliases = {
        row.norm_label: row.kp_id
        for row in db.query(KpAlias).filter(KpAlias.norm_label.isnot(None)).all()
    }

    return KpIndex(nodes=nodes, aliases=aliases, placeholder_id=placeholder)
