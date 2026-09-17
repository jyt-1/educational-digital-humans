# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 混合检索
"""混合检索：向量召回 + 关键词（BM25）召回 → RRF 融合 → 可选云端重排 → top-k 带引用。

工单18 明确要求：「检索时，分别从个人知识库和公共知识库进行混合检索，并对检索结果
进行重排序，返回最优的检索结果」。对应实现：

1. **分别召回**：公共库 collection ``public`` 与当前用户私有库 collection ``u_{uid}``
   各召回一批（私有库物理隔离，绝无串库可能）；
2. **混合**：向量召回捕捉语义、BM25 捕捉术语与编号（如「第三章」「ReLU」），
   两路结果用 RRF（倒数排名融合）合并——对分数量纲不敏感，工程上最稳；
3. **重排**：``RERANK_ENABLED=true`` 时调云端 reranker 精排，失败自动降级（见 rerank.py）；
4. **引用**：返回块的 文件名 / 页码 / 块类型 / 图片路径，供答案角标与原文回显。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.assistant import (
    PARSE_DONE,
    SCOPE_PRIVATE,
    SCOPE_PUBLIC,
    KbChunk,
    KbDoc,
)
from app.models.user import User
from app.services import embedding, rerank, vector_store

logger = logging.getLogger(__name__)

# 每路召回的候选数（融合前），最终返回 KB_TOP_K 条
_RECALL_K = 12
# RRF 平滑常数（经验值 60，来自 RRF 原论文）
_RRF_K = 60

# BM25 索引缓存：key=collection 名，value=(版本号, 索引)
_index_cache: dict[str, tuple[int, "_Bm25Index"]] = {}
_cache_version = 0
_cache_lock = threading.Lock()


@dataclass
class Hit:
    """一条检索结果（含引用所需全部元数据）。"""

    chunk_id: int
    doc_id: int
    chunk_index: int
    chunk_type: str
    content: str
    filename: str
    scope: str
    page_no: int | None = None
    image_path: str | None = None
    score: float = 0.0
    matched_by: list[str] = field(default_factory=list)

    def to_citation(self, index: int) -> dict[str, Any]:
        """转成前端引用卡片结构（index 为答案里的 [n] 角标序号）。"""
        return {
            "index": index,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "filename": self.filename,
            "page_no": self.page_no,
            "chunk_type": self.chunk_type,
            "scope": self.scope,
            "snippet": self.content[:400],
            "image_url": f"/api/kb/chunks/{self.chunk_id}/image" if self.chunk_type == "image" else None,
            "score": round(self.score, 4),
            "matched_by": self.matched_by,
        }


@dataclass
class _Bm25Index:
    chunk_ids: list[int]
    bm25: BM25Okapi | None


# ------------------------------------------------------------------ 索引缓存

def invalidate_index_cache() -> None:
    """文档入库/删除后调用：让所有 BM25 索引缓存失效，下次检索重建。"""
    global _cache_version
    with _cache_lock:
        _cache_version += 1
        _index_cache.clear()


def _tokenize(text: str) -> list[str]:
    """中文按 jieba 分词，英文/数字转小写，去掉空白与纯标点。"""
    tokens = []
    for token in jieba.lcut(text or ""):
        token = token.strip().lower()
        if token and not token.isspace():
            tokens.append(token)
    return tokens


def _collections_for(user: User, scope: str = "all") -> list[tuple[str, int | None]]:
    """当前用户可检索的库：(collection 名, 私有库 owner_id)。

    ``scope`` 取 all / public / private——前端可限定「只看公共库」或「只看我的私有库」。
    私有库的 collection 名按 user_id 生成，越权隔离在向量库层面即已成立。
    """
    items: list[tuple[str, int | None]] = []
    if scope in ("all", "public"):
        items.append(("public", None))
    if scope in ("all", "private"):
        items.append((vector_store.collection_name(SCOPE_PRIVATE, user.id), user.id))
    return items


def _build_index(db: Session, collection: str, owner_id: int | None) -> _Bm25Index:
    """按可见范围构建 BM25 索引（只索引解析完成的文档）。"""
    stmt = (
        select(KbChunk.id, KbChunk.content)
        .join(KbDoc, KbChunk.doc_id == KbDoc.id)
        .where(KbDoc.parse_status == PARSE_DONE)
    )
    if collection == "public":
        stmt = stmt.where(KbDoc.scope == SCOPE_PUBLIC)
    else:
        stmt = stmt.where(KbDoc.scope == SCOPE_PRIVATE, KbDoc.owner_id == owner_id)

    rows = db.execute(stmt).all()
    chunk_ids = [row[0] for row in rows]
    corpus = [_tokenize(row[1]) for row in rows]
    bm25 = None
    if corpus and any(corpus):
        try:
            bm25 = BM25Okapi(corpus)
        except Exception as exc:  # noqa: BLE001 - 语料异常时降级为纯向量召回
            logger.warning("BM25 索引构建失败，降级为纯向量召回：%s", exc)
    return _Bm25Index(chunk_ids=chunk_ids, bm25=bm25)


def _get_index(db: Session, collection: str, owner_id: int | None) -> _Bm25Index:
    with _cache_lock:
        cached = _index_cache.get(collection)
        if cached and cached[0] == _cache_version:
            return cached[1]
    index = _build_index(db, collection, owner_id)
    with _cache_lock:
        _index_cache[collection] = (_cache_version, index)
    return index


def _keyword_recall(db: Session, collection: str, owner_id: int | None, question: str) -> list[int]:
    """BM25 关键词召回，返回按得分降序的 chunk_id 列表。"""
    index = _get_index(db, collection, owner_id)
    if index.bm25 is None or not index.chunk_ids:
        return []
    try:
        scores = index.bm25.get_scores(_tokenize(question))
    except Exception as exc:  # noqa: BLE001
        logger.warning("BM25 打分失败：%s", exc)
        return []

    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [index.chunk_ids[i] for i in ranked[:_RECALL_K] if scores[i] > 0]


# ------------------------------------------------------------------ 融合与检索

def _rrf_fuse(rank_lists: list[list[int]]) -> dict[int, float]:
    """RRF 融合：score = Σ 1/(k + rank)。对多路分数量纲不敏感。"""
    fused: dict[int, float] = {}
    for ranked in rank_lists:
        for rank, chunk_id in enumerate(ranked):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
    return fused


async def search(
    db: Session,
    *,
    question: str,
    user: User,
    top_k: int | None = None,
    scope: str = "all",
    use_rerank: bool | None = None,
) -> list[Hit]:
    """混合检索入口。返回 top_k 条命中的块（带引用元数据）。

    :param scope: all / public / private，限定检索范围
    :param use_rerank: None 表示按 .env 的 RERANK_ENABLED 决定
    """
    question = (question or "").strip()
    if not question:
        return []
    top_k = top_k or settings.KB_TOP_K

    collections = _collections_for(user, scope)
    matched_by: dict[int, list[str]] = {}
    rank_lists: list[list[int]] = []

    # ---------- 1) 向量召回（公共库 + 我的私有库分别召回） ----------
    try:
        query_vector = await embedding.embed_query(question)
    except embedding.EmbeddingNotConfiguredError:
        raise
    except Exception as exc:  # noqa: BLE001 - 向量服务异常时仍有 BM25 可用
        logger.warning("查询向量化失败，降级为纯关键词召回：%s", exc)
        query_vector = None

    if query_vector is not None:
        for collection, _owner in collections:
            hits = vector_store.query_similar(
                collection=collection, embedding=query_vector, n_results=_RECALL_K
            )
            ranked: list[int] = []
            for hit in hits:
                chunk_id = int(hit.get("chunk_id") or 0)
                if chunk_id <= 0:
                    continue
                ranked.append(chunk_id)
                matched_by.setdefault(chunk_id, []).append("vector")
            if ranked:
                rank_lists.append(ranked)

    # ---------- 2) 关键词召回（BM25，中文分词） ----------
    for collection, owner_id in collections:
        ranked = _keyword_recall(db, collection, owner_id, question)
        for chunk_id in ranked:
            matched_by.setdefault(chunk_id, []).append("keyword")
        if ranked:
            rank_lists.append(ranked)

    if not rank_lists:
        return []

    # ---------- 3) RRF 融合 ----------
    fused = _rrf_fuse(rank_lists)
    ordered_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)
    candidate_ids = ordered_ids[: max(top_k * 4, 12)]

    rows = db.execute(
        select(KbChunk, KbDoc.filename, KbDoc.scope)
        .join(KbDoc, KbChunk.doc_id == KbDoc.id)
        .where(KbChunk.id.in_(candidate_ids))
    ).all()
    by_id = {chunk.id: (chunk, filename, scope) for chunk, filename, scope in rows}

    hits: list[Hit] = []
    for chunk_id in candidate_ids:
        found = by_id.get(chunk_id)
        if not found:
            continue
        chunk, filename, scope = found
        hits.append(
            Hit(
                chunk_id=chunk.id,
                doc_id=chunk.doc_id,
                chunk_index=chunk.chunk_index,
                chunk_type=chunk.chunk_type,
                content=chunk.content or "",
                filename=filename,
                scope=scope,
                page_no=chunk.page_no,
                image_path=chunk.image_path,
                score=fused[chunk_id],
                matched_by=sorted(set(matched_by.get(chunk_id, []))),
            )
        )

    # ---------- 4) 云端重排（可选，失败自动降级） ----------
    enabled = rerank.is_enabled() if use_rerank is None else use_rerank
    if enabled and len(hits) > 1:
        ranked = await rerank.rerank_documents(
            question, [hit.content for hit in hits], top_n=min(top_k, len(hits))
        )
        if ranked:
            reordered: list[Hit] = []
            for index, score in ranked:
                if 0 <= index < len(hits):
                    hit = hits[index]
                    hit.score = score
                    hit.matched_by = sorted(set(hit.matched_by + ["rerank"]))
                    reordered.append(hit)
            # 未进入重排结果的候选补在后面，保证召回不丢
            picked = {id(hit) for hit in reordered}
            reordered.extend(hit for hit in hits if id(hit) not in picked)
            hits = reordered

    return hits[:top_k]
