# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 智能问答接口
"""智能助教问答接口：SSE 流式返回，答案内嵌 [n] 角标，并随答案下发引用来源。

事件流（前端按事件名消费）：
    sources → {"conversation_id": 1, "citations": [...], "rerank_enabled": false}
    delta   → {"text": "增量文本"}
    done    → {"conversation_id": 1, "message_id": 9, "title": "..."}
    error   → {"msg": "错误原因"}

会话与消息按 user_id 隔离，任何越权访问都返回 404/403（设计文档 5.1 节）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import SessionLocal, get_db
from app.models.assistant import Conversation, Message
from app.models.user import User
from app.schemas.assistant import (
    ChatRequest,
    CitationOut,
    ConversationDetail,
    ConversationOut,
    MessageOut,
    loads_citations,
)
from app.schemas.common import ApiResponse
from app.services import assistant as assistant_service
from app.services import embedding, llm_client, rerank, retriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["智能助教·问答"])

# 多轮对话带入模型的历史消息条数（太多会稀释本次检索资料）
_HISTORY_LIMIT = 6


def _sse(event: str, data: dict) -> str:
    """构造一条 SSE 消息（与工单17 生成接口保持同一格式）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_own_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conversation


@router.post("/chat", summary="知识库问答（SSE 流式，带引用）")
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    conversation_id = payload.conversation_id
    history: list[dict] = []

    if conversation_id is not None:
        conversation = _get_own_conversation(db, conversation_id, user)
        rows = list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.id.desc())
                .limit(_HISTORY_LIMIT)
            ).all()
        )
        history = [{"role": m.role, "content": m.content} for m in reversed(rows)]

    # 检索在流式开始前完成：前端可先渲染引用来源，再逐字接收答案
    try:
        hits = await retriever.search(
            db,
            question=payload.question,
            user=user,
            top_k=payload.top_k,
            scope=payload.scope,
            use_rerank=payload.use_rerank,
        )
    except embedding.EmbeddingNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    citations = [CitationOut(**hit.to_citation(i)) for i, hit in enumerate(hits, start=1)]
    question = payload.question
    user_id = user.id

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            "sources",
            {
                "conversation_id": conversation_id,
                "citations": [item.model_dump() for item in citations],
                "rerank_enabled": bool(
                    payload.use_rerank if payload.use_rerank is not None else rerank.is_enabled()
                ),
            },
        )

        chunks: list[str] = []
        try:
            async for delta in assistant_service.stream_answer(question, hits, history):
                chunks.append(delta)
                yield _sse("delta", {"text": delta})
        except llm_client.LLMNotConfiguredError as exc:
            yield _sse("error", {"msg": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - 任何供应商异常都以 SSE 形式告知前端
            logger.exception("问答流式生成失败")
            yield _sse("error", {"msg": f"回答生成失败：{exc}"})
            return

        answer = "".join(chunks)
        if not answer.strip():
            yield _sse("error", {"msg": "模型未返回内容，请重试或换一种问法"})
            return

        # 落库：独立 Session，SSE 响应周期长于请求依赖的生命周期
        db2 = SessionLocal()
        try:
            conversation = None
            if conversation_id is not None:
                conversation = db2.scalar(
                    select(Conversation).where(
                        Conversation.id == conversation_id, Conversation.user_id == user_id
                    )
                )
            if conversation is None:
                conversation = Conversation(
                    user_id=user_id, title=assistant_service.make_title(question)
                )
                db2.add(conversation)
                db2.flush()

            db2.add(Message(conversation_id=conversation.id, role="user", content=question))
            answer_row = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
                citations_json=json.dumps(
                    [item.model_dump() for item in citations], ensure_ascii=False
                ),
            )
            db2.add(answer_row)
            db2.commit()
            payload_done = {
                "conversation_id": conversation.id,
                "message_id": answer_row.id,
                "title": conversation.title,
            }
        except Exception as exc:  # noqa: BLE001
            db2.rollback()
            logger.exception("问答结果落库失败")
            yield _sse("error", {"msg": f"回答已生成但保存失败：{exc}"})
            return
        finally:
            db2.close()

        yield _sse("done", payload_done)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证逐字推送
        },
    )


@router.get("/conversations", summary="我的会话列表")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[ConversationOut]]:
    counts = dict(
        db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user.id)
            .group_by(Message.conversation_id)
        ).all()
    )
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.id.desc())
            .limit(100)
        ).all()
    )
    return ApiResponse.ok(
        [
            ConversationOut(
                id=item.id,
                title=item.title,
                created_at=item.created_at,
                message_count=int(counts.get(item.id, 0)),
            )
            for item in conversations
        ]
    )


@router.get("/conversations/{conversation_id}", summary="会话详情（含消息与引用）")
def conversation_detail(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ConversationDetail]:
    conversation = _get_own_conversation(db, conversation_id, user)
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id)
        ).all()
    )
    return ApiResponse.ok(
        ConversationDetail(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            message_count=len(rows),
            messages=[
                MessageOut(
                    id=row.id,
                    role=row.role,
                    content=row.content,
                    citations=loads_citations(row.citations_json),
                    created_at=row.created_at,
                )
                for row in rows
            ],
        )
    )


@router.delete("/conversations/{conversation_id}", summary="删除会话")
def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    conversation = _get_own_conversation(db, conversation_id, user)
    db.delete(conversation)
    db.commit()
    return ApiResponse.ok({"conversation_id": conversation_id}, msg="已删除")
