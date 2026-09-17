# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— Embedding 统一封装
"""文本向量化：默认走云端 API（硅基流动 BAAI/bge-m3 等 OpenAI 兼容接口），
离线兜底走本地 bge-small-zh-v1.5（CPU 可跑）。

策略见 CLAUDE.md 第 5 节：开发机无独立显卡，主路径用云端 Embedding，
本地模型仅作离线兜底；模型名与 base_url 一律读 .env，代码中不得硬编码。
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# 单次请求的文本条数（bge-m3 类接口对单请求条数有限制，分批更稳）
_BATCH_SIZE = 16
_REQUEST_TIMEOUT = 90.0

_local_model = None


class EmbeddingNotConfiguredError(RuntimeError):
    """未配置 Embedding 时抛出，便于接口层给出可读提示。"""


def _client() -> AsyncOpenAI:
    if not settings.EMBEDDING_API_KEY or settings.EMBEDDING_API_KEY.startswith("sk-xxx"):
        raise EmbeddingNotConfiguredError(
            "未配置 Embedding API Key。请在 .env 中填入 EMBEDDING_API_KEY（硅基流动等），"
            "或把 EMBEDDING_PROVIDER 改为 local 使用本地模型。"
        )
    return AsyncOpenAI(
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL or None,
        timeout=_REQUEST_TIMEOUT,
    )


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。返回顺序与入参一一对应。"""
    if not texts:
        return []
    # 空串会被部分向量接口拒收，统一替换为空格
    payload = [text if text and text.strip() else " " for text in texts]

    if settings.EMBEDDING_PROVIDER.lower() == "local":
        return _embed_local(payload)

    client = _client()
    vectors: list[list[float]] = []
    for start in range(0, len(payload), _BATCH_SIZE):
        batch = payload[start : start + _BATCH_SIZE]
        response = await client.embeddings.create(model=settings.EMBEDDING_MODEL, input=batch)
        # 部分供应商不保证返回顺序，按 index 排序后取
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend([item.embedding for item in ordered])
    logger.info("Embedding 完成：%d 条（模型 %s）", len(vectors), settings.EMBEDDING_MODEL)
    return vectors


async def embed_query(text: str) -> list[float]:
    """单条查询向量化。"""
    vectors = await embed_texts([text])
    if not vectors:
        raise ValueError("查询内容为空，无法向量化")
    return vectors[0]


def _embed_local(texts: list[str]) -> list[list[float]]:
    """本地兜底：bge-small-zh-v1.5。

    注意：本机 sentence-transformers 目前因 numpy 2.x 扩展冲突不可用
    （CLAUDE.md 第 11 节已知缺口），此路径仅在主路径不可用时启用。
    """
    global _local_model
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingNotConfiguredError(
            "本地 Embedding 不可用（sentence-transformers 导入失败，参见 CLAUDE.md 第 11 节）。"
            "请改用 EMBEDDING_PROVIDER=api。"
        ) from exc

    if _local_model is None:
        logger.info("加载本地 Embedding 模型：%s", settings.EMBEDDING_MODEL)
        _local_model = SentenceTransformer(settings.EMBEDDING_MODEL)
    vectors = _local_model.encode(texts, normalize_embeddings=True)
    return [list(map(float, vec)) for vec in vectors]
