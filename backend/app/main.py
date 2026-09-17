# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— FastAPI 应用入口
"""FastAPI 入口：挂载 CORS（前端 5173）、注册路由、建表、统一异常响应。

启动：cd backend && uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import assistant as assistant_api
from app.api import auth as auth_api
from app.api import kb as kb_api
from app.api import learn as learn_api
from app.api import lesson as lesson_api
from app.config import settings
from app.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info("数据库已就绪：%s", settings.database_url)
    if not settings.LLM_API_KEY or settings.LLM_API_KEY.startswith("sk-xxx"):
        logger.warning("未配置 LLM_API_KEY，生成类接口调用时会返回明确错误提示")
    yield


app = FastAPI(
    title="教育智能体平台 · 阶段一",
    description="工单16~19：智能备课 / 智能助教 / 个性化学习推荐（工单20 面试AI复盘已移出本期）",
    version="0.1.0",
    lifespan=lifespan,
)

# 前端开发期跨域（Vite 默认 5173）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------ 统一异常响应
# 成功响应由各接口返回 ApiResponse（{code,msg,data}）；
# 异常统一在此转换为同结构，前端拦截器只需处理一种格式。

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "msg": str(exc.detail), "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    msg = f"参数校验失败：{loc} {first.get('msg', '')}".strip()
    return JSONResponse(
        status_code=422,
        content={"code": 422, "msg": msg, "data": None},
    )


# ------------------------------------------------------------ 路由注册
app.include_router(auth_api.router)
app.include_router(lesson_api.router)
app.include_router(kb_api.router)
app.include_router(assistant_api.router)
app.include_router(learn_api.router)


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "status": "ok",
            "llm_configured": bool(
                settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("sk-xxx")
            ),
            "model": settings.LLM_MODEL,
        },
    }
