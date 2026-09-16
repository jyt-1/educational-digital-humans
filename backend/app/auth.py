# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— JWT 认证与角色权限
"""认证与授权：密码哈希（bcrypt）、JWT 签发校验、当前用户依赖注入、角色校验。

跨工单基础模块：工单18 私有知识库隔离、工单19 student_id、工单20 上报人均复用本模块。
安全要求见设计文档 5.1 节：密码仅存哈希；所有个人数据查询强制附加 user_id 过滤。
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import ROLE_ADMIN, User

# bcrypt 算法本身只取前 72 字节，超长密码需先截断，否则新版 bcrypt 会直接抛错
_BCRYPT_MAX_BYTES = 72

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """生成密码哈希。仅存哈希，禁止明文或可逆加密存储。"""
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。哈希格式非法时返回 False，不抛异常。"""
    try:
        raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    """签发 JWT。有效期由 .env 的 JWT_EXPIRE_MINUTES 控制。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析 JWT，失败抛出 401。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录"
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证"
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI 依赖：从 Authorization: Bearer <token> 解析当前用户。"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供登录凭证"
        )
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证")

    user = db.scalar(select(User).where(User.id == int(user_id)))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def require_role(*roles: str):
    """生成一个角色校验依赖，例如 Depends(require_role(ROLE_TEACHER))。"""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles and user.role != ROLE_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {'/'.join(roles)} 角色权限",
            )
        return user

    return _checker


# 常用依赖别名
require_teacher = require_role("teacher")
require_student = require_role("student")
