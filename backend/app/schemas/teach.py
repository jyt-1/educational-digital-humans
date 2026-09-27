# [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 班级接口的请求/响应模型
"""班级接口的 Pydantic 模型（设计文档 3.2.2 第(5)组）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="班级名称")
    course_name: str = Field(min_length=1, max_length=128, description="课程名称")


class MemberAddRequest(BaseModel):
    """按 username 加人。

    为什么不是 student_id：教师手上只有名单，没有数据库主键。让他先查 id 再加人，
    等于把内部标识泄漏到使用流程里。
    """

    usernames: list[str] = Field(min_length=1, max_length=200, description="学生登录名列表")


class MemberRow(BaseModel):
    """逐行结果。照 `profile/import` 的先例：不因一行失败整批回滚。"""

    username: str
    ok: bool
    student_id: int | None = None
    display_name: str | None = None
    reason: str | None = None


class MemberAddResponse(BaseModel):
    items: list[MemberRow]
    added: int
    failed: int


class StudentRow(BaseModel):
    student_id: int
    username: str
    display_name: str | None = None
    kp_count: int = Field(default=0, description="该生有证据的知识点数")
    weak_count: int = Field(default=0, description="其中低于达标线的条数")
