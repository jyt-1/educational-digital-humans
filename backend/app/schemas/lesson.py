# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 备课相关 Pydantic 模型
"""智能备课接口的请求/响应模型。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.lesson import CONTENT_TYPES


class GenerateRequest(BaseModel):
    """生成请求。入参按工单要求：学科 / 课程 / 知识点 / 难度。"""

    content_type: str = Field(description="教案 | 课件 | 习题 | 案例 | 试题")
    course_name: str = Field(min_length=1, max_length=128, description="课程名")
    subject: str | None = Field(default=None, max_length=64, description="学科/专业")
    chapter: str | None = Field(default=None, max_length=128, description="章节")
    knowledge_points: list[str] = Field(default_factory=list, description="知识点列表")
    difficulty: str | None = Field(default=None, max_length=16, description="难度：简单|中等|困难")
    objectives: list[str] = Field(default_factory=list, description="教学目标列表")
    extra: str | None = Field(default=None, max_length=500, description="补充要求")

    def validate_type(self) -> str:
        if self.content_type not in CONTENT_TYPES:
            raise ValueError(f"content_type 必须是 {'/'.join(CONTENT_TYPES)} 之一")
        return self.content_type


class PlanUpdateRequest(BaseModel):
    """编辑保存。content 为新的结构化内容；传 remark 便于版本回溯时识别。"""

    content: dict[str, Any] | list[Any] | str = Field(description="编辑后的内容")
    remark: str | None = Field(default=None, max_length=255)


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_no: int
    remark: str | None = None
    created_by: int | None = None
    created_at: datetime


class PlanBrief(BaseModel):
    """列表项，不含完整内容。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: str
    title: str | None = None
    subject: str | None = None
    course_name: str
    chapter: str | None = None
    difficulty: str | None = None
    current_version: int
    created_at: datetime
    updated_at: datetime


class PlanDetail(BaseModel):
    """详情，含完整结构化内容。"""

    id: int
    owner_id: int
    content_type: str
    title: str | None = None
    subject: str | None = None
    course_name: str
    chapter: str | None = None
    knowledge_points: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    objectives: list[str] = Field(default_factory=list)
    content: Any = None
    current_version: int
    created_at: datetime
    updated_at: datetime


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source: str | None = None
    content: str | None = None
    doc_id: int | None = None
    is_public: bool = True


class ResourceSearchRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=5, ge=1, le=50)


def loads_or_none(raw: str | None) -> Any:
    """安全的 JSON 反序列化，脏数据不抛异常。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def plan_to_detail(plan) -> PlanDetail:
    """ORM -> PlanDetail，负责 JSON 字段的反序列化。"""
    return PlanDetail(
        id=plan.id,
        owner_id=plan.owner_id,
        content_type=plan.content_type,
        title=plan.title,
        subject=plan.subject,
        course_name=plan.course_name,
        chapter=plan.chapter,
        knowledge_points=loads_or_none(plan.knowledge_points) or [],
        difficulty=plan.difficulty,
        objectives=loads_or_none(plan.objectives) or [],
        content=loads_or_none(plan.content_json),
        current_version=plan.current_version,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )
