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

_local_tokenizer = None
_local_model = None


def active_model_name() -> str:
    """当前生效的向量模型名（用于向量库维度/模型一致性校验）。"""
    if settings.EMBEDDING_PROVIDER.lower() == "local":
        return settings.EMBEDDING_LOCAL_MODEL
    return settings.EMBEDDING_MODEL


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


def _load_local_model():
    """懒加载本地句向量模型，返回 (tokenizer, model)。

    实现说明：**不用 sentence-transformers**。本机（Anaconda base 环境）的
    pandas/sklearn 是 conda 用 NumPy 1.x 编译的，而 `numpy` 已升到 2.5.x，
    sentence-transformers → sklearn → scipy.sparse 一导入就 `numpy.core.multiarray
    failed to import`（CLAUDE.md 第 11 节已知缺口）。transformers + torch 这条链路
    不依赖 sklearn/scipy，能直接跑，于是本地兜底改为手写 CLS 池化。
    """
    global _local_tokenizer, _local_model
    if _local_model is not None:
        return _local_tokenizer, _local_model

    try:
        import torch  # noqa: F401 - 仅确认可用
        from transformers import AutoModel, AutoTokenizer
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingNotConfiguredError(
            f"本地 Embedding 不可用（transformers/torch 导入失败：{exc}）。"
            "请改用 EMBEDDING_PROVIDER=api 并配置 EMBEDDING_API_KEY。"
        ) from exc

    name = settings.EMBEDDING_LOCAL_MODEL
    if any(flag in name.lower() for flag in ("m3", "large", "bge-m3")):
        logger.warning(
            "本地 Embedding 模型 %s 体积大、无 GPU 时很慢，建议改用 bge-small-zh-v1.5", name
        )
    logger.info("加载本地 Embedding 模型：%s（CPU）", name)
    _local_tokenizer = AutoTokenizer.from_pretrained(name)
    model = AutoModel.from_pretrained(name)
    model.eval()
    _local_model = model
    return _local_tokenizer, _local_model


def _embed_local(texts: list[str]) -> list[list[float]]:
    """本地兜底：bge-small-zh-v1.5（CPU，无 GPU 依赖）。

    bge 系列句向量取 [CLS] 位再做 L2 归一化，与官方用法一致；
    归一化后 Chroma 用余弦距离检索等价于内积排序。
    """
    import torch

    tokenizer, model = _load_local_model()
    vectors: list[list[float]] = []
    with torch.no_grad():
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            encoded = tokenizer(
                batch, padding=True, truncation=True, max_length=512, return_tensors="pt"
            )
            hidden = model(**encoded).last_hidden_state[:, 0]
            normalized = torch.nn.functional.normalize(hidden, p=2, dim=1)
            vectors.extend(normalized.tolist())
    logger.info("本地 Embedding 完成：%d 条（模型 %s）", len(vectors), settings.EMBEDDING_LOCAL_MODEL)
    return vectors
