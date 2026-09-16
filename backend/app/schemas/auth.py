# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 认证相关 Pydantic 模型
"""认证接口的请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import VALID_ROLES


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, description="登录名")
    password: str = Field(min_length=6, max_length=128, description="密码，仅存哈希")
    role: str = Field(default="student", description="角色：teacher | student")
    display_name: str | None = Field(default=None, max_length=64, description="显示名")

    def validated_role(self) -> str:
        if self.role not in VALID_ROLES:
            raise ValueError(f"角色必须是 {'/'.join(VALID_ROLES)} 之一")
        return self.role


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    display_name: str | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
