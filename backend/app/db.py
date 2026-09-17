# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 数据库 engine / Session
# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 开启外键约束（前置修复 P0）
"""SQLAlchemy engine、Session 与 Base。开发期使用 SQLite。"""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

# check_same_thread=False：FastAPI 多线程访问 SQLite 必需
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, _connection_record) -> None:
    """每个连接开启 SQLite 外键约束。

    SQLite 默认 ``PRAGMA foreign_keys=0``，即模型里声明的 ``ondelete="CASCADE"``
    **从不生效**——删 kb_docs 不会带走 kb_chunks，删 conversations 不会带走 messages，
    子表会静默留下孤儿行。且该 pragma 是**连接级**的，必须逐连接设置，写进 DDL 没用。

    为什么是工单19 的前置修复：工单19 新增的 10 张表全部靠外键串联
    （attempts→questions、mistake_book→attempts、knowledge_points 自关联先修链），
    孤儿行会直接污染画像与图谱。趁 工单17/18 的表还没有孤儿（已核对全库 0 条）时打开，
    代价最低。

    注意：开启后写入会真正校验父行是否存在，历史上靠"悬空外键"塞进去的数据会开始报错。
    开发和迁移脚本里如遇 ``IntegrityError: FOREIGN KEY constraint failed``，
    多半是数据问题而非约束过严，不要用 `PRAGMA foreign_keys=OFF` 绕过去。
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def foreign_keys_enabled(conn: Engine | None = None) -> bool:
    """当前连接是否已启用外键约束（供自检与用例断言）。"""
    target = conn if conn is not None else engine
    with target.connect() as connection:
        return bool(connection.exec_driver_sql("PRAGMA foreign_keys").scalar())


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 Session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表 + 增量迁移。开发期直接 create_all；生产建议改用 Alembic 迁移。

    注意不能只调 `create_all`：它只建**缺失的表**，不会给已存在的表加列。
    工单19 给 `exercises` / `exam_questions` 加了 `kp_id`，那种改动必须走迁移——
    否则会得到"模型里有、库里没有"的状态，直到查询时才报 `no such column`。
    把迁移放在这里，是为了让"忘了跑迁移"不可能发生（见 app/migrations.py）。
    """
    from app.migrations import run as run_migrations

    for change in run_migrations(engine):
        logger.info("迁移：%s", change)
