# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 智能备课接口
"""智能备课接口：SSE 流式生成、列表/详情、编辑保存、版本管理与回滚、导出、资源检索。

需求见工单17：教案/课件/习题/案例/试题自动生成 → 在线编辑 → 资源检索引用 → 多格式导出 → 版本回溯。
已确认降级项：不实现多教师协同编辑（WebSocket+Yjs）；"一键推送"降级为导出文件下载。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_teacher
from app.db import SessionLocal, get_db
from app.models.lesson import (
    CONTENT_TYPES,
    ExamQuestion,
    Exercise,
    PlanVersion,
    Resource,
    TeachingPlan,
)
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.lesson import (
    GenerateRequest,
    PlanBrief,
    PlanDetail,
    PlanUpdateRequest,
    ResourceOut,
    ResourceSearchRequest,
    VersionOut,
    loads_or_none,
    plan_to_detail,
)
from app.services import exporter, llm_client, prompts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lesson", tags=["智能备课"])


# ------------------------------------------------------------------ 工具函数

def _sse(event: str, data: dict) -> str:
    """构造一条 SSE 消息。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _make_title(payload: GenerateRequest) -> str:
    parts = [payload.course_name]
    if payload.chapter:
        parts.append(payload.chapter)
    parts.append(payload.content_type)
    return "-".join(parts)


def _get_own_plan(db: Session, plan_id: int, user: User) -> TeachingPlan:
    """取本人备课记录，越权或不存在统一返回 404（不泄露他人资源是否存在）。"""
    plan = db.scalar(
        select(TeachingPlan).where(
            TeachingPlan.id == plan_id, TeachingPlan.owner_id == user.id
        )
    )
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="备课记录不存在")
    return plan


def _save_questions(db: Session, plan: TeachingPlan, items: list[dict], is_exam: bool) -> int:
    """把解析出的题目写入 exercises / exam_questions，供工单19 抽题使用。"""
    model = ExamQuestion if is_exam else Exercise
    count = 0
    for item in items:
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        options = item.get("options")
        row = model(
            plan_id=plan.id,
            qtype=item.get("qtype"),
            stem=stem,
            options_json=json.dumps(options, ensure_ascii=False) if isinstance(options, list) else None,
            answer=str(item.get("answer")) if item.get("answer") is not None else None,
            analysis=item.get("analysis"),
            knowledge_point=item.get("knowledge_point"),
            difficulty=item.get("difficulty"),
        )
        if is_exam:
            try:
                row.score = int(item.get("score") or 0)
            except (TypeError, ValueError):
                row.score = 0
        db.add(row)
        count += 1
    return count


# ------------------------------------------------------------------ SSE 生成

