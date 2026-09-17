# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 重排序（云端 API）
"""检索结果重排序：走云端 Rerank API（默认 BAAI/bge-reranker-v2-m3，OpenAI 兼容网关的 /rerank 接口）。

开关与地址全部来自 .env：
- ``RERANK_ENABLED=false`` 时直接跳过（开发期策略，见 CLAUDE.md 第 5 节）；
- 开启后若网关不可用/超时，**自动降级**为混合检索的 RRF 顺序并在日志中告警，
  绝不因为重排服务抖动导致问答不可用。
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0


def is_enabled() -> bool:
    """重排是否可用：开关打开 + 已配置地址与 Key。"""
    if not settings.RERANK_ENABLED:
        return False
    if not settings.RERANK_BASE_URL:
        return False
    key = settings.RERANK_API_KEY or ""
    return bool(key) and not key.startswith("sk-xxx")


async def rerank_documents(
    query: str,
    documents: list[str],
    *,
    top_n: int | None = None,
) -> list[tuple[int, float]] | None:
    """对候选文档重排，返回 [(原始下标, 相关度得分)]（按得分降序）。

    不可用或调用失败时返回 ``None``，由调用方沿用原顺序。
    """
    if not is_enabled() or not documents:
        return None

    url = settings.RERANK_BASE_URL.rstrip("/") + "/rerank"
    payload = {
        "model": settings.RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n or len(documents),
        "return_documents": False,
    }
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.RERANK_API_KEY}"},
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001 - 重排是增强项，任何异常都降级
        logger.warning("重排序调用失败，已降级为混合检索顺序：%s", exc)
        return None

    results = data.get("results") or data.get("data") or []
    ranked: list[tuple[int, float]] = []
    for item in results:
        index = item.get("index")
        if index is None:
            continue
        score = item.get("relevance_score", item.get("score", 0.0))
        ranked.append((int(index), float(score)))
    if not ranked:
        logger.warning("重排序返回结果为空，已降级为混合检索顺序")
        return None
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    logger.info("重排序完成：%d 条候选（模型 %s）", len(ranked), settings.RERANK_MODEL)
    return ranked
