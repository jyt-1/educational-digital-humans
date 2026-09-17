# [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 测试用例
"""工单18 智能助教 pytest 用例。

覆盖：
- 多模态解析：PDF / DOCX / PPTX / XLSX / 老格式 DOC / 图像（表格转 Markdown、图片抽存路径、公式保留）；
- 切块：约 500 字 + 重叠、表格与图片不切分、超大表格分组重复表头；
- 入库流水线：上传 → 后台解析 → 切块 → 向量 → 状态流转与失败原因；
- 混合检索：向量 + BM25 → RRF 融合、top5 引用元数据、能命中指定页的表格；
- 权限隔离：公共库仅教师可写、私有库按用户物理隔离（三重保障的接口层校验）；
- 问答：SSE 事件流（sources/delta/done）、引用落库、多轮上下文、LLM 未配置的错误提示；
- 降级：重排服务不可用时自动回退混合检索顺序；向量库与 Embedding 配置不一致时拦截并降级为关键词召回。

Embedding 与 LLM 全部 mock，测试不依赖真实 API Key 与网络。
"""

from __future__ import annotations

import io
import json
import math

import fitz
import pytest
from docx import Document as DocxDocument
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from app.config import settings
from app.models.assistant import PARSE_DONE, PARSE_FAILED
from app.services import assistant as assistant_service
from app.services import embedding, llm_client, retriever, vector_store
from app.services.chunking import chunk_blocks
from app.services.parsers import detect_file_type, parse_document
from app.services.parsers.base import ParsedBlock, looks_formula

# ============================================================ Mock：Embedding

_VEC_DIM = 64


def _fake_vector(text: str) -> list[float]:
    """确定性伪向量：按字符码分桶，字面重合度高的文本向量更接近。"""
    vector = [0.0] * _VEC_DIM
    for char in text or " ":
        vector[ord(char) % _VEC_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [_fake_vector(text) for text in texts]


@pytest.fixture(scope="session", autouse=True)
def mock_embedding():
    """全文件默认使用伪向量，避免依赖云端 Embedding API。

    必须是 session 级：class 级夹具（如 corpus）会先于函数级夹具构建，
    若只打函数级补丁，入库时就会走到真实 Embedding 而失败。
    """
    original = embedding.embed_texts
    embedding.embed_texts = _fake_embed_texts
    yield
    embedding.embed_texts = original


# ============================================================ 样本文件构造

AI_LECTURE = (
    "第三章 梯度下降与反向传播\n"
    "梯度下降是一种迭代优化算法，沿着损失函数的负梯度方向更新参数，逐步逼近极小值。\n"
    "学习率过大会导致震荡甚至发散，过小则收敛缓慢，实践中常配合学习率衰减策略。\n"
    "反向传播利用链式法则，从输出层向输入层逐层计算梯度，是神经网络训练的核心。\n"
    "批量梯度下降每次迭代使用全部样本，随机梯度下降每次只用一个样本，小批量折中两者。\n"
)


def _make_png(color: tuple[int, int, int] = (200, 30, 30), size: int = 48) -> bytes:
    """用 PyMuPDF 造一张真实 PNG（测试用，不依赖 Pillow）。"""
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size))
    pixmap.set_rect(pixmap.irect, color)
    return pixmap.tobytes("png")


def _make_pdf(table_on_page: int = 3, pages: int = 3) -> bytes:
    """生成多页 PDF，指定页画一个带框线的表格（用于验证「检索到指定页的表格」）。"""
    doc = fitz.open()
    for page_no in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (72, 60), f"第 {page_no} 页：人工智能导论讲义", fontname="china-s", fontsize=14
        )
        page.insert_text(
            (72, 90),
            "梯度下降用于最小化损失函数。",
            fontname="china-s",
            fontsize=11,
        )
        if page_no == table_on_page:
            x0, y0, rows, cols, w, h = 72, 120, 3, 3, 130, 26
            for r in range(rows + 1):
                page.draw_line(fitz.Point(x0, y0 + r * h), fitz.Point(x0 + cols * w, y0 + r * h))
            for c in range(cols + 1):
                page.draw_line(fitz.Point(x0 + c * w, y0), fitz.Point(x0 + c * w, y0 + rows * h))
            cells = [["函数", "表达式", "值域"], ["Sigmoid", "(0,1)", "饱和"], ["ReLU", "[0,+∞)", "常用"]]
            for r, row in enumerate(cells):
                for c, cell in enumerate(row):
                    page.insert_text(
                        (x0 + c * w + 6, y0 + r * h + 17), cell, fontname="china-s", fontsize=10
                    )
            page.insert_image(fitz.Rect(360, 120, 460, 220), stream=_make_png())
    data = doc.tobytes()
    doc.close()
    return data