@router.post("/generate", summary="生成备课内容（SSE 流式）")
async def generate(
    payload: GenerateRequest,
    user: User = Depends(require_teacher),
) -> StreamingResponse:
    """流式生成教案/课件/习题/案例/试题。

    SSE 事件：
      - ``delta``  : {"text": "增量文本"}
      - ``done``   : {"plan_id": 1, "version": 1, "title": "...", "question_count": 23}
      - ``error``  : {"msg": "错误原因"}
    """
    try:
        content_type = payload.validate_type()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    messages = prompts.build_messages(
        content_type,
        subject=payload.subject,
        course_name=payload.course_name,
        chapter=payload.chapter,
        knowledge_points=payload.knowledge_points,
        difficulty=payload.difficulty,
        objectives=payload.objectives,
        extra=payload.extra,
    )
    title = _make_title(payload)
    owner_id = user.id

    async def event_stream() -> AsyncIterator[str]:
        chunks: list[str] = []
        yield _sse("start", {"content_type": content_type, "title": title})
        try:
            async for delta in llm_client.chat_stream(messages):
                chunks.append(delta)
                yield _sse("delta", {"text": delta})
        except llm_client.LLMNotConfiguredError as exc:
            yield _sse("error", {"msg": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - 任何供应商异常都要以 SSE 形式告知前端
            logger.exception("LLM 流式生成失败")
            yield _sse("error", {"msg": f"生成失败：{exc}"})
            return

        raw_text = "".join(chunks)

        # 生成结束，落库。使用独立 Session：SSE 响应周期长于请求依赖的生命周期
        db = SessionLocal()
        try:
            parsed = llm_client.extract_json_block(raw_text) if content_type in prompts.JSON_TYPES else None
            content_json = prompts.build_content_payload(content_type, raw_text, parsed)

            plan = TeachingPlan(
                owner_id=owner_id,
                content_type=content_type,
                title=title,
                subject=payload.subject,
                course_name=payload.course_name,
                chapter=payload.chapter,
                knowledge_points=json.dumps(payload.knowledge_points, ensure_ascii=False),
                difficulty=payload.difficulty,
                objectives=json.dumps(payload.objectives, ensure_ascii=False),
                content_json=content_json,
                current_version=1,
            )
            db.add(plan)
            db.flush()

            db.add(
                PlanVersion(
                    plan_id=plan.id,
                    version_no=1,
                    content_json=content_json,
                    created_by=owner_id,
                    remark="AI 首次生成",
                )
            )

            question_count = 0
            if content_type in ("习题", "试题"):
                items = prompts.normalize_items(parsed)
                question_count = _save_questions(db, plan, items, is_exam=(content_type == "试题"))

            db.commit()
            plan_id = plan.id
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("生成结果落库失败")
            yield _sse("error", {"msg": f"内容已生成但保存失败：{exc}"})
            return
        finally:
            db.close()

        yield _sse(
            "done",
            {
                "plan_id": plan_id,
                "version": 1,
                "title": title,
                "question_count": question_count,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证逐字推送
        },
    )


# ------------------------------------------------------------------ 列表 / 详情

@router.get("/plans", response_model=ApiResponse[list[PlanBrief]], summary="备课记录列表")
def list_plans(
    content_type: str | None = Query(default=None, description="按类型筛选"),
    course_name: str | None = Query(default=None, description="按课程名筛选"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[list[PlanBrief]]:
    stmt = select(TeachingPlan).where(TeachingPlan.owner_id == user.id)
    if content_type:
        stmt = stmt.where(TeachingPlan.content_type == content_type)
    if course_name:
        stmt = stmt.where(TeachingPlan.course_name.like(f"%{course_name}%"))
    stmt = stmt.order_by(TeachingPlan.updated_at.desc()).limit(limit).offset(offset)

    rows = db.scalars(stmt).all()
    return ApiResponse.ok([PlanBrief.model_validate(r) for r in rows])


@router.get("/plans/{plan_id}", response_model=ApiResponse[PlanDetail], summary="备课记录详情")
def get_plan(
    plan_id: int,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[PlanDetail]:
    plan = _get_own_plan(db, plan_id, user)
    return ApiResponse.ok(plan_to_detail(plan))


# ------------------------------------------------------------------ 编辑保存

@router.put("/plans/{plan_id}", response_model=ApiResponse[PlanDetail], summary="编辑保存（自动生成新版本）")
def update_plan(
    plan_id: int,
    payload: PlanUpdateRequest,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[PlanDetail]:
    plan = _get_own_plan(db, plan_id, user)

    content = payload.content
    content_json = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

    plan.content_json = content_json
    plan.current_version += 1
    db.add(
        PlanVersion(
            plan_id=plan.id,
            version_no=plan.current_version,
            content_json=content_json,
            created_by=user.id,
            remark=payload.remark or "编辑保存",
        )
    )
    # 编辑后同步刷新题目表，保证工单19 抽到的是最新版本
    if plan.content_type in ("习题", "试题"):
        items = prompts.normalize_items(loads_or_none(content_json))
        if items:
            model = ExamQuestion if plan.content_type == "试题" else Exercise
            db.query(model).filter(model.plan_id == plan.id).delete()
            _save_questions(db, plan, items, is_exam=(plan.content_type == "试题"))

    db.commit()
    db.refresh(plan)
    return ApiResponse.ok(plan_to_detail(plan))


# ------------------------------------------------------------------ 版本管理

@router.get("/plans/{plan_id}/versions", response_model=ApiResponse[list[VersionOut]], summary="版本列表")
def list_versions(
    plan_id: int,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[list[VersionOut]]:
    plan = _get_own_plan(db, plan_id, user)
    rows = db.scalars(
        select(PlanVersion)
        .where(PlanVersion.plan_id == plan.id)
        .order_by(PlanVersion.version_no.desc())
    ).all()
    return ApiResponse.ok([VersionOut.model_validate(r) for r in rows])


@router.post(
    "/plans/{plan_id}/versions/{version_id}/rollback",
    response_model=ApiResponse[PlanDetail],
    summary="回滚到指定版本",
)
def rollback_version(
    plan_id: int,
    version_id: int,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[PlanDetail]:
    """回滚不删除历史：把目标版本内容作为**新版本**追加，保证版本链完整可追溯。"""
    plan = _get_own_plan(db, plan_id, user)
    target = db.scalar(
        select(PlanVersion).where(
            PlanVersion.id == version_id, PlanVersion.plan_id == plan.id
        )
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")

    plan.content_json = target.content_json
    plan.current_version += 1
    db.add(
        PlanVersion(
            plan_id=plan.id,
            version_no=plan.current_version,
            content_json=target.content_json,
            created_by=user.id,
            remark=f"回滚自 v{target.version_no}",
        )
    )
    db.commit()
    db.refresh(plan)
    return ApiResponse.ok(plan_to_detail(plan))


# ------------------------------------------------------------------ 导出

@router.get("/plans/{plan_id}/export", summary="导出 docx / pptx")
def export_plan(
    plan_id: int,
    format: str = Query(default="docx", pattern="^(docx|pptx)$"),
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> Response:
    """导出为文件流。课件导出 pptx，其余导出 docx。"""
    plan = _get_own_plan(db, plan_id, user)

    if format == "pptx" and plan.content_type != "课件":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅课件支持导出为 pptx",
        )

    content = loads_or_none(plan.content_json) or {"raw": "", "items": []}
    subtitle = f"{plan.subject or ''} {plan.course_name} {plan.chapter or ''}".strip()
    data, filename, media_type = exporter.export_plan(
        content, plan.content_type, plan.title or plan.course_name, subtitle
    )
    # 文件名含中文，用 RFC 5987 编码避免乱码
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return Response(content=data, media_type=media_type, headers=headers)


# ------------------------------------------------------------------ 资源检索

@router.post("/resources/search", response_model=ApiResponse[list[ResourceOut]], summary="检索可引用资源")
def search_resources(
    payload: ResourceSearchRequest,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[list[ResourceOut]]:
    """关键词检索校本资源，结果可一键插入正文并标注引用来源。"""
    kw = f"%{payload.keyword}%"
    stmt = (
        select(Resource)
        .where(
            or_(Resource.title.like(kw), Resource.content.like(kw)),
            or_(Resource.is_public.is_(True), Resource.owner_id == user.id),
        )
        .order_by(Resource.created_at.desc())
        .limit(payload.limit)
    )
    rows = db.scalars(stmt).all()
    return ApiResponse.ok([ResourceOut.model_validate(r) for r in rows])


@router.get("/resources", response_model=ApiResponse[list[ResourceOut]], summary="资源列表")
def list_resources(
    limit: int = Query(default=20, ge=1, le=200),
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[list[ResourceOut]]:
    rows = db.scalars(
        select(Resource)
        .where(or_(Resource.is_public.is_(True), Resource.owner_id == user.id))
        .order_by(Resource.created_at.desc())
        .limit(limit)
    ).all()
    return ApiResponse.ok([ResourceOut.model_validate(r) for r in rows])


@router.get("/stats", response_model=ApiResponse[dict], summary="备课数量统计")
def stats(
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    rows = db.execute(
        select(TeachingPlan.content_type, func.count(TeachingPlan.id))
        .where(TeachingPlan.owner_id == user.id)
        .group_by(TeachingPlan.content_type)
    ).all()
    counts = {ct: 0 for ct in CONTENT_TYPES}
    counts.update({ct: n for ct, n in rows})
    return ApiResponse.ok({"by_type": counts, "total": sum(counts.values())})
