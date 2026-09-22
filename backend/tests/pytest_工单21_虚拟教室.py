# [工单21] 人工智能NLP-Agent数字人项目-教育智能体-虚拟教室/讲课页 —— 成课链路测试
"""成课接口测试：教案草稿拆页、teacher 守卫、页面引用校验、任务状态机（mock 管线）、课程列表。

不真跑 Wav2Lip：_run_pipeline 被 mock 成直接落产物，只验证接口编排与状态流转。
"""

from __future__ import annotations

import json

import pytest

from app.api import lecture as lecture_api


def _make_plan(
    owner_id: int,
    content_type: str = "教案",
    raw: str | None = None,
    content: dict | None = None,
) -> int:
    from app.db import SessionLocal
    from app.models.lesson import TeachingPlan

    if content is None:
        if raw is None:
            raw = (
                "## 一、教学目标\n\n1. 理解基本概念\n2. 掌握核心方法\n\n## 二、重点难点\n\n"
                "重点在**应用**，难点在推导。"
            )
        content = {"format": "markdown", "raw": raw}
    with SessionLocal() as db:
        plan = TeachingPlan(
            owner_id=owner_id,
            content_type=content_type,
            course_name="测试课程",
            title=f"测试课程-{content_type}",
            content_json=json.dumps(content, ensure_ascii=False),
        )
        db.add(plan)
        db.commit()
        return plan.id


def _owner_id_by_username(username: str) -> int:
    from app.db import SessionLocal
    from app.models.user import User

    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).one().id


def test_draft_splits_markdown(client, auth, teacher_token):
    plan_id = _make_plan(_owner_id_by_username("teacher_zhang"))
    resp = client.post("/api/lecture/draft", json={"plan_id": plan_id}, headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "测试课程-教案"
    assert [p["title"] for p in data["pages"]] == ["一、教学目标", "二、重点难点"]
    # 讲稿底稿：markdown 标记被剥掉
    assert "##" not in data["segments"][0]["text"]
    assert "理解基本概念" in data["segments"][0]["text"]
    assert "**" not in data["segments"][1]["text"]
    assert "难点在推导" in data["segments"][1]["text"]


def test_draft_supports_slides(client, auth, teacher_token):
    """课件成课：每页一条讲稿，notes 优先；缺 notes 的页用 标题+要点 拼底稿。"""
    slides = {
        "format": "json",
        "raw": "",
        "items": [
            {"title": "过拟合是什么", "bullets": ["定义：训练集很准、测试集拉胯"], "notes": "同学们好，我们来看过拟合。"},
            {"title": "缓解手段", "bullets": ["正则化", "早停", "数据增强"], "notes": ""},
        ],
    }
    plan_id = _make_plan(
        _owner_id_by_username("teacher_zhang"), content_type="课件", content=slides
    )
    resp = client.post("/api/lecture/draft", json={"plan_id": plan_id}, headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [p["title"] for p in data["pages"]] == ["过拟合是什么", "缓解手段"]
    # 页面正文 = 要点的 markdown 列表
    assert "- 正则化" in data["pages"][1]["body"]
    # 讲稿：有 notes 用 notes，没有则标题+要点兜底
    assert data["segments"][0]["text"] == "同学们好，我们来看过拟合。"
    assert "缓解手段" in data["segments"][1]["text"]
    assert "数据增强" in data["segments"][1]["text"]


def test_draft_rejects_empty_slides(client, auth, teacher_token):
    plan_id = _make_plan(
        _owner_id_by_username("teacher_zhang"),
        content_type="课件",
        content={"format": "json", "raw": "", "items": []},
    )
    resp = client.post("/api/lecture/draft", json={"plan_id": plan_id}, headers=auth(teacher_token))
    assert resp.status_code == 400


def test_draft_rejects_non_plan(client, auth, teacher_token):
    plan_id = _make_plan(_owner_id_by_username("teacher_zhang"), content_type="习题")
    resp = client.post("/api/lecture/draft", json={"plan_id": plan_id}, headers=auth(teacher_token))
    assert resp.status_code == 400


def test_draft_teacher_isolated(client, auth, other_teacher_token):
    """别人（包括其他老师）的教案拿不到：404。"""
    plan_id = _make_plan(_owner_id_by_username("teacher_zhang"))
    resp = client.post("/api/lecture/draft", json={"plan_id": plan_id}, headers=auth(other_teacher_token))
    assert resp.status_code == 404


def test_generate_requires_teacher(client, auth, student_token):
    resp = client.post("/api/lecture/generate", json={}, headers=auth(student_token))
    assert resp.status_code == 403


def _valid_payload() -> dict:
    return {
        "plan_id": None,
        "title": "接口冒烟课",
        "subject": "测试",
        "avatar": "xiaowen",
        "pages": [{"title": "第一页", "body": "内容"}],
        "segments": [{"page": 1, "text": "同学们好。"}],
    }


def test_generate_rejects_bad_page_ref(client, auth, teacher_token):
    payload = _valid_payload()
    payload["segments"] = [{"page": 9, "text": "越界讲稿"}]
    resp = client.post("/api/lecture/generate", json=payload, headers=auth(teacher_token))
    assert resp.status_code == 400


def test_generate_job_lifecycle_and_courses(client, auth, teacher_token, monkeypatch):
    """mock 掉真管线：验证任务状态 running→done、课程列表出现新课程。"""

    def fake_pipeline(job, spec_path, out_dir):
        (out_dir / "video.mp4").write_bytes(b"\x00fake")
        (out_dir / "timeline.json").write_text("[]", encoding="utf-8")
        (out_dir / "course.json").write_text(
            json.dumps({"courseId": job.course_id, "title": "接口冒烟课", "subject": "测试", "pages": []},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        job.progress = 100
        job.status = "done"
        job.message = "生成完成"

    monkeypatch.setattr(lecture_api, "_run_pipeline", fake_pipeline)

    resp = client.post("/api/lecture/generate", json=_valid_payload(), headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    job = resp.json()["data"]
    assert job["status"] in ("running", "done")

    # 轮询到终态（线程是 daemon，mock 下立即完成，留一点调度余量）
    import time

    final = None
    for _ in range(30):
        r = client.get(f"/api/lecture/jobs/{job['job_id']}", headers=auth(teacher_token))
        assert r.status_code == 200
        final = r.json()["data"]
        if final["status"] != "running":
            break
        time.sleep(0.1)
    assert final is not None and final["status"] == "done", final
    assert final["progress"] == 100

    # 课程列表出现新课程，且 base 指向媒体挂载路径
    resp = client.get("/api/lecture/courses", headers=auth(teacher_token))
    assert resp.status_code == 200
    courses = resp.json()["data"]
    mine = [c for c in courses if c["courseId"] == job["course_id"]]
    assert mine and mine[0]["base"].startswith("/api/lecture/media/")
    assert mine[0]["title"] == "接口冒烟课"


def test_courses_requires_login(client):
    assert client.get("/api/lecture/courses").status_code == 401
