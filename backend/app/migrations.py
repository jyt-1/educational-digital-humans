# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 增量结构迁移
"""工单19 增量结构迁移（幂等，可重复执行）。

**为什么需要迁移**：`Base.metadata.create_all()` 只对**缺失的表**发 `CREATE TABLE`，
**不会给已存在的表加列**。工单18 全是新建表所以没撞上这个坑，工单19 是第一个
"给旧表加列"的工单——跳过迁移会得到"模型里有 `kp_id`、库里没有"的状态，
直到查询时才报 `no such column: exercises.kp_id`。

本模块做两件事，都可以重复跑：

1. **建缺失的表**：直接复用 `Base.metadata.create_all()`——它本身幂等，且能让 ORM
   定义与建表语句天然一致，避免手写 DDL 与模型漂移。
2. **给既有表加列 + 补索引**：`create_all` 做不到的部分，用 `PRAGMA table_info`
   判存在性后逐个 `ALTER TABLE ... ADD COLUMN`。

**触发方式**：`app.db.init_db()` 会调用 `run()`，因此**启动服务或跑 pytest 时已自动完成迁移**，
不存在"忘了跑迁移"的失败模式。`backend/scripts/migrate_w19.py` 是同一逻辑的 CLI 入口，
供排查与 CI 单独调用。这一点比设计文档 3.3.3 的原始表述更强：文档只要求"提供独立脚本"，
实现上让启动路径自动执行，避免顺序依赖变成人工纪律。
"""

from __future__ import annotations

from sqlalchemy import Engine

from app.db import Base, engine

# 给**既有表**新增的列。元组含义：(表, 列, 列定义, 该列需要的索引 DDL)
#
# 取值范围受 SQLite 的 ADD COLUMN 限制：不允许 PRIMARY KEY / UNIQUE 约束；
# 若带 REFERENCES 子句，默认值必须是 NULL（所以 kp_id 可空且无默认值）。
# 另外外键约束已开启（见 app/db.py），带 REFERENCES 的加列会真正校验父行存在。
_ADDED_COLUMNS: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "exercises",
        "kp_id",
        "kp_id INTEGER REFERENCES knowledge_points(id)",
        "CREATE INDEX IF NOT EXISTS idx_exercises_kpid ON exercises(kp_id)",
    ),
    (
        "exam_questions",
        "kp_id",
        "kp_id INTEGER REFERENCES knowledge_points(id)",
        "CREATE INDEX IF NOT EXISTS idx_exam_kpid ON exam_questions(kp_id)",
    ),
)


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _table_exists(conn, table: str) -> bool:
    row = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:name",
        {"name": table},
    ).fetchone()
    return row is not None


def run(target: Engine | None = None) -> list[str]:
    """执行迁移，返回本次实际改动的清单（仅含 create_all 一行 = 已是最新，未改结构）。"""
    from app import models  # noqa: F401  确保所有模型已注册到 Base.metadata

    bind = target if target is not None else engine
    table_count = len(Base.metadata.tables)

    # ① 建缺失的表（工单19 的 10 张新表在这里创建；已存在的表被跳过）
    Base.metadata.create_all(bind=bind)
    applied: list[str] = [f"create_all: 已确保 {table_count} 张表存在（其中工单19 新表 10 张）"]

    # ② 给既有表加列
    with bind.begin() as conn:
        for table, column, column_ddl, index_ddl in _ADDED_COLUMNS:
            if not _table_exists(conn, table):
                # 全新库：表由 create_all 依模型建出，kp_id 已含在内，无需 ALTER
                continue
            if column in _existing_columns(conn, table):
                continue

            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column_ddl}")
            applied.append(f"ALTER {table} ADD COLUMN {column}")

            if index_ddl:
                conn.exec_driver_sql(index_ddl)
                applied.append(f"INDEX {table}({column})")

    return applied
