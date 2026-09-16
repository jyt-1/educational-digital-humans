# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 认证接口
"""认证与权限接口：注册 / 登录 / 当前用户。跨工单基础模块。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_db
from app.models.user import ROLE_STUDENT, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=ApiResponse[UserOut], summary="注册")
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> ApiResponse[UserOut]:
    try:
        role = payload.validated_role()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=role or ROLE_STUDENT,
        display_name=payload.display_name or payload.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ApiResponse.ok(UserOut.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenResponse], summary="登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> ApiResponse[TokenResponse]:
    user = db.scalar(select(User).where(User.username == payload.username))
    # 用户不存在与密码错误返回同一提示，避免账号枚举
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    token = create_access_token(user)
    return ApiResponse.ok(
        TokenResponse(access_token=token, user=UserOut.model_validate(user))
    )


@router.get("/me", response_model=ApiResponse[UserOut], summary="获取当前用户")
def me(user: User = Depends(get_current_user)) -> ApiResponse[UserOut]:
    return ApiResponse.ok(UserOut.model_validate(user))
