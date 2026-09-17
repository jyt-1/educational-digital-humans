# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— ORM 模型注册
# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 同文件追加知识库与问答模型
"""集中导入所有 ORM 模型，确保 Base.metadata 完整（init_db 依赖此处的导入）。"""

from app.models.assistant import (
    CHUNK_TYPES,
    SCOPES,
    Conversation,
    KbChunk,
    KbDoc,
    Message,
)
from app.models.lesson import (
    CONTENT_TYPES,
    Courseware,
    ExamQuestion,
    Exercise,
    PlanVersion,
    Resource,
    TeachingPlan,
)
from app.models.user import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER, VALID_ROLES, User

__all__ = [
    "CHUNK_TYPES",
    "CONTENT_TYPES",
    "Conversation",
    "Courseware",
    "KbChunk",
    "KbDoc",
    "Message",
    "SCOPES",
    "ExamQuestion",
    "Exercise",
    "PlanVersion",
    "Resource",
    "ROLE_ADMIN",
    "ROLE_STUDENT",
    "ROLE_TEACHER",
    "TeachingPlan",
    "User",
    "VALID_ROLES",
]