def _make_docx() -> bytes:
    """Word：正文 + 表格 + 内嵌图片，验证三类内容都能被抽出。"""
    document = DocxDocument()
    document.add_heading("人工智能导论 第三章", level=1)
    document.add_paragraph("梯度下降是神经网络训练的基础优化算法。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "学习率"
    table.cell(0, 1).text = "现象"
    table.cell(1, 0).text = "0.9"
    table.cell(1, 1).text = "震荡不收敛"
    document.add_paragraph("下图为损失函数等高线示意。")
    document.add_picture(io.BytesIO(_make_png()))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_pptx() -> bytes:
    """PPT：标题 + 正文 + 表格 + 插图，页码即幻灯片序号。"""
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "反向传播算法"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    box.text_frame.text = "链式法则逐层求导"
    table_shape = slide.shapes.add_table(2, 2, Inches(1), Inches(3.4), Inches(5), Inches(1))
    table = table_shape.table
    table.cell(0, 0).text = "层"
    table.cell(0, 1).text = "作用"
    table.cell(1, 0).text = "输出层"
    table.cell(1, 1).text = "计算误差梯度"
    slide.shapes.add_picture(io.BytesIO(_make_png(size=64)), Inches(7), Inches(2), Inches(2), Inches(2))
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _make_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "成绩表"
    sheet.append(["学号", "姓名", "成绩"])
    sheet.append(["2023001", "李明", 92])
    sheet.append(["2023002", "王芳", 85])
    second = workbook.create_sheet("知识点掌握")
    second.append(["知识点", "掌握度"])
    second.append(["梯度下降", 0.75])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _make_legacy_doc() -> bytes:
    """老格式 .doc：OLE 二进制里以 UTF-16LE 存正文，验证降级抽取。"""
    text = "面试复盘记录：候选人对梯度下降的讲解清晰，建议补充正则化经验。"
    return text.encode("utf-16-le") + b"\x00\x01\x02\x03" * 16 + "答得不错。".encode("utf-16-le")


def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# ============================================================ 一、多模态解析

class TestParsers:
    """六类格式的解析能力（工单18 验收标准：多模态内容分析引擎）。"""

    def test_detect_file_type(self):
        assert detect_file_type("a.pdf") == "pdf"
        assert detect_file_type("a.DOCX") == "docx"
        assert detect_file_type("a.ppt") == "ppt"
        assert detect_file_type("a.xls") == "xls"
        assert detect_file_type("a.PNG") == "image"
        assert detect_file_type("无扩展名", b"%PDF-1.7") == "pdf"
        assert detect_file_type("a.txt") is None

    def test_pdf_extracts_text_and_table_with_page_no(self, tmp_path):
        path = _write(tmp_path, "lecture.pdf", _make_pdf(table_on_page=3))
        blocks = parse_document(path, image_dir=tmp_path / "img", rel_prefix="kb/1")

        text_blocks = [b for b in blocks if b.block_type == "text"]
        assert any("梯度下降" in b.content for b in text_blocks)
        # 第 1 页与第 3 页的文本都要在，且页码正确
        assert {b.page_no for b in text_blocks} >= {1, 3}

        tables = [b for b in blocks if b.block_type == "table"]
        assert tables, "应解析出表格块"
        table = tables[0]
        assert table.page_no == 3, "表格应标注所在页码"
        assert table.content.startswith("|") and "---" in table.content
        assert "值域" in table.content

    def test_pdf_extracts_embedded_image_to_uploads(self, tmp_path):
        path = _write(tmp_path, "lecture.pdf", _make_pdf())
        image_dir = tmp_path / "kb" / "7"
        blocks = parse_document(path, image_dir=image_dir, rel_prefix="kb/7")

        images = [b for b in blocks if b.block_type == "image"]
        assert images, "应抽出内嵌图片"
        assert images[0].image_path.startswith("kb/7/")
        assert (image_dir / images[0].image_path.split("/")[-1]).exists()
        # 图片块带上下文文字，才能被文本查询检索到
        assert "图片" in images[0].content

    def test_docx_extracts_paragraph_table_image(self, tmp_path):
        path = _write(tmp_path, "handout.docx", _make_docx())
        blocks = parse_document(path, image_dir=tmp_path / "img", rel_prefix="kb/2")

        assert any(b.block_type == "text" and "梯度下降" in b.content for b in blocks)
        table = next(b for b in blocks if b.block_type == "table")
        assert "学习率" in table.content and "|" in table.content
        assert any(b.block_type == "image" and b.image_path for b in blocks)

    def test_pptx_extracts_slides_table_picture(self, tmp_path):
        path = _write(tmp_path, "slides.pptx", _make_pptx())
        blocks = parse_document(path, image_dir=tmp_path / "img", rel_prefix="kb/3")

        assert any(b.content == "反向传播算法" and b.page_no == 1 for b in blocks)
        assert any(b.block_type == "table" and "输出层" in b.content for b in blocks)
        # 图片上下文含同页标题，便于「那页的图」类提问命中
        image = next(b for b in blocks if b.block_type == "image")
        assert image.page_no == 1 and "反向传播" in image.content

    def test_xlsx_converts_sheets_to_markdown(self, tmp_path):
        path = _write(tmp_path, "score.xlsx", _make_xlsx())
        blocks = parse_document(path)

        assert len(blocks) == 2, "两个工作表各成一块"
        assert blocks[0].section == "成绩表" and blocks[0].page_no == 1
        assert "| 学号 | 姓名 | 成绩 |" in blocks[0].content
        assert "梯度下降" in blocks[1].content

    def test_legacy_doc_degrades_with_notice(self, tmp_path):
        path = _write(tmp_path, "old.doc", _make_legacy_doc())
        blocks = parse_document(path)

        assert "【格式说明】" in blocks[0].content and "降级为纯文本抽取" in blocks[0].content
        assert any("面试复盘记录" in b.content for b in blocks[1:])

    def test_image_document_uses_original_path(self, tmp_path):
        path = _write(tmp_path, "diagram.png", _make_png())
        blocks = parse_document(path, rel_prefix="kb/9/diagram.png")

        assert blocks[0].block_type == "image"
        assert blocks[0].image_path == "kb/9/diagram.png"
        assert "diagram.png" in blocks[0].content

    def test_unsupported_format_raises(self, tmp_path):
        path = _write(tmp_path, "notes.txt", b"plain text")
        with pytest.raises(ValueError):
            parse_document(path)

    def test_formula_detection_keeps_original_text(self):
        assert looks_formula("σ(x) = 1 / (1 + e^-x)")
        assert looks_formula("L = Σ (y - ŷ)² / n")
        assert not looks_formula("梯度下降是一种优化算法，用于最小化损失函数。")
        assert not looks_formula("............................")  # 目录点线不算公式
        # 保守策略：纯 ASCII 四则运算式不判为公式，避免误伤英文正文（仍作为文本入库）
        assert not looks_formula("y = w x + b")


# ============================================================ 二、切块

class TestChunking:
    """约 500 字 + 重叠 80；表格/图片不切分。"""

    def test_text_chunks_size_and_overlap(self):
        long_text = "梯度下降沿负梯度方向更新参数。" * 60  # 约 960 字
        blocks = [ParsedBlock("text", long_text, page_no=2)]
        chunks = chunk_blocks(blocks, size=200, overlap=40)

        assert len(chunks) >= 4
        assert all(len(c.content) <= 200 for c in chunks)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert all(c.page_no == 2 for c in chunks)
        # 相邻块存在重叠：前一块的结尾片段应出现在后一块开头
        tail = chunks[0].content[-20:]
        assert tail in chunks[1].content

    def test_table_and_image_are_atomic(self):
        markdown = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        blocks = [
            ParsedBlock("text", "正文内容。" * 10, page_no=1),
            ParsedBlock("table", markdown, page_no=1),
            ParsedBlock("image", "图片（第 1 页）：示意图", page_no=1, image_path="kb/1/x.png"),
            ParsedBlock("text", "图片之后的正文。" * 10, page_no=2),
        ]
        chunks = chunk_blocks(blocks, size=100, overlap=20)

        types = [c.chunk_type for c in chunks]
        assert "table" in types and "image" in types
        table_chunk = next(c for c in chunks if c.chunk_type == "table")
        assert table_chunk.content == markdown, "表格整体成块，不被切散"
        image_chunk = next(c for c in chunks if c.chunk_type == "image")
        assert image_chunk.image_path == "kb/1/x.png"
        # 表格/图片前后的正文各自成块，不与多模态块混在一起
        assert all(c.chunk_type == "text" for c in chunks if "正文内容" in c.content)
        assert all(len(c.content) <= 100 for c in chunks)

    def test_oversized_table_split_repeats_header(self):
        rows = "\n".join(f"| 行{i} | 数据{i} |" for i in range(200))
        markdown = f"| 列A | 列B |\n| --- | --- |\n{rows}"
        chunks = chunk_blocks([ParsedBlock("table", markdown)], size=500, overlap=80)

        assert len(chunks) > 1, "超大表格应分组"
        for chunk in chunks:
            assert chunk.chunk_type == "table"
            assert chunk.content.startswith("| 列A | 列B |"), "每组都重复表头"

    def test_formula_block_keeps_type_and_context(self):
        blocks = [
            ParsedBlock("text", "损失函数定义如下："),
            ParsedBlock("formula", "L = Σ (y - ŷ)² / n"),
        ]
        chunks = chunk_blocks(blocks, size=500, overlap=80)

        assert chunks[0].chunk_type == "text"
        assert "损失函数" in chunks[0].content and "L = Σ" in chunks[0].content


# ============================================================ 三、入库与检索

def _upload(client, auth, token, filename: str, data: bytes, scope: str = "private"):
    return client.post(
        "/api/kb/upload",
        files={"file": (filename, data, "application/octet-stream")},
        data={"scope": scope},
        headers=auth(token),
    )


def _wait_done(client, auth, token, doc_id: int, timeout: int = 20) -> dict:
    """等待后台解析完成（TestClient 下通常同步完成，这里仍轮询兜底）。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/kb/docs/{doc_id}", headers=auth(token))
        assert resp.status_code == 200, resp.text
        doc = resp.json()["data"]
        if doc["parse_status"] in (PARSE_DONE, PARSE_FAILED):
            return doc
        time.sleep(0.2)
    raise AssertionError("解析超时")


class TestIngestPipeline:
    """上传 → 解析 → 切块 → 向量 → 状态流转。"""

    def test_upload_docx_and_index(self, client, auth, teacher_token):
        resp = _upload(client, auth, teacher_token, "人工智能导论.docx", _make_docx())
        assert resp.status_code == 200, resp.text
        doc = resp.json()["data"]
        assert doc["parse_status"] in ("pending", "parsing", "done")

        detail = _wait_done(client, auth, teacher_token, doc["id"])
        assert detail["parse_status"] == PARSE_DONE
        assert detail["chunk_count"] > 0
        assert detail["chunk_stats"]["table"] >= 1
        assert detail["chunk_stats"]["image"] >= 1
        assert detail["file_type"] == "docx"

    def test_upload_unsupported_format_rejected(self, client, auth, teacher_token):
        resp = _upload(client, auth, teacher_token, "笔记.txt", b"hello")
        assert resp.status_code == 400
        assert "暂不支持" in resp.json()["msg"]

    def test_oversize_upload_rejected(self, client, auth, teacher_token, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "KB_MAX_UPLOAD_MB", 0)
        resp = _upload(client, auth, teacher_token, "big.pdf", _make_pdf())
        assert resp.status_code == 400
        assert "上限" in resp.json()["msg"]

    def test_failed_parse_records_reason(self, client, auth, teacher_token):
        """损坏的 PDF：状态置 failed 且写入可读原因，不抛 500。"""
        resp = _upload(client, auth, teacher_token, "broken.pdf", b"%PDF-1.7\n not a real pdf")
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()["data"]["id"]
        detail = _wait_done(client, auth, teacher_token, doc_id)
        # PyMuPDF 对损坏文件会抛错；若个别版本能容错解析，则至少状态是 done 而非崩
        assert detail["parse_status"] in (PARSE_DONE, PARSE_FAILED)
        if detail["parse_status"] == PARSE_FAILED:
            assert detail["parse_error"]

    def test_delete_doc_removes_chunks_and_files(self, client, auth, teacher_token):
        doc_id = _upload(client, auth, teacher_token, "待删除.docx", _make_docx()).json()["data"]["id"]
        _wait_done(client, auth, teacher_token, doc_id)

        assert client.delete(f"/api/kb/docs/{doc_id}", headers=auth(teacher_token)).status_code == 200
        assert client.get(f"/api/kb/docs/{doc_id}", headers=auth(teacher_token)).status_code == 404


class TestHybridSearch:
    """向量 + 关键词混合检索、RRF 融合、引用元数据。"""

    @pytest.fixture(scope="class")
    def corpus(self, client, auth, teacher_token):
        """公共库放入一份 PDF（第 3 页含表格）与一份 Word。"""
        pdf_id = _upload(
            client, auth, teacher_token, "人工智能导论-讲义.pdf", _make_pdf(table_on_page=3),
            scope="public",
        ).json()["data"]["id"]
        docx_id = _upload(
            client, auth, teacher_token, "梯度下降讲义.docx", _make_docx(), scope="public"
        ).json()["data"]["id"]
        _wait_done(client, auth, teacher_token, pdf_id)
        _wait_done(client, auth, teacher_token, docx_id)
        return {"pdf": pdf_id, "docx": docx_id}

    def test_search_returns_citations(self, client, auth, student_token, corpus):
        resp = client.post(
            "/api/kb/search",
            json={"question": "梯度下降是什么？", "top_k": 5},
            headers=auth(student_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert 0 < len(data["citations"]) <= 5
        first = data["citations"][0]
        assert first["index"] == 1
        assert first["filename"]
        assert first["chunk_type"] in ("text", "table", "image", "formula")
        assert first["matched_by"], "应标明命中来源（vector / keyword）"

    def test_search_hits_table_on_specified_page(self, client, auth, student_token, corpus):
        """验收标准：能检索到指定页的表格。"""
        resp = client.post(
            "/api/kb/search",
            json={"question": "Sigmoid 函数的值域", "top_k": 5},
            headers=auth(student_token),
        )
        assert resp.status_code == 200, resp.text
        citations = resp.json()["data"]["citations"]

        tables = [c for c in citations if c["chunk_type"] == "table"]
        assert tables, f"应命中表格块，实际：{[(c['chunk_type'], c['filename']) for c in citations]}"
        assert tables[0]["page_no"] == 3, "表格引用应标注正确页码"

    def test_search_scope_public_only(self, client, auth, student_token, corpus):
        resp = client.post(
            "/api/kb/search",
            json={"question": "梯度下降", "scope": "public"},
            headers=auth(student_token),
        )
        assert resp.status_code == 200
        assert all(c["scope"] == "public" for c in resp.json()["data"]["citations"])

    def test_search_empty_question_rejected(self, client, auth, student_token):
        resp = client.post("/api/kb/search", json={"question": ""}, headers=auth(student_token))
        assert resp.status_code == 422

    def test_search_without_embedding_config(self, client, auth, student_token, monkeypatch):
        async def _boom(texts):
            raise embedding.EmbeddingNotConfiguredError("未配置 Embedding API Key")

        monkeypatch.setattr(embedding, "embed_texts", _boom)
        resp = client.post(
            "/api/kb/search", json={"question": "梯度下降"}, headers=auth(student_token)
        )
        assert resp.status_code == 400
        assert "Embedding" in resp.json()["msg"]

    def test_rerank_failure_degrades_gracefully(self, client, auth, student_token, corpus, monkeypatch):
        """重排网关不可达时，检索仍返回混合检索结果（自动降级）。"""
        from app.config import settings

        monkeypatch.setattr(settings, "RERANK_ENABLED", True)
        monkeypatch.setattr(settings, "RERANK_BASE_URL", "http://127.0.0.1:9/v1")
        monkeypatch.setattr(settings, "RERANK_API_KEY", "sk-test-not-real")

        resp = client.post(
            "/api/kb/search",
            json={"question": "梯度下降", "use_rerank": True},
            headers=auth(student_token),
        )
        assert resp.status_code == 200, resp.text
        citations = resp.json()["data"]["citations"]
        assert citations, "重排失败也必须返回混合检索结果"
        assert all("rerank" not in c["matched_by"] for c in citations)


# ============================================================ 四、向量库配置一致性

class TestVectorStoreSignature:
    """换 Embedding 模型（云端 bge-m3 1024 维 ↔ 本地 bge-small 512 维）时，
    维度不一致必须给出可读原因，而不是让 Chroma 抛晦涩的维度错误。"""

    @pytest.fixture
    def restore_signature(self):
        """备份并还原向量库签名文件，避免污染同会话的其它用例。"""
        path = settings.chroma_dir / vector_store._SIGNATURE_FILE
        original = path.read_text(encoding="utf-8") if path.exists() else None
        yield path
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original, encoding="utf-8")

    def test_signature_blocks_upsert_after_model_switch(self, restore_signature, tmp_path):
        restore_signature.write_text(
            json.dumps({"model": "BAAI/bge-m3", "dim": 1024}), encoding="utf-8"
        )
        with pytest.raises(RuntimeError) as excinfo:
            vector_store.upsert_chunks(
                doc_id=999,
                scope="private",
                owner_id=1,
                filename="x.docx",
                items=[{"chunk_index": 0, "content": "内容", "chunk_type": "text"}],
                embeddings=[[0.1] * _VEC_DIM],
            )
        message = str(excinfo.value)
        assert "BAAI/bge-m3" in message and "1024" in message
        assert "data/chroma" in message, "要给出可操作的修复建议"

    def test_query_degrades_when_signature_mismatched(self, restore_signature):
        restore_signature.write_text(
            json.dumps({"model": "BAAI/bge-m3", "dim": 1024}), encoding="utf-8"
        )
        hits = vector_store.query_similar(collection="public", embedding=[0.1] * _VEC_DIM)
        assert hits == [], "维度不一致时向量召回应跳过（降级为纯关键词召回）而非报错"

    def test_signature_written_on_first_upsert(self, restore_signature):
        restore_signature.unlink(missing_ok=True)
        reason = vector_store.check_embedding_signature(_VEC_DIM)
        assert reason is None
        saved = json.loads(restore_signature.read_text(encoding="utf-8"))
        assert saved["dim"] == _VEC_DIM
        assert saved["model"] == embedding.active_model_name()

    def test_active_model_name_follows_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        assert embedding.active_model_name() == settings.EMBEDDING_LOCAL_MODEL
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "api")
        assert embedding.active_model_name() == settings.EMBEDDING_MODEL


# ============================================================ 五、权限隔离

class TestPermissions:
    """公共库仅教师可写；私有库按用户隔离（三重保障的接口层校验）。"""

    @pytest.fixture(scope="class")
    def private_doc(self, client, auth, student_token):
        doc_id = _upload(
            client, auth, student_token, "我的笔记.docx", _make_docx(), scope="private"
        ).json()["data"]["id"]
        _wait_done(client, auth, student_token, doc_id)
        return doc_id

    def test_student_cannot_upload_to_public(self, client, auth, student_token):
        resp = _upload(client, auth, student_token, "课件.pptx", _make_pptx(), scope="public")
        assert resp.status_code == 403
        assert "教师" in resp.json()["msg"]

    def test_private_doc_invisible_to_others(self, client, auth, student_token, teacher_token, private_doc):
        # 列表里看不到
        docs = client.get("/api/kb/docs", params={"scope": "private"}, headers=auth(teacher_token)).json()["data"]
        assert all(d["id"] != private_doc for d in docs)
        # 详情直接 403
        assert client.get(f"/api/kb/docs/{private_doc}", headers=auth(teacher_token)).status_code == 403
        # 删除也 403
        assert client.delete(f"/api/kb/docs/{private_doc}", headers=auth(teacher_token)).status_code == 403

    def test_private_chunks_invisible_to_others(self, client, auth, teacher_token, student_token, private_doc):
        detail = client.get(f"/api/kb/docs/{private_doc}", headers=auth(student_token)).json()["data"]
        chunk_id = detail["chunks"][0]["id"]
        assert client.get(f"/api/kb/chunks/{chunk_id}", headers=auth(teacher_token)).status_code == 403
        assert client.get(f"/api/kb/chunks/{chunk_id}/image", headers=auth(teacher_token)).status_code in (403, 404)

    def test_private_doc_not_recalled_by_others(self, client, auth, teacher_token, student_token, private_doc):
        """混合检索同样不可能召回他人私有库内容。"""
        resp = client.post(
            "/api/kb/search",
            json={"question": "梯度下降 学习率 震荡", "top_k": 10},
            headers=auth(teacher_token),
        )
        assert resp.status_code == 200
        assert all(c["doc_id"] != private_doc for c in resp.json()["data"]["citations"])

    def test_public_doc_readable_by_student(self, client, auth, student_token, teacher_token):
        doc_id = _upload(
            client, auth, teacher_token, "公共讲义.docx", _make_docx(), scope="public"
        ).json()["data"]["id"]
        _wait_done(client, auth, teacher_token, doc_id)
        assert client.get(f"/api/kb/docs/{doc_id}", headers=auth(student_token)).status_code == 200
        # 但学生不能删公共库文档
        assert client.delete(f"/api/kb/docs/{doc_id}", headers=auth(student_token)).status_code == 403

    def test_unauthenticated_rejected(self, client):
        assert client.get("/api/kb/docs").status_code == 401

    def test_reparse_requires_owner(self, client, auth, teacher_token, private_doc):
        assert (
            client.post(f"/api/kb/docs/{private_doc}/reparse", headers=auth(teacher_token)).status_code
            == 403
        )


# ============================================================ 六、问答（SSE）

class TestChat:
    """SSE 事件流、引用落库、多轮上下文、错误提示。"""

    ANSWER = "梯度下降是沿负梯度方向迭代更新参数的优化算法 [1]。"

    @pytest.fixture(scope="class")
    def kb_ready(self, client, auth, teacher_token):
        doc_id = _upload(
            client, auth, teacher_token, "问答语料.pdf", _make_pdf(table_on_page=2), scope="public"
        ).json()["data"]["id"]
        _wait_done(client, auth, teacher_token, doc_id)
        return doc_id

    @pytest.fixture
    def mock_chat_stream(self, monkeypatch):
        captured: dict = {}

        async def _stream(messages, **kwargs):
            captured["messages"] = messages
            for i in range(0, len(self.ANSWER), 6):
                yield self.ANSWER[i : i + 6]

        monkeypatch.setattr(llm_client, "chat_stream", _stream)
        return captured

    @staticmethod
    def _parse_sse(text: str) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        for block in text.strip().split("\n\n"):
            name, payload = None, None
            for line in block.splitlines():
                if line.startswith("event: "):
                    name = line[7:].strip()
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
            if name:
                events.append((name, payload or {}))
        return events

    def test_chat_streams_with_citations(self, client, auth, student_token, kb_ready, mock_chat_stream):
        resp = client.post(
            "/api/assistant/chat",
            json={"question": "梯度下降的原理是什么？", "top_k": 3},
            headers=auth(student_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")

        events = self._parse_sse(resp.text)
        names = [name for name, _ in events]
        assert names[0] == "sources" and names[-1] == "done"
        assert "delta" in names

        sources = events[0][1]
        assert sources["citations"], "应先下发引用来源"
        assert sources["citations"][0]["filename"]
        answer = "".join(payload["text"] for name, payload in events if name == "delta")
        assert answer == self.ANSWER

        # 提示词里必须带上编号资料，模型才有依据可引
        system = mock_chat_stream["messages"][0]["content"]
        assert "标注来源编号" in system
        assert "[1]" in mock_chat_stream["messages"][-1]["content"]

        # 会话与引用落库
        conversation_id = events[-1][1]["conversation_id"]
        assert conversation_id
        detail = client.get(
            f"/api/assistant/conversations/{conversation_id}", headers=auth(student_token)
        ).json()["data"]
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["citations"][0]["filename"]
        assert detail["title"]

    def test_chat_second_turn_keeps_history(self, client, auth, student_token, kb_ready, mock_chat_stream):
        first = self._parse_sse(
            client.post(
                "/api/assistant/chat",
                json={"question": "什么是反向传播？"},
                headers=auth(student_token),
            ).text
        )
        conversation_id = first[-1][1]["conversation_id"]

        second = self._parse_sse(
            client.post(
                "/api/assistant/chat",
                json={"question": "那它和梯度下降的关系呢？", "conversation_id": conversation_id},
                headers=auth(student_token),
            ).text
        )
        assert second[-1][1]["conversation_id"] == conversation_id
        roles = [m["role"] for m in mock_chat_stream["messages"]]
        assert roles == ["system", "user", "assistant", "user"], "应带入上一轮问答作为上下文"

        detail = client.get(
            f"/api/assistant/conversations/{conversation_id}", headers=auth(student_token)
        ).json()["data"]
        assert len(detail["messages"]) == 4

    def test_chat_prompt_without_hits_forbids_fabrication(self, client, auth, student_token, mock_chat_stream, monkeypatch):
        """知识库无相关内容时，提示词必须要求明确说明「未找到依据」。"""

        async def _empty_search(db, **kwargs):
            return []

        monkeypatch.setattr(retriever, "search", _empty_search)
        resp = client.post(
            "/api/assistant/chat",
            json={"question": "量子纠缠在烹饪中的应用"},
            headers=auth(student_token),
        )
        events = self._parse_sse(resp.text)
        assert events[0][1]["citations"] == []
        system = mock_chat_stream["messages"][0]["content"]
        assert "未在知识库中找到依据" in system
        assert "严禁" in system  # 严禁编造

    def test_chat_llm_not_configured(self, client, auth, student_token, kb_ready, monkeypatch):
        async def _raise(messages, **kwargs):
            raise llm_client.LLMNotConfiguredError("未配置 LLM API Key")
            yield  # pragma: no cover - 仅用于让函数成为异步生成器

        monkeypatch.setattr(llm_client, "chat_stream", _raise)
        resp = client.post(
            "/api/assistant/chat", json={"question": "梯度下降"}, headers=auth(student_token)
        )
        events = self._parse_sse(resp.text)
        assert ("error", {"msg": "未配置 LLM API Key"}) in events

    def test_conversation_isolation(self, client, auth, student_token, teacher_token, kb_ready, mock_chat_stream):
        conversation_id = self._parse_sse(
            client.post(
                "/api/assistant/chat", json={"question": "梯度下降"}, headers=auth(student_token)
            ).text
        )[-1][1]["conversation_id"]

        assert (
            client.get(f"/api/assistant/conversations/{conversation_id}", headers=auth(teacher_token)).status_code
            == 404
        )
        assert (
            client.delete(f"/api/assistant/conversations/{conversation_id}", headers=auth(teacher_token)).status_code
            == 404
        )
        listed = client.get("/api/assistant/conversations", headers=auth(teacher_token)).json()["data"]
        assert all(item["id"] != conversation_id for item in listed)

    def test_delete_conversation(self, client, auth, student_token, kb_ready, mock_chat_stream):
        conversation_id = self._parse_sse(
            client.post(
                "/api/assistant/chat", json={"question": "梯度下降"}, headers=auth(student_token)
            ).text
        )[-1][1]["conversation_id"]
        assert client.delete(f"/api/assistant/conversations/{conversation_id}", headers=auth(student_token)).status_code == 200
        assert client.get(f"/api/assistant/conversations/{conversation_id}", headers=auth(student_token)).status_code == 404


class TestRagPrompt:
    """提示词构造（不依赖网络）。"""

    def test_build_context_numbers_sources(self):
        from app.services.retriever import Hit

        hits = [
            Hit(
                chunk_id=1, doc_id=1, chunk_index=0, chunk_type="text",
                content="梯度下降是最优化算法。", filename="讲义.pdf", scope="public", page_no=3,
            ),
            Hit(
                chunk_id=2, doc_id=1, chunk_index=1, chunk_type="table",
                content="| 函数 | 值域 |", filename="讲义.pdf", scope="public", page_no=3,
            ),
        ]
        messages = assistant_service.build_rag_messages("梯度下降是什么", hits)
        user_content = messages[-1]["content"]
        assert "[1] 《讲义.pdf》 第 3 页（正文）" in user_content
        assert "[2] 《讲义.pdf》 第 3 页（表格）" in user_content
        assert "梯度下降是什么" in user_content

    def test_make_title_truncates(self):
        assert assistant_service.make_title("短问题") == "短问题"
        assert len(assistant_service.make_title("很长的问" * 20)) <= 24
