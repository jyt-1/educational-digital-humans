# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 数据库 engine / Session
"""SQLAlchemy engine、Session 与 Base。开发期使用 SQLite。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# check_same_thread=False：FastAPI 多线程访问 SQLite 必需
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


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
    """建表。开发期直接 create_all；生产建议改用 Alembic 迁移。"""
    from app import models  # noqa: F401  确保所有模型已注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
