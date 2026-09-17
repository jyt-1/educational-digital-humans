# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 向量库封装
"""ChromaDB 向量库：collection 按知识库隔离（设计文档 4.2.3 节「知识库隔离」三重保障之二）。

- 公共库 → collection ``public``
- 私有库 → collection ``u_{user_id}``（按用户物理隔离，检索时不可能串库）
- 第三重保障在接口层：私有文档的读写一律再校验 owner_id。

向量 id 采用 ``{doc_id}:{chunk_index}``，重新解析时先按 doc_id 删除旧向量再写入。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import chromadb

from app.config import settings
from app.models.assistant import SCOPE_PUBLIC
from app.services import embedding

logger = logging.getLogger(__name__)

# 余弦距离：文本语义相似度场景比默认 L2 更合适
_COLLECTION_METADATA = {"hnsw:space": "cosine"}

# 记录向量库是用哪个模型建的：换模型/换供应商后维度不同，Chroma 会报晦涩的维度错误，
# 这里提前挡住并给出「删 data/chroma 重解析」的可操作提示。
_SIGNATURE_FILE = ".embedding_signature.json"
_signature_lock = threading.Lock()

_client: chromadb.ClientAPI | None = None
_client_lock = threading.Lock()


def collection_name(scope: str, owner_id: int | None) -> str:
    """知识库 → collection 名。公共库共用 ``public``，私有库按用户独立。"""
    if scope == SCOPE_PUBLIC or owner_id is None:
        return "public"
    return f"u_{owner_id}"


def get_client() -> chromadb.ClientAPI:
    """进程内单例的 Chroma 持久化客户端（数据落在 data/chroma）。"""
    global _client
    with _client_lock:
        if _client is None:
            _client = chromadb.PersistentClient(
                path=str(settings.chroma_dir),
                settings=chromadb.config.Settings(anonymized_telemetry=False, allow_reset=True),
            )
            logger.info("ChromaDB 已就绪：%s", settings.chroma_dir)
        return _client


def get_collection(name: str):
    """获取或创建 collection。"""
    return get_client().get_or_create_collection(name=name, metadata=_COLLECTION_METADATA)


# ------------------------------------------------------------------ 向量库签名

def _read_signature() -> dict[str, Any] | None:
    path = settings.chroma_dir / _SIGNATURE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_embedding_signature(dimension: int) -> str | None:
    """校验向量库与当前 Embedding 配置是否匹配。

    一致返回 None；不一致返回可读的原因说明（调用方决定是抛错还是降级）。
    """
    model = embedding.active_model_name()
    current = {"model": model, "dim": int(dimension)}
    with _signature_lock:
        saved = _read_signature()
        if saved is None:
            try:
                (settings.chroma_dir / _SIGNATURE_FILE).write_text(
                    json.dumps(current, ensure_ascii=False), encoding="utf-8"
                )
            except OSError as exc:
                logger.warning("写入向量库签名失败：%s", exc)
            return None
    if saved.get("model") == model and int(saved.get("dim") or 0) == int(dimension):
        return None
    return (
        f"向量库当前由「{saved.get('model')}（{saved.get('dim')} 维）」建立，"
        f"而当前 Embedding 配置是「{model}（{dimension} 维）」。"
        "两者不通用，请删除 data/chroma 目录后重新上传/解析文档，"
        "或把 .env 的 Embedding 配置改回原模型。"
    )


def upsert_chunks(
    *,
    doc_id: int,
    scope: str,
    owner_id: int | None,
    filename: str,
    items: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> int:
    """写入向量。``items`` 与 ``embeddings`` 一一对应，每项含 chunk_index/content/chunk_type/page_no。

    返回写入条数。
    """
    if not items:
        return 0
    if len(items) != len(embeddings):
        raise ValueError("向量条数与切块数不一致")

    mismatch = check_embedding_signature(len(embeddings[0]))
    if mismatch:
        # 抛给入库流程，最终落到文档的 parse_error 里，用户能直接在页面上看到原因
        raise RuntimeError(mismatch)

    collection = get_collection(collection_name(scope, owner_id))
    ids = [f"{doc_id}:{item['chunk_index']}" for item in items]
    metadatas = [
        {
            "doc_id": doc_id,
            # chunk_id 是 SQLite 侧主键，向量召回后可直接回表取引用元数据
            "chunk_id": int(item.get("chunk_id") or 0),
            "chunk_index": int(item["chunk_index"]),
            "chunk_type": item.get("chunk_type") or "text",
            "page_no": int(item["page_no"]) if item.get("page_no") is not None else -1,
            "filename": filename,
            "scope": scope,
            "owner_id": int(owner_id) if owner_id is not None else -1,
        }
        for item in items
    ]
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=[item.get("content") or " " for item in items],
        metadatas=metadatas,
    )
    return len(ids)


def delete_doc_vectors(doc_id: int, scope: str, owner_id: int | None) -> None:
    """删除某文档的全部向量（重新解析、删除文档时调用）。"""
    name = collection_name(scope, owner_id)
    try:
        get_collection(name).delete(where={"doc_id": doc_id})
    except Exception as exc:  # noqa: BLE001 - 向量库异常不应阻断业务删除
        logger.warning("删除向量失败（collection=%s, doc_id=%s）：%s", name, doc_id, exc)


def query_similar(
    *,
    collection: str,
    embedding: list[float],
    n_results: int = 10,
) -> list[dict[str, Any]]:
    """向量召回。返回 [{vector_id, doc_id, chunk_index, chunk_type, page_no, filename, distance}]。"""
    if n_results <= 0:
        return []
    mismatch = check_embedding_signature(len(embedding))
    if mismatch:
        logger.warning("向量召回已跳过：%s", mismatch)
        return []
    try:
        store = get_collection(collection)
        if store.count() == 0:
            return []
        result = store.query(
            query_embeddings=[embedding],
            n_results=min(n_results, store.count()),
            include=["metadatas", "distances"],
        )
    except Exception as exc:  # noqa: BLE001 - 向量库不可用时降级为纯关键词召回
        logger.warning("向量召回失败（collection=%s）：%s", collection, exc)
        return []

    ids = (result.get("ids") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hits: list[dict[str, Any]] = []
    for position, vector_id in enumerate(ids):
        meta = metadatas[position] if position < len(metadatas) else {}
        hits.append(
            {
                "vector_id": vector_id,
                "chunk_id": int(meta.get("chunk_id") or 0),
                "doc_id": int(meta.get("doc_id") or 0),
                "chunk_index": int(meta.get("chunk_index") or 0),
                "chunk_type": meta.get("chunk_type") or "text",
                "page_no": None if int(meta.get("page_no", -1)) < 0 else int(meta.get("page_no")),
                "filename": meta.get("filename") or "",
                "distance": float(distances[position]) if position < len(distances) else 1.0,
            }
        )
    return hits


def reset() -> None:
    """清空所有 collection（仅供测试与本地重建使用）。"""
    get_client().reset()
