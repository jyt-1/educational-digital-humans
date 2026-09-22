# [工单21] 人工智能NLP-Agent数字人项目-教育智能体-虚拟教室/讲课页 —— 数字人讲课成课接口
"""成课链路：备课教案 → 课程草稿 → 后台生成任务（Wav2Lip 离线管线）→ 虚拟教室观看。

- POST /api/lecture/draft     从备课内容（教案 markdown `## ` 分节 / 课件幻灯片 items）生成课程配置草稿，前端弹层预填可编辑
- POST /api/lecture/generate  提交课程配置，起后台线程跑 gen_lecture.py（一次仅允许一个任务）
- GET  /api/lecture/jobs/{id} 轮询生成进度
- GET  /api/lecture/courses   列出全部课程（静态内置 + 已生成），师生均可调用

生成产物落 uploads/lectures/<courseId>/，经 main.py 挂载的 /api/lecture/media 静态下发。
生成器是外部管线（C:/Users/23772/sx/wav2lip/gen_lecture.py，依赖 400MB 权重目录），不入仓库。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.staticfiles import StaticFiles  # noqa: F401  （挂载在 main.py）
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_teacher
from app.config import settings
from app.db import get_db
from app.models.lesson import TeachingPlan
from app.models.user import User
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/lecture", tags=["虚拟教室"])

# ---- 外部管线（wav2lip 不在仓库内，缺失时接口给出明确报错而不是崩） ----
WAV2LIP_DIR = Path(r"C:/Users/23772/sx/wav2lip")
GEN_SCRIPT = WAV2LIP_DIR / "gen_lecture.py"
PYTHON = r"D:/anaconda3/python.exe"

# faces.js 六个写实形象的 id → 资产文件名（讲课视频按此取照片）
AVATAR_ASSETS: dict[str, str] = {
    "xiaowen": "photo-teacher.png",
    "suqing": "f-young-blue.png",
    "zhouhui": "f-senior-burgundy.png",
    "linyue": "f-lively-ponytail.png",
    "chenyuan": "m-young-navy.png",
    "wuqian": "m-senior-tweed.png",
}

STATIC_COURSES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "public" / "lectures"
PROJECT_ROOT_AVATAR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "assets" / "avatar"


def lectures_dir() -> Path:
    """已生成课程的存放目录（uploads/lectures，隔离在测试临时目录规则内）。"""
    d = settings.upload_dir / "lectures"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ 课程草稿
class DraftRequest(BaseModel):
    plan_id: int


_MD_STRIP = re.compile(r"^#{1,6}\s*|^\s*[-*+]\s+|^\s*\d+[.、)]\s+|\*\*|`")


def _md_to_spoken(md: str) -> str:
    """markdown → 口语讲稿底稿：去标题/列表/加粗等标记，保留正文行。教师可在前端继续改写。"""
    lines = []
    for line in md.splitlines():
        t = _MD_STRIP.sub("", line.strip())
        if t and not t.startswith(("|", ">", "---", "==")):
            lines.append(t)
    return "\n".join(lines)


def _split_markdown_pages(raw: str) -> list[dict]:
    """按 `## ` 一级分节拆课件页；无分节则整篇一页。"""
    parts = re.split(r"(?m)^##\s+", raw)
    pages = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        head, _, body = part.partition("\n")
        pages.append({"title": head.strip(), "body": body.strip() or head.strip()})
    return pages or [{"title": "课件", "body": raw.strip()}]


@router.post("/draft", response_model=ApiResponse[dict], summary="从备课内容生成课程配置草稿")
def draft_lecture(
    payload: DraftRequest,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    plan = db.get(TeachingPlan, payload.plan_id)
    if plan is None or plan.owner_id != user.id:
        raise HTTPException(status_code=404, detail="备课内容不存在")
    if plan.content_type not in ("教案", "课件"):
        raise HTTPException(
            status_code=400,
            detail="只有「教案」和「课件」能转成讲课视频，请先在智能备课里生成对应内容",
        )

    try:
        content = json.loads(plan.content_json)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="备课内容解析失败") from None

    if plan.content_type == "课件":
        pages, segments = _slides_to_pages(content)
    else:
        raw = content.get("raw", "")
        md_pages = _split_markdown_pages(raw)
        pages = md_pages
        segments = [
            {"page": i + 1, "text": _md_to_spoken(p["body"])} for i, p in enumerate(md_pages)
        ]
    return ApiResponse(data={
        "plan_id": plan.id,
        "title": plan.title or plan.course_name,
        "subject": plan.subject or plan.course_name,
        "pages": pages,
        "segments": segments,
    })


def _slides_to_pages(content: dict) -> tuple[list[dict], list[dict]]:
    """课件 items（{title, bullets, notes}）→ 讲课页与讲稿底稿。
    讲稿优先取生成时写好的 notes；缺 notes 的页用 标题+要点 拼底稿，教师在弹层里补写。"""
    items = content.get("items") or []
    if not items:
        raise HTTPException(status_code=400, detail="该课件没有幻灯片页面，无法成课")
    pages: list[dict] = []
    segments: list[dict] = []
    for i, item in enumerate(items):
        title = str(item.get("title") or f"第{i + 1}页").strip() or f"第{i + 1}页"
        bullets = [str(b).strip() for b in (item.get("bullets") or []) if str(b).strip()]
        notes = str(item.get("notes") or "").strip()
        pages.append({"title": title[:120], "body": "\n".join(f"- {b}" for b in bullets)})
        segments.append({"page": i + 1, "text": notes or "\n".join([title, *bullets])[:2000]})
    return pages, segments


# ------------------------------------------------------------------ 生成任务
class PageIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1)


class SegmentIn(BaseModel):
    page: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=2000)


class GenerateRequest(BaseModel):
    plan_id: int | None = None
    title: str = Field(min_length=1, max_length=120)
    subject: str = ""
    avatar: str = "xiaowen"
    pages: list[PageIn] = Field(min_length=1, max_length=20)
    segments: list[SegmentIn] = Field(min_length=1, max_length=40)


class _Job:
    """一次成课任务的内存状态。服务重启即丢（MVP 口径：任务几分钟内完成，可接受）。"""

    def __init__(self, job_id: str, course_id: str, plan_id: int | None, total: int):
        self.id = job_id
        self.course_id = course_id
        self.plan_id = plan_id
        self.status = "running"  # running | done | error
        self.progress = 0
        self.message = "排队中"
        self.error = ""
        self.total = total
        self.thread: threading.Thread | None = None


_JOBS: dict[str, _Job] = {}
_JOB_LOCK = threading.Lock()


def _job_snapshot(job: _Job) -> dict:
    return {
        "job_id": job.id, "course_id": job.course_id, "plan_id": job.plan_id,
        "status": job.status, "progress": job.progress,
        "message": job.message, "error": job.error,
    }


def _pipeline_env() -> dict[str, str]:
    """子进程环境：剥离代理变量。uvicorn 常带着宿主的 HTTP(S)_PROXY 启动，
    而这些代理对 speech.platform.bing.com（Edge-TTS）多半是死路；
    手动裸跑（无代理变量）从来是通的，所以管线子进程对齐裸环境。"""
    banned = {"http_proxy", "https_proxy", "all_proxy", "ftp_proxy"}
    env = {k: v for k, v in os.environ.items() if k.lower() not in banned}
    # 管道模式下子进程 stdout 按 locale（GBK）编码，管线里的 emoji/中文打印会直接
    # UnicodeEncodeError 摔掉——产物已生成却被误判失败。强制 UTF-8。
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_pipeline(job: _Job, spec_path: Path, out_dir: Path) -> None:
    """工作线程：跑外部管线，解析进度行。"""
    tail: list[str] = []
    try:
        proc = subprocess.Popen(
            [PYTHON, str(GEN_SCRIPT), str(spec_path), "--out-dir", str(out_dir)],
            cwd=str(WAV2LIP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="ignore", env=_pipeline_env(),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            tail.append(line)
            if len(tail) > 60:
                tail.pop(0)
            m = re.match(r"\[gen\] SEG (\d+)/(\d+)$", line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                job.progress = int(done / max(total, 1) * 90)
                job.message = f"已生成 {done}/{total} 段"
            elif line == "[gen] CONCAT":
                job.progress = 92
                job.message = "拼接整课视频"
        proc.wait(timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError(f"管线退出码 {proc.returncode}，输出尾部：\n" + "\n".join(tail[-25:]))
        if not (out_dir / "video.mp4").exists():
            raise RuntimeError("管线结束但未产出 video.mp4")
        job.progress = 100
        job.status = "done"
        job.message = "生成完成"
    except Exception as exc:  # noqa: BLE001  任务线程内兜底，状态必须落到 error
        job.status = "error"
        job.error = str(exc)[:1500]
        job.message = "生成失败"


@router.post("/generate", response_model=ApiResponse[dict], summary="提交成课任务（teacher）")
def generate_lecture(
    payload: GenerateRequest,
    user: User = Depends(require_teacher),
) -> ApiResponse[dict]:
    if not GEN_SCRIPT.exists():
        raise HTTPException(status_code=503, detail="生成管线未就绪：本机缺少 wav2lip 管线目录")
    if payload.avatar not in AVATAR_ASSETS:
        raise HTTPException(status_code=400, detail=f"不支持的形象：{payload.avatar}")

    page_ids = {i + 1 for i in range(len(payload.pages))}
    bad = [s.page for s in payload.segments if s.page not in page_ids]
    if bad:
        raise HTTPException(status_code=400, detail=f"讲稿引用了不存在的课件页：{sorted(set(bad))}")

    with _JOB_LOCK:
        running = [j for j in _JOBS.values() if j.status == "running"]
        if running:
            raise HTTPException(status_code=409, detail="已有生成任务在进行中，请等它完成后再提交")

        course_id = f"p{payload.plan_id or 'x'}-{time.strftime('%m%d%H%M%S')}"
        out_dir = lectures_dir() / course_id
        out_dir.mkdir(parents=True, exist_ok=True)
        spec = {
            "courseId": course_id,
            "title": payload.title,
            "subject": payload.subject,
            "image": str(PROJECT_ROOT_AVATAR / AVATAR_ASSETS[payload.avatar]),
            "avatar": payload.avatar,
            "pages": [p.model_dump() for p in payload.pages],
            "segments": [s.model_dump() for s in payload.segments],
        }
        spec_path = out_dir / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")

        job = _Job(uuid.uuid4().hex[:12], course_id, payload.plan_id, len(payload.segments))
        job.message = "开始生成"
        job.thread = threading.Thread(
            target=_run_pipeline, args=(job, spec_path, out_dir), daemon=True, name=f"lecture-{job.id}")
        _JOBS[job.id] = job
        job.thread.start()

    return ApiResponse(data=_job_snapshot(job))


@router.get("/jobs/{job_id}", response_model=ApiResponse[dict], summary="查询成课任务进度（teacher）")
def lecture_job(job_id: str, user: User = Depends(require_teacher)) -> ApiResponse[dict]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在（可能服务已重启）")
    return ApiResponse(data=_job_snapshot(job))


# ------------------------------------------------------------------ 课程列表
def _scan_courses(root: Path, base_prefix: str) -> list[dict]:
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        meta = d / "course.json"
        if d.is_dir() and meta.exists():
            try:
                c = json.loads(meta.read_text(encoding="utf-8"))
                out.append({"courseId": c.get("courseId", d.name), "title": c.get("title", d.name),
                            "subject": c.get("subject", ""), "base": f"{base_prefix}/{d.name}"})
            except ValueError:
                continue
    return out


@router.get("/courses", response_model=ApiResponse[list[dict]], summary="课程列表（师生均可）")
def list_courses(user: User = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    courses = _scan_courses(STATIC_COURSES_DIR, "/lectures")  # 内置静态课在前
    courses += _scan_courses(lectures_dir(), "/api/lecture/media")
    return ApiResponse(data=courses)
