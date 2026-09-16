# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 统一响应结构
"""统一响应体 {code, msg, data}（设计文档 3.2.2 节）。SSE 与文件下载接口不使用本结构。"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

CODE_OK = 0
CODE_ERROR = 1


class ApiResponse(BaseModel, Generic[T]):
    code: int = CODE_OK
    msg: str = "success"
    data: T | None = None

    @classmethod
    def ok(cls, data: T | None = None, msg: str = "success") -> "ApiResponse[T]":
        return cls(code=CODE_OK, msg=msg, data=data)

    @classmethod
    def fail(cls, msg: str, code: int = CODE_ERROR) -> "ApiResponse[T]":
        return cls(code=code, msg=msg, data=None)
