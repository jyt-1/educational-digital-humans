# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 知识点图谱种子数据
"""工单19 数据 seed：知识图谱 + 占位节点 + 助教问题种子（**只灌数据，不改结构**）。

与 `app/migrations.py` 严格分工：结构走迁移、数据走本脚本。两者幂等条件不同
（判存在性 vs 判数据重复），混在一起就会出现"改结构时顺手插数据、重跑一次数据翻倍"。

幂等做法是**按名判存在**：先查已有节点，只插缺的；先修关系第二遍再挂，
避免"先修知识点还没建"的顺序依赖。重复执行不翻倍。

    cd backend && python -m scripts.seed_learn
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.learn import PLACEHOLDER_KP_NAME, KnowledgePoint, KpFaq  # noqa: E402

COURSE = "人工智能导论"

# 知识图谱：(知识点, 先修知识点, 预设的常见错误类型)
#
# 「先修」构成有向无环图，是路径推荐"沿图谱上溯到最先修薄弱点"的依据。
# 链式关系里含设计文档 3.2.5 点名的示例链：矩阵运算 → 神经网络 → 反向传播 → 梯度下降。
#
# 「预设的常见错误类型」只对高频知识点填（本表共 6 个），其余留空由 LLM 分析时
# 先推断再归因——这正是工单19 原文要求的 Prompt 输入之一，见设计文档 3.2.7。
# 它可空、不做校验：只影响归因针对性，不影响主链路，因此不会成为新的失败点。
KNOWLEDGE_POINTS: tuple[tuple[str, str | None, tuple[str, ...]], ...] = (
    # ---------- 数学与编程基础 ----------
    ("矩阵运算", None, ()),
    ("概率论基础", None, ()),
    ("微积分基础", None, ()),
    ("Python编程基础", None, ()),
    ("数据结构基础", "Python编程基础", ()),
    ("链式法则", "微积分基础", ()),
    # ---------- 机器学习基础 ----------
    ("机器学习概述", "Python编程基础", ()),
    ("监督学习", "机器学习概述", ()),
    ("无监督学习", "机器学习概述", ()),
    ("数据预处理", "Python编程基础", ()),
    ("特征工程", "数据预处理", ()),
    ("模型评估", "监督学习", ()),
    ("过拟合与正则化", "模型评估", (
        "把训练集精度当成模型效果，忽略验证集",
        "认为正则化系数越大越好，导致欠拟合",
        "混淆 L1 与 L2 正则化的作用（稀疏化 vs 权重衰减）",
    )),
    ("交叉验证", "模型评估", ()),
    ("线性回归", "监督学习", ()),
    ("逻辑回归", "线性回归", ()),
    ("决策树", "监督学习", ()),
    ("随机森林", "决策树", ()),
    ("支持向量机", "逻辑回归", ()),
    ("朴素贝叶斯", "概率论基础", ()),
    ("K近邻算法", "监督学习", ()),
    ("聚类分析", "无监督学习", ()),
    ("主成分分析", "矩阵运算", ()),
    ("集成学习", "决策树", ()),
    # ---------- 神经网络与深度学习 ----------
    ("神经元模型", "逻辑回归", ()),
    ("感知机", "神经元模型", ()),
    ("激活函数", "神经元模型", (
        "认为激活函数必须线性，忽略非线性带来的表达能力",
        "混淆 Sigmoid 与 ReLU 的导数范围，误判梯度消失风险",
        "以为 ReLU 在 0 点不可导就不能用于反向传播",
    )),
    ("多层感知机", "感知机", ()),
    ("神经网络", "多层感知机", ()),
    ("前向传播", "神经网络", ()),
    ("损失函数", "神经网络", (
        "回归任务误用交叉熵、分类任务误用均方误差",
        "忽略损失函数与输出层激活函数的搭配（如 Sigmoid + 均方误差）",
        "把损失值大小直接当作模型好坏，忽略不同任务的量纲差异",
    )),
    ("反向传播", "前向传播", (
        "以为反向传播是独立的训练算法，而非求梯度的方式",
        "混淆前向与反向的计算方向，认为梯度从输入层往输出层传",
        "忽略计算图需保存中间结果，误以为反向传播不占额外显存",
    )),
    ("梯度下降", "反向传播", (
        "把学习率当作无关紧要的超参数，忽略它对收敛的影响",
        "认为梯度下降总能找到全局最优，忽略非凸损失面的局部极小",
        "混淆批量梯度下降与随机梯度下降的更新频率",
    )),
    ("学习率", "梯度下降", ()),
    ("随机梯度下降", "梯度下降", ()),
    ("批量梯度下降", "梯度下降", ()),
    ("动量法", "随机梯度下降", ()),
    ("Adam优化器", "随机梯度下降", ()),
    ("权重初始化", "神经网络", ()),
    ("批归一化", "神经网络", ()),
    ("丢弃法", "神经网络", ()),
    # 拆成两个节点而不是合成"梯度消失与梯度爆炸"：复合名会让词典扫描
    # 匹配不上"梯度消失问题""梯度消失的缓解方法"这类真实标签（实测少命中 4 道题）
    ("梯度消失", "反向传播", ()),
    ("梯度爆炸", "反向传播", ()),
    ("计算图", "反向传播", ()),
    ("卷积神经网络", "神经网络", (
        "认为卷积核大小等于感受野大小，忽略层数叠加的效果",
        "混淆卷积与池化的作用，以为池化也能提取特征",
        "忽略通道数变化对参数量与计算量的影响",
    )),
    ("卷积运算", "卷积神经网络", ()),
    ("池化操作", "卷积神经网络", ()),
    ("循环神经网络", "神经网络", ()),
    ("长短期记忆网络", "循环神经网络", ()),
    ("注意力机制", "循环神经网络", (
        "把注意力权重当成可解释的因果依据",
        "混淆自注意力与交叉注意力的查询来源",
        "忽略缩放点积中缩放因子的作用",
    )),
    ("自注意力", "注意力机制", ()),
    ("Transformer架构", "自注意力", ()),
    ("词向量", "神经网络", ()),
    ("预训练语言模型", "Transformer架构", ()),
    ("大语言模型", "预训练语言模型", ()),
    ("提示工程", "大语言模型", ()),
    ("检索增强生成", "大语言模型", ()),
    ("模型微调", "预训练语言模型", ()),
    ("多模态学习", "Transformer架构", ()),
    ("迁移学习", "卷积神经网络", ()),
    ("生成对抗网络", "神经网络", ()),
    ("自编码器", "神经网络", ()),
    ("强化学习", "概率论基础", ()),
    ("智能体", "大语言模型", ()),
    # ---------- 应用与伦理 ----------
    ("计算机视觉", "卷积神经网络", ()),
    ("自然语言处理", "循环神经网络", ()),
    ("语音识别", "循环神经网络", ()),
    ("推荐系统", "机器学习概述", ()),
    ("知识图谱", "自然语言处理", ()),
    ("人工智能伦理", "机器学习概述", ()),
    ("数据隐私保护", "人工智能伦理", ()),
)

# 助教高频问题种子：冷启动用，保证"新学生一句话没问过"时也有东西可推荐
KP_FAQ_SEEDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("反向传播", (
        "反向传播到底在算什么？",
        "为什么反向传播要从输出层往输入层算？",
        "反向传播和梯度下降是什么关系？",
    )),
    ("梯度下降", (
        "梯度下降为什么能降低损失？",
        "学习率太大会怎么样？",
        "批量梯度下降和随机梯度下降怎么选？",
    )),
    ("损失函数", (
        "分类任务为什么用交叉熵而不用均方误差？",
        "损失函数和评价指标是一回事吗？",
    )),
    ("过拟合与正则化", (
        "怎么判断模型是不是过拟合了？",
        "L1 和 L2 正则化有什么区别？",
    )),
    ("卷积神经网络", (
        "卷积核的尺寸该怎么选？",
        "池化层的作用是什么？",
    )),
    ("注意力机制", (
        "自注意力和交叉注意力有什么区别？",
        "为什么要对点积做缩放？",
    )),
    ("Adam优化器", (
        "Adam 优化器适合什么场景？",
        "Adam 还需要手动调学习率吗？",
    )),
    ("激活函数", (
        "为什么需要非线性激活函数？",
        "ReLU 有什么缺点？",
    )),
)


def seed_knowledge_points(db) -> tuple[int, int, int]:
    """建图谱节点。返回 (新增知识点, 新增占位节点, 新挂先修关系) 三个计数。"""
    existing = {
        row.name: row
        for row in db.query(KnowledgePoint).filter(KnowledgePoint.course == COURSE).all()
    }

    # 先修关系名写错时必须立刻炸——静默跳过的结果是图谱缺一条链，
    # 而路径推荐会给出看似合理、实际错误的顺序，验收时很难发现
    known = {name for name, _, _ in KNOWLEDGE_POINTS}
    for name, prereq, _ in KNOWLEDGE_POINTS:
        if prereq is not None and prereq not in known:
            raise ValueError(f"知识点「{name}」的先修「{prereq}」不在清单里")

    added = 0
    for order_no, (name, _prereq, misconceptions) in enumerate(KNOWLEDGE_POINTS):
        if name in existing:
            continue
        db.add(
            KnowledgePoint(
                course=COURSE,
                name=name,
                order_no=order_no,
                common_misconceptions=(
                    json.dumps(list(misconceptions), ensure_ascii=False) if misconceptions else None
                ),
            )
        )
        added += 1
    db.flush()

    # 重新读一遍：新增的节点需要拿到自增 id 才能挂先修关系
    by_name = {
        row.name: row
        for row in db.query(KnowledgePoint).filter(KnowledgePoint.course == COURSE).all()
    }

    linked = 0
    for name, prereq, _ in KNOWLEDGE_POINTS:
        node = by_name[name]
        if prereq is None or node.prereq_id is not None:
            continue
        node.prereq_id = by_name[prereq].id
        linked += 1

    # 全库唯一的「未归类」占位节点：承接匹配不上的题目，而不是自动新建节点
    placeholder_added = 0
    has_placeholder = (
        db.query(KnowledgePoint).filter(KnowledgePoint.is_placeholder == 1).first() is not None
    )
    if not has_placeholder:
        db.add(
            KnowledgePoint(
                course=COURSE,
                name=PLACEHOLDER_KP_NAME,
                order_no=9999,
                is_placeholder=1,
            )
        )
        placeholder_added = 1

    db.commit()
    return added, placeholder_added, linked


def seed_kp_faq(db) -> int:
    """灌助教问题种子。靠 `UNIQUE(kp_id, question)` 保证重复执行不翻倍。"""
    by_name = {row.name: row for row in db.query(KnowledgePoint).all()}
    existing = {(row.kp_id, row.question) for row in db.query(KpFaq).all()}

    added = 0
    for kp_name, questions in KP_FAQ_SEEDS:
        node = by_name.get(kp_name)
        if node is None:
            raise ValueError(f"问题种子指向不存在的知识点「{kp_name}」，请先核对图谱清单")
        for question in questions:
            if (node.id, question) in existing:
                continue
            db.add(KpFaq(kp_id=node.id, question=question, source="seed"))
            added += 1

    db.commit()
    return added


def main() -> None:
    init_db()  # 顺带把结构迁移跑掉，seed 不依赖"你先迁移过"
    db = SessionLocal()
    try:
        kp_added, placeholder_added, linked = seed_knowledge_points(db)
        faq_added = seed_kp_faq(db)

        total = db.query(KnowledgePoint).count()
        print("工单19 数据 seed 完成：")
        print(f"  - 知识点：新增 {kp_added}，库中共 {total} 条（含占位节点 {placeholder_added} 个新增）")
        print(f"  - 先修关系：新挂 {linked} 条")
        print(f"  - 助教问题种子：新增 {faq_added} 条")
        print()
        print("下一步（演示前置步骤）：以教师身份执行一次题库汇入——")
        print("  POST /api/learn/kp/sync?target=questions")
    finally:
        db.close()


if __name__ == "__main__":
    main()
