# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— ORM 模型
"""工单19 个性化学习推荐：知识图谱、统一题库、答题记录、画像、错题本与四张辅助表。

DDL 与 `docs/设计文档-工单16.md` 3.3.2 逐列对齐。两点须留意：

1. **`questions` 是统一题库，不是工单17 的表**——它由 `/api/learn/kp/sync?target=questions`
   从工单17 的 `exercises` / `exam_questions` **汇入**并挂 `kp_id`。工单17 自身不写本表。
2. **`student_profile.mastery` 是纯缓存**。权威来源为实时计算（`attempts` ∪ `score_imports`），
   缓存缺失或过期时必须实时兜底重算，不得返回空画像（见 3.3.3）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# 难度三档：questions / practice_state 与汇入侧的归一化映射共用同一口径（设计文档 3.2.6）
DIFFICULTY_EASY = "简单"
DIFFICULTY_MEDIUM = "中等"
DIFFICULTY_HARD = "困难"
DIFFICULTIES = (DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD)
DIFFICULTY_CHECK = "difficulty IN ('简单','中等','困难')"

# 统一题库的来源标记，与 kp_alias.source 的取值口径对齐
SOURCE_EXERCISE = "exercise"
SOURCE_EXAM = "exam"
SOURCE_SCORE_IMPORT = "score_import"
SOURCE_MESSAGE = "message"
SOURCE_MANUAL = "manual"

# 错题本的 AIGC 分析状态
ANALYZE_PENDING = "pending"
ANALYZE_ANALYZING = "analyzing"
ANALYZE_DONE = "done"
ANALYZE_FAILED = "failed"
ANALYZE_STATUSES = (ANALYZE_PENDING, ANALYZE_ANALYZING, ANALYZE_DONE, ANALYZE_FAILED)

# 全库唯一的「未归类」占位节点名（匹配不上的题目挂这里，而不是自动新建节点，见 3.2.5）
PLACEHOLDER_KP_NAME = "未归类"


class KnowledgePoint(Base):
    """知识点。`prereq_id` 自关联构成课程知识图谱（如 矩阵运算→神经网络→反向传播→梯度下降）。"""

    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course: Mapped[str] = mapped_column(String(128), nullable=False, default="人工智能导论")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    prereq_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True, index=True
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON 数组：该知识点「预设的常见错误类型」（工单19 原文要求的 Prompt 输入之一）。
    # seed 只对 5~8 个高频知识点预置，其余留空由 LLM 分析时先推断再归因，见设计文档 3.2.7
    common_misconceptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 1 = 「未归类」占位节点。部分唯一索引保证全库至多一条，
    # 这样「题目一条不丢」与「图谱一个不脏」可以同时成立
    is_placeholder: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("course", "name", name="uq_kp_course_name"),
        Index(
            "idx_kp_placeholder",
            "is_placeholder",
            unique=True,
            sqlite_where=text("is_placeholder = 1"),
        ),
    )


class Question(Base):
    """统一题库。由工单17 的 `exercises` / `exam_questions` 汇入，供练习与试卷抽题。"""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kp_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True, index=True
    )
    qtype: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DIFFICULTY_MEDIUM
    )
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # exercise | exam
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(DIFFICULTY_CHECK, name="ck_questions_difficulty"),
        Index("idx_q_kp", "kp_id", "difficulty"),
        # 幂等键：/kp/sync?target=questions 可重跑的前提，否则每跑一次题库翻一倍。
        # 用部分索引而非 NOT NULL，是为将来可能出现的「无来源行的手工题」留口子
        Index(
            "idx_q_source",
            "source",
            "source_id",
            unique=True,
            sqlite_where=text("source_id IS NOT NULL"),
        ),
    )


class Attempt(Base):
    """答题记录。画像计算的原始素材，区分练习 / 变式题 / 试卷三种形态。"""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    kp_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True
    )
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_variant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 试卷模式作答。考试是「测量」、练习是「训练」——故试卷不计入 practice_state 难度档
    is_exam: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_attempts_stu", "student_id", "kp_id", "created_at"),)


class StudentProfile(Base):
    """学生画像（按知识点存掌握度）。**纯缓存**，可随时由 `attempts` ∪ `score_imports` 重建。"""

    __tablename__ = "student_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    kp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    mastery: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0~1
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("student_id", "kp_id", name="uq_profile_student_kp"),)


class MistakeBook(Base):
    """错题本。答错触发 AIGC 分析（解析 + 归因 + 2~3 道变式题），变式题可再答、再错重新分析。"""

    __tablename__ = "mistake_book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("attempts.id"), nullable=True
    )
    kp_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True
    )
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON：解析 + 错误原因诊断
    variant_questions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON：变式题数组
    analyze_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ANALYZE_PENDING
    )
    variant_tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "analyze_status IN ('pending','analyzing','done','failed')",
            name="ck_mistake_analyze_status",
        ),
        Index("idx_mistake_stu", "student_id", "kp_id"),
    )


class PracticeState(Base):
    """自适应练习的难度档状态。连对 3 题升档、答错降档；试卷模式不动本表。"""

    __tablename__ = "practice_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    kp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default=DIFFICULTY_EASY)
    streak_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(DIFFICULTY_CHECK, name="ck_practice_state_difficulty"),
        UniqueConstraint("student_id", "kp_id", name="uq_practice_student_kp"),
    )


class KpAlias(Base):
    """知识点别名：匹配失败标签的落点 + 自学习载体。「待归并清单」即本表的查询结果。"""

    __tablename__ = "kp_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_label: Mapped[str] = mapped_column(String(128), nullable=False)  # LLM 或人工填的原始标签
    norm_label: Mapped[str] = mapped_column(String(128), nullable=False)  # 归一化后（见 3.2.5）
    kp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # 一个标签只映射到一个知识点；教师改判走 UPSERT 覆盖，不是新增一行
        UniqueConstraint("norm_label", name="uq_kpalias_norm_label"),
    )


class ScoreImport(Base):
    """历史成绩导入：**知识点级**粒度，独立于 `attempts`（单题级）。

    混进 `attempts` 会让 `question_id` 为空的假记录污染错题本与难度统计，
    且没有 `batch_id` 就无法整批撤销。画像计算时同时读本表与 `attempts`。
    """

    __tablename__ = "score_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)  # 一次导入一个批次
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    kp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    raw_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("score >= 0", name="ck_scoreimp_score_nonneg"),
        CheckConstraint("total > 0", name="ck_scoreimp_total_positive"),  # 防 score/total 除零
        Index("idx_scoreimp_batch", "batch_id"),
    )


class KpFaq(Base):
    """助教高频问题种子库：冷启动用；真实高频由 `source='user'` 累计而来。"""

    __tablename__ = "kp_faq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(512), nullable=False)
    ask_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        # 保证 /kp/sync?target=faq 可重跑：重复问题 UPSERT 覆盖而非重复插入
        UniqueConstraint("kp_id", "question", name="uq_kpfaq_kp_question"),
        Index("idx_kpfaq_kp", "kp_id", "ask_count"),
    )


class MessageKp(Base):
    """消息↔知识点中间表。单独成表是为了**不改动工单18 已交付的 `messages` 表**；一条消息可挂多个知识点。"""

    __tablename__ = "message_kp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # dict | vector | manual
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("message_id", "kp_id", name="uq_msgkp_message_kp"),)
