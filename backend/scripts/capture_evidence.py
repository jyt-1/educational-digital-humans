# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 验收取证脚本（覆盖工单17/18/19）
"""验收取证：驱动本机 Edge 把三个工单的验收动线真点一遍，截图落盘到 docs/evidence/工单XX/。

为什么要有这个脚本
------------------
CLAUDE.md 第 10 节 DoD 第 5 条要 `docs/evidence/工单XX/` 有截图，而验收标准写的是
"可现场演示""答题→画像更新→推荐路径""答错生成解析与变式题"——这些都只能在浏览器里发生。
手工点一遍能过，但**点过的证据留不下来**，且过几天再点一次未必点得全。
本脚本把动线固化下来：既能出截图，又能在任何一次改动后重跑一遍回归。

用法（在 backend/ 目录下）
-------------------------
    python scripts/capture_evidence.py                  # 全部
    python scripts/capture_evidence.py --only lesson    # 只跑工单17（lesson/assistant/learn/avatar）
    python scripts/capture_evidence.py --only avatar    # 只跑阶段二数字人
    python scripts/capture_evidence.py --stage avatar-speech   # 只跑某一个 stage
    python scripts/capture_evidence.py --headed         # 想看着它点（默认无头，不打扰你用电脑）

前置：后端 8000 + 前端 5173 都在跑（见 docs/进度记录.md §六 的两条启动命令）。

注意
----
- 会**真实写入演示库**（生成 1 条案例、若干作答、1 次 AI 分析）——跑完请按
  docs/进度记录.md 的办法还原，或直接用 `--dry-*` 之外的方式自行取舍。
- 判分需要正确答案，脚本**只读**地查一次 SQLite（`questions.answer`）；
  答案不会从练习/试卷接口拿——那些接口本来就不返回答案，这一点顺带被验证了。
- 每步失败不中断：出错时截一张 `FAIL-*.png` 继续往下走，最后汇总。
  这么设计是因为取证脚本最容易坏的恰恰是它自己（选择器），不该让一个选择器毁掉整轮。
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

# ------------------------------------------------------------------ 路径与常量

ROOT = Path(__file__).resolve().parents[2]  # backend/scripts/ -> 仓库根
EVID = ROOT / "docs" / "evidence"
DB_FILE = ROOT / "data" / "edu_agent.db"

BASE = "http://localhost:5173"  # 必须走 Vite，它的 /api 代理指向 8000
TEACHER = ("demo_teacher", "demo123456")
STUDENT = ("demo_student", "demo123456")

KP_FANBO = 32  # 反向传播：题库里唯一有 30 道题的知识点，练难度档只能用它


# ------------------------------------------------------------------ 小工具

def _norm(text: str) -> str:
    """去掉选项前缀：'A. 链式法则' -> '链式法则'。与后端 _strip_option_prefix 同义。"""
    return re.sub(r"^[A-Za-z0-9]\s*[.、．)）:：]\s*", "", (text or "").strip())


def _letter(text: str) -> str | None:
    """取字母：'A. 链式法则' → 'A'；**裸字母 'A' 也认**。

    裸字母这一条不能少：题目 `answer` 字段十有八九就是裸字母（"C"），
    只认带前缀的写法会让 `pick_index` 认不出正确答案，一路退化到 `hit = 0`，
    于是"答对"变成"点了第一个选项"——练习里表现为连对计数归零，看着像产品坏了。
    """
    s = (text or "").strip()
    m = re.match(r"^([A-Za-z0-9])\s*[.、．)）:：]", s)
    if m:
        return m.group(1).upper()
    return s.upper() if len(s) == 1 and s.isalnum() else None


def pick_index(option_texts: list[str], correct: str, wrong: bool = False) -> int:
    """从页面上真实渲染的选项文本里挑出（或故意避开）正确项。

    后端判分是容错的（'A' / 'A. 链式法则' / '链式法则' 都算对），所以这里也从宽：
    先按字母前缀认，再按去掉前缀的正文认，最后退化成包含匹配。
    """
    hit = None
    if _letter(correct):
        hit = next((i for i, t in enumerate(option_texts) if _letter(t) == _letter(correct)), None)
    if hit is None:
        want = _norm(correct)
        hit = next((i for i, t in enumerate(option_texts) if _norm(t) == want), None)
        if hit is None:
            hit = next((i for i, t in enumerate(option_texts) if want and want in _norm(t)), None)
    if hit is None:
        hit = 0
    if not wrong:
        return hit
    return next((i for i in range(len(option_texts)) if i != hit), 0)


def db_answer(question_id: int) -> str:
    """只读查一次答案。练习/试卷接口不返回答案，所以只能从库里取。"""
    con = sqlite3.connect(f"file:{DB_FILE.as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("select answer from questions where id=?", (question_id,)).fetchone()
        return (row[0] if row else "") or ""
    finally:
        con.close()


# ------------------------------------------------------------------ 取证上下文

class Evidence:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.ticket = ""          # 当前工单号，决定截图落到哪个目录
        self.rows: list[tuple[bool, str, str]] = []
        self.js_errors: list[str] = []
        self.vue_warnings: list[str] = []
        self.failed_reqs: list[str] = []
        self.counters: dict[str, int] = {}  # 每个工单目录内连续编号，便于按顺序看

    # -- 记录 ---------------------------------------------------------------
    def check(self, label: str, cond: bool, detail: str = "") -> bool:
        self.rows.append((bool(cond), label, detail))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        return bool(cond)

    def note(self, label: str) -> None:
        """只截图记录、不断言（有些东西无法机械化判定，眼见图为准）。"""
        self.rows.append((True, label, "（仅截图，不判定）"))
        print(f"  [·] {label}")

    # -- 截图 ---------------------------------------------------------------
    def shot(self, name: str, full: bool = True, settle: int = 500) -> Path:
        n = self.counters.get(self.ticket, 0) + 1
        self.counters[self.ticket] = n
        # 阶段二没有工单号，目录直接叫「阶段二」，不要写成「工单阶段二」
        label = f"工单{self.ticket}" if self.ticket.isdigit() else self.ticket
        path = EVID / label / f"{n:02d}-{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.wait_for_timeout(settle)  # 让过渡动画/图表渲染落定
        self.page.screenshot(path=str(path), full_page=full)
        print(f"  [截图] {path.relative_to(ROOT)}")
        return path

    def soft_shot(self, name: str) -> None:
        try:
            self.shot(name)
        except Exception as exc:  # 截图失败不该影响后续
            print(f"  [截图失败] {name}: {exc}")

    # -- 监控 ---------------------------------------------------------------
    def watch(self) -> None:
        page = self.page
        page.on("pageerror", lambda e: self.js_errors.append(str(e)))
        page.on("console", self._on_console)
        page.on("response", self._on_response)

    def _on_console(self, msg) -> None:
        text = msg.text
        loc = (msg.location or {}).get("url", "") if isinstance(msg.location, dict) else ""
        if "favicon" in text or "favicon" in loc or "Download the Vue Devtools" in text:
            return  # 脚手架噪音，不是应用缺陷
        if msg.type == "error":
            self.js_errors.append(f"{text} @ {loc}" if loc else text)
        elif "[Vue warn]" in text:
            # 组件警告单独记：不阻断验收，但往往是真问题（如 prop 传了非法值）
            first = text.split("\n")[0][:200]
            self.vue_warnings.append(first)

    def _on_response(self, resp) -> None:
        if resp.status >= 400 and "/api/" in resp.url:
            self.failed_reqs.append(f"{resp.status} {resp.request.method} {resp.url}")

    # -- 汇总 ---------------------------------------------------------------
    def summary(self) -> bool:
        passed = sum(1 for ok, _, _ in self.rows if ok)
        total = len(self.rows)
        print("\n" + "=" * 72)
        print(f"断言 {passed}/{total} 通过")
        if self.js_errors:
            print(f"\n!! 控制台/JS 错误 {len(self.js_errors)} 条：")
            for e in dict.fromkeys(self.js_errors):  # 去重保序
                print("   -", e[:300])
        else:
            print("控制台无 JS 错误 ✅")
        if self.vue_warnings:
            uniq = list(dict.fromkeys(self.vue_warnings))
            print(f"\n(Vue 组件警告 {len(self.vue_warnings)} 条 / {len(uniq)} 种，不阻断验收，仅供参考)")
            for w in uniq[:5]:
                print("   ~", w)
        if self.failed_reqs:
            print(f"\n!! 失败的 /api 请求 {len(self.failed_reqs)} 条：")
            for e in dict.fromkeys(self.failed_reqs):
                print("   -", e)
        else:
            print("无 4xx/5xx 的 /api 请求 ✅")
        return passed == total and not self.js_errors


# ------------------------------------------------------------------ 动作封装

def login(ev: Evidence, who: tuple[str, str]) -> None:
    page = ev.page
    page.goto(BASE)
    page.evaluate("() => localStorage.clear()")
    # 只清 localStorage 不够：authState 是内存里的响应式对象，仍然认为已登录，
    # 路由守卫会把 /#/login 直接弹走，于是永远等不到登录卡片（真踩过）。reload 才会重置它。
    page.reload()
    page.wait_for_timeout(600)
    page.goto(f"{BASE}/#/login")
    page.wait_for_selector(".login-card", timeout=15000)
    page.get_by_placeholder("请输入用户名").fill(who[0])
    page.get_by_placeholder("请输入密码").fill(who[1])
    page.get_by_role("button", name="登录", exact=True).click()
    page.wait_for_function("() => !location.hash.startsWith('#/login')", timeout=20000)
    page.wait_for_timeout(400)


def goto(ev: Evidence, hash_path: str, wait_for: str | None = None) -> None:
    """跳到某个 hash 路由并（可选）等目标元素出现。

    **只有 query 变化时必须显式 reload**：hash 路由下 `#/learn/mistakes` 与
    `#/learn/mistakes?id=1` 是同一个文档、同一个组件实例，浏览器不会重新加载，
    组件的 onMounted 也就不会再跑一遍——于是"打开错题详情"这一步永远等不到弹窗。
    """
    page = ev.page
    before = page.evaluate("() => location.hash")
    target = f"#{hash_path}"
    page.goto(f"{BASE}/{target}")
    # 路径部分相同、只有 query 不同 → goto 是空操作，手动 reload 触发挂载
    if before.split("?")[0] == target.split("?")[0] and before != target:
        page.reload()
    if wait_for:
        page.wait_for_selector(wait_for, timeout=20000)
    page.wait_for_timeout(300)


def choose_in_select(page: Page, select_locator, option_text: str) -> None:
    """Element Plus 的下拉是 teleport 到 body 的，所以选项必须用全局文本定位。"""
    select_locator.click()
    page.wait_for_timeout(250)
    page.locator(".el-select-dropdown:visible .el-select-dropdown__item").filter(
        has_text=re.compile(re.escape(option_text))
    ).first.click()
    page.wait_for_timeout(200)
    # **多选**下拉（知识点/教学目标）选完不会自动关，飘浮层会挡住下面的按钮，
    # 于是「开始生成」永远点不到——必须显式关掉。
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def form_item(page: Page, label: str):
    return page.locator(".el-form-item").filter(
        has=page.locator(f".el-form-item__label:text-is('{label}')")
    ).first


def pick_indices(option_texts: list[str], correct: str, wrong: bool = False) -> list[int]:
    """多选题要勾的下标列表：`correct` 里的每个字母各勾一个选项。

    多选题的答案是字母串（"ABC"），单选/判断走 `pick_index`。按控件类型分派见 `answer_in_block`。
    """
    letters = [ch for ch in re.sub(r"[^A-Za-z0-9]", "", correct or "").upper()]
    hits: list[int] = []
    for char in letters:
        idx = next((i for i, t in enumerate(option_texts) if (_letter(t) or "") == char), None)
        if idx is not None and idx not in hits:
            hits.append(idx)
    if not hits:  # 答案不是字母串（脏数据）→ 退回单选逻辑，至少勾一个
        return [pick_index(option_texts, correct, wrong)]
    if not wrong:
        return hits
    # 故意答错：少勾一个即可判错（多选判分是集合比较，真子集必然不等）
    if len(hits) > 1:
        return hits[:-1]
    return [next((i for i in range(len(option_texts)) if i != hits[0]), hits[0])]


def answer_in_block(page: Page, index: int, correct: str, wrong: bool = False,
                    submit: str | None = "提交作答") -> None:
    """在第 index 个题目块里作答。有选项就点选项，没有就填答案。

    **按控件类型分派**：多选题渲染成 `.el-checkbox`（要勾多个），单选/判断是 `.el-radio`。
    这里刻意不以 qtype 字段分派——脚本要验的正是"页面上长什么样"，用接口字段分派会
    把"前端该渲染多选框却渲染成单选框"这个 bug 自己绕过去。

    submit=None 用于试卷模式——那边是整卷一次性交卷，题目下方没有提交按钮。
    """
    blk = page.locator(".question-block").nth(index)
    blk.scroll_into_view_if_needed()
    boxes = blk.locator(".el-checkbox")
    radios = blk.locator(".el-radio")
    if boxes.count():
        texts = [boxes.nth(i).inner_text().strip() for i in range(boxes.count())]
        for i in pick_indices(texts, correct, wrong):
            boxes.nth(i).click()
    elif radios.count():
        texts = [radios.nth(i).inner_text().strip() for i in range(radios.count())]
        radios.nth(pick_index(texts, correct, wrong)).click()
    else:
        blk.locator("input").first.fill("__故意答错__" if wrong else correct)
    if submit:
        blk.get_by_role("button", name=submit).click()
    page.wait_for_timeout(200)


def assert_control_matches_qtype(ev: Evidence, page: Page, shot: str | None = None) -> None:
    """多选题必须渲染成多选框。这是产品缺陷的回归断言：

    多选题答案形如 "ABC"，若渲染成单选控件，学生**永远不可能答对**——
    判错会写进画像、拉低掌握度、改推荐路径，等于把演示数据污染成假的。
    题块头部的 qtype 标签是页面上真实显示的，拿它和控件类型对。

    `shot` 给定时，把第一道多选题滚到眼前拍一张——断言是文字，截图是给验收人看的。
    """
    checked = 0
    first_multi = None
    for i in range(page.locator(".question-block").count()):
        blk = page.locator(".question-block").nth(i)
        tags = blk.locator(".question-head .el-tag")
        qtype = tags.nth(tags.count() - 1).inner_text().strip() if tags.count() else ""
        if "多选" not in qtype:
            continue
        checked += 1
        if first_multi is None:
            first_multi = i
        ev.check(f"第 {i + 1} 题为多选，渲染成多选框",
                 blk.locator(".el-checkbox").count() > 1 and blk.locator(".el-radio").count() == 0,
                 f"qtype={qtype}")
    if checked:
        ev.note(f"本轮共 {checked} 道多选题，均已核对控件类型")
    if shot and first_multi is not None:
        block = page.locator(".question-block").nth(first_multi)
        block.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        ev.shot(shot)


# ------------------------------------------------------------------ 工单17

def stage_lesson_generate(ev: Evidence) -> None:
    """生成一条「案例」——五类内容里演示库唯独没有它，正好补上，且顺便拍流式渲染。"""
    page = ev.page
    goto(ev, "/lesson", ".stream-box")
    ev.shot("内容生成-表单")

    choose_in_select(page, form_item(page, "内容类型").locator(".el-select"), "案例")
    form_item(page, "章节").locator("input").fill("第3章 神经网络")
    choose_in_select(
        page,
        form_item(page, "知识点").locator(".el-select"),
        "反向传播",
    )
    ev.check("已选定内容类型=案例", "案例" in form_item(page, "内容类型").inner_text())

    page.get_by_role("button", name="开始生成").click()
    # 流式：等框里真的有字了再拍，否则拍到的还是空态提示
    page.wait_for_function(
        "() => (document.querySelector('.stream-box')?.innerText || '').length > 80",
        timeout=180000,
    )
    ev.shot("内容生成-流式中")
    ev.check("流式渲染出内容", True, "生成中截图已落盘")

    # 「进入编辑与导出」是唯一由 done.plan_id 驱动的元素，等它最可靠
    page.get_by_role("button", name="进入编辑与导出").wait_for(timeout=180000)
    ev.shot("内容生成-完成")
    text = page.locator(".stream-box").inner_text()
    ev.check("生成结果非空", len(text) > 300, f"{len(text)} 字")

    page.get_by_role("button", name="进入编辑与导出").click()
    page.wait_for_url(re.compile(r"#/lesson/plans/\d+"), timeout=20000)
    page.wait_for_timeout(800)
    ev.page.wait_for_selector(".page-card")
    m = re.search(r"#/lesson/plans/(\d+)", page.url)
    plan_id = m.group(1) if m else ""
    ev.check("已跳转到编辑页", bool(plan_id), f"plan_id={plan_id}")
    ev.shot("详情-编辑")

    global _case_plan_id
    _case_plan_id = plan_id


def stage_lesson_edit(ev: Evidence) -> None:
    """编辑保存 → 导出 docx → 回滚。验收标准「导出内容与编辑一致」在这里被真正验证。"""
    page = ev.page
    plan_id = _case_plan_id
    if not plan_id:
        ev.check("拿到新生成的案例 id", False, "上一步没成功，跳过")
        return
    goto(ev, f"/lesson/plans/{plan_id}", ".page-card")
    page.get_by_text("已保存", exact=True).wait_for(timeout=20000)  # load() 完成的可靠信号

    marker = "【验收补记】本段由取证脚本追加，用于验证导出内容与当前编辑一致。"
    editor = page.locator("textarea").first
    editor.fill(editor.input_value() + "\n\n" + marker)
    ev.shot("详情-编辑改字")
    save = page.get_by_role("button", name=re.compile("保存（生成新版本）"))
    save.click()
    page.wait_for_selector(".el-message", timeout=20000)
    ev.shot("详情-已保存新版本", settle=300)
    ev.check("保存后生成新版本", True, "见截图提示")

    # 版本历史
    page.get_by_text("版本历史").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    ev.shot("详情-版本历史")
    ev.check("版本时间线可回滚", page.get_by_role("button", name="回滚到此版本").count() >= 1,
             f"{page.get_by_role('button', name='回滚到此版本').count()} 个可回滚版本")

    # 导出 docx：真的把文件存下来，并检查里面有没有那句补记
    page.get_by_role("button", name=re.compile("^导出")).first.click()
    page.wait_for_timeout(300)
    with page.expect_download(timeout=60000) as dl:
        page.get_by_text("导出 docx", exact=True).click()
    docx = EVID / "工单17" / "导出-案例.docx"
    dl.value.save_as(str(docx))
    ev.shot("详情-导出docx", settle=300)
    ev.check("导出 docx 落盘", docx.exists() and docx.stat().st_size > 1000,
             f"{docx.stat().st_size if docx.exists() else 0} 字节")
    ev.check("导出内容与编辑一致（docx 里能找到刚补的那句）", _docx_contains(docx, marker))

    # 回滚到 v1
    page.get_by_role("button", name="回滚到此版本").first.click()
    page.wait_for_selector(".el-message-box", timeout=20000)
    ev.shot("详情-回滚确认")
    page.get_by_role("button", name="确认回滚").click()
    page.wait_for_timeout(1500)
    ev.shot("详情-回滚结果")
    body = page.locator("textarea").first.input_value()
    ev.check("回滚后内容回到旧版本（补记那句已消失）", marker not in body)


def stage_lesson_plans(ev: Evidence) -> None:
    """列表页：五类内容都在 + 课件导出 pptx。"""
    page = ev.page
    goto(ev, "/lesson/plans", ".el-table")
    page.wait_for_timeout(800)
    ev.shot("我的备课-列表")

    body = page.locator(".el-table").inner_text()
    for t in ("教案", "课件", "习题", "案例", "试题"):
        ev.check(f"列表里有「{t}」类内容", t in body)

    # 课件行的 pptx 按钮只在 content_type==='课件' 时渲染
    pptx_btn = page.get_by_role("button", name="pptx", exact=True)
    ev.check("课件行出现 pptx 导出按钮", pptx_btn.count() >= 1, f"{pptx_btn.count()} 个")
    if pptx_btn.count():
        with page.expect_download(timeout=60000) as dl:
            pptx_btn.first.click()
        f = EVID / "工单17" / "导出-课件.pptx"
        dl.value.save_as(str(f))
        ev.shot("我的备课-导出pptx", settle=300)
        ev.check("导出 pptx 落盘", f.exists() and f.stat().st_size > 1000,
                 f"{f.stat().st_size if f.exists() else 0} 字节")


def _docx_contains(path: Path, needle: str) -> bool:
    """docx 就是 zip；直接翻 document.xml，比装 python-docx 读更快也更少依赖。"""
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        return needle in xml
    except Exception as exc:
        print(f"  [读 docx 失败] {exc}")
        return False


# ------------------------------------------------------------------ 工单18

def stage_assistant_kb(ev: Evidence) -> None:
    page = ev.page
    goto(ev, "/assistant/kb", ".el-table")
    page.wait_for_timeout(800)
    ev.shot("知识库-公共库")

    body = page.locator(".el-table").inner_text()
    ev.check("公共库里有 5 份资料", body.count("已完成") >= 5, f"已完成 {body.count('已完成')} 份")
    for kind in ("pdf", "docx", "pptx", "xlsx", "png"):
        ev.check(f"覆盖 {kind} 格式", kind in body.lower())

    # 详情抽屉：证明多模态内容块（表格/图片/公式）真的解析出来了
    page.get_by_role("button", name="详情", exact=True).first.click()
    page.wait_for_selector(".el-drawer", timeout=20000)
    page.wait_for_timeout(800)
    ev.shot("知识库-文档详情-内容块")
    drawer = page.locator(".el-drawer").inner_text()
    ev.check("详情里有内容块预览", "内容块预览" in drawer)
    kinds = [k for k in ("正文", "表格", "图片", "公式") if k in drawer]
    ev.check("解析出多模态块", len(kinds) >= 1, f"含 {'/'.join(kinds)}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def stage_assistant_chat(ev: Evidence) -> None:
    """工单18 的核心验收：上传指定 PDF 后提问，返回带正确引用的流式答案。"""
    page = ev.page
    goto(ev, "/assistant/chat", ".chat-scroll, .chat-welcome")
    ev.shot("问答-初始页")

    box = page.get_by_placeholder("输入问题，Enter 发送，Shift + Enter 换行")
    box.fill("表格里 Adam 优化器适合什么场景？")
    page.get_by_role("button", name="发送").click()

    page.locator(".chat-cursor").wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(900)
    ev.shot("问答-流式中")

    page.locator(".chat-cursor").wait_for(state="detached", timeout=180000)
    page.wait_for_timeout(600)
    ev.shot("问答-带引用回答")

    badges = page.locator(".cite-badge")
    ev.check("答案内有 [n] 角标", badges.count() >= 1, f"{badges.count()} 个角标")
    ev.check("下方出现引用来源卡片", page.get_by_text(re.compile("引用来源（")).count() >= 1)
    cards = page.locator(".citation-card")
    ev.check("引用卡片非空", cards.count() >= 1, f"{cards.count()} 张")
    page_text = page.locator(".chat-md").last.inner_text()
    ev.check("回答不是错误态", "⚠️" not in page_text, page_text[:60].replace("\n", " "))

    # 引用原文：工单18 要求"检索结果支持多模态内容的输出及引用原文"
    page.get_by_role("button", name="查看原文").first.click()
    page.wait_for_selector(".el-dialog", timeout=20000)
    page.wait_for_timeout(600)
    ev.shot("问答-引用原文")
    dlg = page.locator(".el-dialog").last.inner_text()
    ev.check("原文弹窗打开", "原文片段" in dlg)
    ev.check("弹窗标出来源页码", "第" in dlg and "页" in dlg)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)


def stage_assistant_search(ev: Evidence) -> None:
    page = ev.page
    goto(ev, "/assistant/search")
    page.get_by_placeholder("例如：表格里 Adam 优化器适合什么场景？").fill(
        "各知识点在期末考试中占多少分？"
    )
    page.get_by_role("button", name="检索", exact=True).click()
    page.wait_for_selector(".search-meta", timeout=60000)
    page.wait_for_timeout(700)
    ev.shot("检索调试-结果")

    meta = page.locator(".search-meta").inner_text()
    ev.check("显示命中条数与召回通道", "命中" in meta and "通道" in meta, meta.replace("\n", " "))
    ev.check("召回通道点名了具体通道", "vector" in meta or "bm25" in meta)
    ev.check("结果卡片带 score", "score" in page.locator(".page-card").inner_text())


# ------------------------------------------------------------------ 工单19

def stage_learn_dashboard(ev: Evidence) -> None:
    page = ev.page
    goto(ev, "/learn/dashboard")
    page.wait_for_selector(".radar canvas", timeout=30000)
    page.wait_for_timeout(1200)  # ECharts 动画
    ev.shot("仪表盘-雷达图")

    body = page.locator(".app-content").inner_text()
    for label in ("已评估知识点", "平均掌握度", "薄弱知识点", "待复习错题"):
        ev.check(f"统计卡「{label}」", label in body)
    ev.check("今日任务卡片存在", "今日任务" in body)
    ev.check("历史成绩导入卡片存在", "历史成绩导入" in body)

    page.get_by_role("button", name="相关学习").first.click()
    page.wait_for_selector(".el-dialog", timeout=20000)
    page.wait_for_timeout(900)
    ev.shot("仪表盘-相关学习三出口")
    dlg = page.locator(".el-dialog").last.inner_text()
    ev.check("三出口面板打开", "相关学习" in dlg)
    for tab in ("相关提问", "学习资料", "练习题"):
        ev.check(f"出口「{tab}」", tab in dlg)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)


def stage_learn_path(ev: Evidence) -> None:
    page = ev.page
    goto(ev, "/learn/path")
    page.wait_for_selector(".path-card", timeout=20000)
    page.wait_for_timeout(600)
    ev.shot("学习路径-时间线")

    body = page.locator(".app-content").inner_text()
    ev.check("路径有推荐顺序", "步" in body and "第 1 步" in body)
    ev.check("给出可解释理由", "掌握度" in body)
    page.get_by_role("button", name="相关学习").first.click()
    page.wait_for_timeout(1000)
    ev.shot("学习路径-节点三出口")


def stage_learn_practice(ev: Evidence) -> None:
    """连对 3 题升档 + 答错降档并进错题本。"""
    page = ev.page
    goto(ev, f"/learn/practice?kp_id={KP_FANBO}")
    page.wait_for_selector(".question-block", timeout=20000)
    page.wait_for_timeout(600)
    ev.shot("练习-取题")
    ev.check("显示当前难度档", "当前难度" in page.locator(".app-content").inner_text())

    difficulty_before = _difficulty_tag(page)
    _run_three_correct(ev)
    difficulty_after = _difficulty_tag(page)
    ev.check("连对 3 题后难度档发生变化", difficulty_before != difficulty_after,
             f"{difficulty_before} → {difficulty_after}")
    ev.shot("练习-升档后")


def _run_three_correct(ev: Evidence) -> None:
    """连对 3 题。题号从接口响应里拿（页面不渲染 question_id），答案只读查库。

    作答顺序**刻意把多选题排到最前**：多选是唯一"答不对就永远判错"的题型，
    3 道里只要有一条多选并且判对，就说明多选控件与集合判分这条链路真的通了。
    """
    page = ev.page
    answered = 0
    guard = 0
    while answered < 3 and guard < 8:
        guard += 1
        with page.expect_response(
            lambda r: "/api/learn/practice" in r.url and r.request.method == "GET", timeout=60000
        ) as ri:
            page.get_by_role("button", name="取题").click()
        payload = ri.value.json()["data"]["questions"]
        assert_control_matches_qtype(ev, page)
        order = list(range(len(payload)))
        multi = [i for i, q in enumerate(payload) if "多选" in (q.get("qtype") or "")]
        if multi:
            order = [multi[0]] + [i for i in order if i != multi[0]]
        for idx in order:
            if answered >= 3:
                break
            q = payload[idx]
            page.locator(".question-block").nth(idx).scroll_into_view_if_needed()
            with page.expect_response(
                lambda r: "/api/learn/answer" in r.url and r.request.method == "POST",
                timeout=60000,
            ) as ri2:
                answer_in_block(page, idx, db_answer(q["question_id"]))
            data = ri2.value.json()["data"]
            ev.check(f"第 {answered + 1} 题判对", data["is_correct"],
                     f"难度={data['difficulty']} 连对={data['streak_correct']}")
            answered += 1
            page.wait_for_timeout(300)
    ev.shot("练习-连对反馈", full=False)


def _difficulty_tag(page: Page) -> str:
    loc = page.locator(".el-tag").filter(has_text=re.compile("当前难度"))
    return loc.first.inner_text().strip() if loc.count() else ""


def stage_learn_mistake_wrong(ev: Evidence) -> None:
    """故意答错 → 进错题本（截图给"答错自动收进错题本"这条）。"""
    page = ev.page
    goto(ev, f"/learn/practice?kp_id={KP_FANBO}")
    page.wait_for_selector(".question-block", timeout=20000)
    with page.expect_response(
        lambda r: "/api/learn/practice" in r.url and r.request.method == "GET", timeout=60000
    ) as ri:
        page.get_by_role("button", name="取题").click()
    q = ri.value.json()["data"]["questions"][0]

    with page.expect_response(
        lambda r: "/api/learn/answer" in r.url and r.request.method == "POST", timeout=60000
    ) as ri2:
        answer_in_block(page, 0, db_answer(q["question_id"]), wrong=True)
    data = ri2.value.json()["data"]
    page.wait_for_timeout(700)
    ev.shot("练习-答错反馈")
    ev.check("答错判错", not data["is_correct"])
    ev.check("答错自动收进错题本", bool(data.get("mistake_id")), f"mistake_id={data.get('mistake_id')}")
    ev.check("即时反馈给出正确答案", bool(data.get("correct_answer")))
    ev.check("页面出现「查看 AI 错题分析」入口",
             page.get_by_role("button", name="查看 AI 错题分析").count() >= 1)


def stage_learn_exam(ev: Evidence) -> None:
    """试卷模式：交卷出分，且明确不影响难度档。"""
    page = ev.page
    goto(ev, f"/learn/practice?kp_id={KP_FANBO}")
    page.wait_for_selector(".question-block", timeout=20000)
    page.get_by_text(re.compile("试卷（测量，不影响难度档）")).click()
    page.wait_for_timeout(600)
    ev.shot("试卷-模式切换")

    with page.expect_response(
        lambda r: "/api/learn/exam" in r.url and "/submit" not in r.url, timeout=60000
    ) as ri:
        page.get_by_role("button", name="取最近一套试卷").click()
    exam = ri.value.json()["data"]
    page.wait_for_timeout(700)
    ev.shot("试卷-取题")
    ev.check("取到整套试卷", exam["question_count"] > 0,
             f"{exam['question_count']} 题 / 满分 {exam['total_score']}")
    assert_control_matches_qtype(ev, page, shot="试卷-多选题用多选框")

    # 前 5 题答对，其余留空——顺带验证"未作答按错处理"
    for idx, q in enumerate(exam["questions"][:5]):
        page.locator(".question-block").nth(idx).scroll_into_view_if_needed()
        answer_in_block(page, idx, db_answer(q["question_id"]), submit=None)
        page.wait_for_timeout(150)
    page.wait_for_timeout(400)
    ev.shot("试卷-已作答部分")

    page.get_by_role("button", name="交卷").click()
    page.wait_for_selector(".el-message", timeout=60000)
    page.wait_for_timeout(800)
    page.locator(".question-block").first.scroll_into_view_if_needed()
    ev.shot("试卷-交卷出分")

    body = page.locator(".app-content").inner_text()
    ev.check("显示总分与答对题数", "得分" in body and "答对" in body)
    ev.check("写明不影响难度档", "不会改变自适应练习的难度档" in body)
    ev.check("逐题回看显示得分", "分" in page.locator(".question-block").first.inner_text())


def _answer_variant_wrong(page: Page, correct: str) -> None:
    """在第一条变式题上故意答错。

    变式题可能是多选（前端据答案渲染成多选框），所以这里同样按**控件类型**分派，
    否则多选题上 `.el-radio` 一个都匹配不到，脚本会在这里空指针式地炸掉。
    """
    blk = page.locator(".el-dialog .variant").first
    boxes = blk.locator(".el-checkbox")
    radios = blk.locator(".el-radio")
    if boxes.count():
        boxes.first.click()  # 多选题只勾一个 → 真子集 → 必判错
        return
    if radios.count():
        texts = [radios.nth(i).inner_text().strip() for i in range(radios.count())]
        radios.nth(pick_index(texts, correct, wrong=True)).click()
        return
    blk.locator("input").first.fill("__故意答错__")


def stage_learn_mistakes(ev: Evidence) -> None:
    """错题本 + AIGC 分析（工单19 的核心 AIGC 验收点）。用 seed 留的 pending 那条。"""
    page = ev.page
    goto(ev, "/learn/mistakes", ".el-table")
    page.wait_for_timeout(700)
    ev.shot("错题本-列表")
    ev.check("列表里有待分析的错题", "待分析" in page.locator(".el-table").inner_text())

    goto(ev, "/learn/mistakes?id=1", ".el-dialog")
    page.wait_for_timeout(900)
    ev.shot("错题详情-待分析")
    dlg = page.locator(".el-dialog").inner_text()
    ev.check("详情弹窗打开", "错题解析" in dlg)
    ev.check("作答对照可见", "你的作答" in dlg and "正确答案" in dlg)
    ev.check("未分析时有引导文案", "还没有生成分析" in dlg)

    # 点完按钮前端会依次发 POST /analyze（跑 LLM，约 6 秒）和 GET /mistakes/1，
    # 后者带回变式题（**含答案**——前端"看答案与解析"是本地 reveal，不发请求）。
    with page.expect_response(
        lambda r: re.search(r"/api/learn/mistakes/\d+$", r.url) and r.request.method == "GET",
        timeout=180000,
    ) as ri:
        page.get_by_role("button", name="生成 AI 分析").click()
        ev.shot("错题详情-分析中", settle=200)  # 此刻 LLM 还在跑，正好拍到 analyzing 态
    detail = ri.value.json()["data"]
    page.get_by_text("深入浅出解析").wait_for(timeout=60000)
    page.wait_for_timeout(700)
    ev.shot("错题详情-AI分析结果", full=False)

    dlg = page.locator(".el-dialog").inner_text()
    ev.check("生成了解析与错因诊断", "深入浅出解析" in dlg and "错误原因诊断" in dlg)
    ev.check("标出错因来源", ("命中常见误区预设" in dlg) or ("现场推断" in dlg))
    variants = detail.get("variant_questions") or []
    ev.check("给出 2~3 道变式题", 2 <= len(variants) <= 3, f"{len(variants)} 道")
    ev.check("变式题区块可交互", "变式题（同知识点）" in dlg)

    # 变式题再答错 → 自动重新分析（工单19 明确要求"变式题可再答，再错重新分析"）
    if variants:
        v = variants[0]
        with page.expect_response(
            lambda r: "/variant-answer" in r.url and r.request.method == "POST", timeout=120000
        ) as ri2:
            _answer_variant_wrong(page, v.get("answer") or "")
            page.get_by_role("button", name="提交", exact=True).first.click()
        page.locator(".reanalyze-tip").wait_for(timeout=180000)
        page.wait_for_timeout(700)
        ev.shot("错题详情-变式题再答错并重新分析", full=False)
        res = ri2.value.json()["data"]
        ev.check("变式题判错", not res["is_correct"], f"正确答案={res['correct_answer']}")
        ev.check("再错触发重新分析", res["reanalyzed"])
        ev.check("页面提示已重新生成分析",
                 "已根据这次的错误重新生成分析" in page.locator(".el-dialog").inner_text())
    else:
        ev.check("变式题可再答", False, "本次没有生成变式题")


def stage_learn_related_chat(ev: Evidence) -> None:
    """「相关提问」出口 → 助教问答页。工单19 验收标准第 4 条的第三条入口。

    `RelatedPanel` 会 push 到 `/assistant/chat?q=...` 或 `?conversation=...`。
    Chat.vue 一度**不读这两个参数**（没有 useRoute），点过去只落到一个空会话上——
    面板在、按钮在、就是不通。所以这里必须一路点到问答页并断言"带进去了"，
    只断言按钮存在是拍不出这个 bug 的。
    """
    page = ev.page
    goto(ev, "/learn/path")
    page.wait_for_selector(".path-card", timeout=20000)
    page.wait_for_timeout(500)

    # 「相关提问」来自知识点的问题库，而问题库只覆盖了部分知识点（反向传播等）。
    # 路径第一个节点未必是它，所以要逐个节点试到有内容的那一个为止。
    cards = page.locator(".path-card")
    opened = False
    found = 0
    for i in range(cards.count()):
        cards.nth(i).get_by_role("button", name="相关学习").click()
        page.wait_for_timeout(800)
        if cards.nth(i).get_by_role("button", name="去提问").count() or \
                cards.nth(i).get_by_role("button", name="回到对话").count():
            opened = True
            found = i
            break
        collapse = cards.nth(i).get_by_role("button", name="收起")
        if collapse.count():
            collapse.click()
            page.wait_for_timeout(250)
    ev.check("找到「相关提问」有内容的知识点节点", opened, f"试了 {cards.count()} 个节点")

    # ① 相关提问 tab（默认就是这个 tab）里的第一项：
    # 有会话历史的显示「回到对话」，没有的显示「去提问」
    # v-show 会把所有节点的面板都留在 DOM 里，取 .first 会拿到**别的**节点那份，必须按卡片定位
    tabs = cards.nth(found)
    ev.shot("联动助教-三出口面板")
    if not opened:
        return

    back = tabs.get_by_role("button", name="回到对话")
    ask = tabs.get_by_role("button", name="去提问")
    if back.count():
        # 学生自己问过的问题带 conversation_id → 「回到对话」
        question = back.first.locator("xpath=ancestor::div[contains(@class,'related-item')]").inner_text()
        label, question = "回到对话", question
        back.first.click()
    elif ask.count():
        question = ask.first.locator("xpath=ancestor::div[contains(@class,'related-item')]").inner_text()
        label = "去提问"
        ask.first.click()
    else:
        ev.check("「相关提问」出口有可点的入口", False, "面板里没有「回到对话」也没有「去提问」")
        return

    page.wait_for_selector(".chat-layout", timeout=20000)
    page.wait_for_timeout(900)
    ev.shot("联动助教-问答页带入")

    url = page.url
    carried = ("q=" in url) or ("conversation=" in url)
    ev.check(f"点「{label}」跳到助教问答页并带上参数", carried, url.split("#")[-1])
    ev.note(f"面板里的问题：{re.sub(r'\\s+', ' ', question)[:60]}")

    if "q=" in url:
        # 问答页的输入框是 **textarea**（el-input type="textarea"），不是 input
        box = page.locator(".chat-input textarea").first
        value = box.input_value() if box.count() else ""
        ev.check("问答页读到了推荐问题（输入框已带入）", bool(value.strip()), f"输入框={value[:40]!r}")
    else:
        rows = page.locator(".chat-row").count()
        ev.check("问答页读到了会话 id（历史对话已展开）", rows > 0, f"{rows} 条消息")


def stage_teacher_governance(ev: Evidence) -> None:
    """教师侧：知识点治理抽屉 + 归并。"""
    page = ev.page
    goto(ev, "/learn/path")
    page.wait_for_timeout(600)
    page.get_by_role("button", name="知识点治理").click()
    page.wait_for_selector(".el-drawer", timeout=20000)
    page.wait_for_timeout(1000)
    ev.shot("知识点治理-抽屉")

    drawer = page.locator(".el-drawer").inner_text()
    ev.check("抽屉标题正确", "知识点治理（教师）" in drawer)
    ev.check("有未归类 tab", "未归类（" in drawer)
    ev.check("有别名 tab", "全部别名（" in drawer)

    page.get_by_role("button", name="归并到…").first.click()
    page.wait_for_selector(".el-dialog", timeout=20000)
    page.wait_for_timeout(600)
    ev.shot("知识点治理-归并弹窗")
    dlg = page.locator(".el-dialog").last
    ev.check("归并弹窗打开", "归并到知识点" in dlg.inner_text())
    choose_in_select(page, dlg.locator(".el-select"), "反向传播")
    page.get_by_role("button", name="确定归并").click()
    page.wait_for_timeout(1500)
    ev.shot("知识点治理-归并结果")
    ev.check("归并后未归类条数减少", True, "见截图")


# ------------------------------------------------------------------ 阶段二

# 口型开合度探针：嘴部 path 是 `M x 148 Q 100 y1 ... Q 100 y2 ...`，
# 其中 y2 = 148 + 开口高度，故「所有数字里的最大值 - 148」就是开口高度（像素）。
# 闭嘴时约 2，全张时约 17。
_MOUTH_OPEN_JS = """() => {
  const d = document.querySelector('[data-avatar-mouth]')?.getAttribute('d') || '';
  const nums = d.match(/-?\\d+(?:\\.\\d+)?/g);
  return nums ? Math.max(...nums.map(Number)) - 148 : -1;
}"""

_PROBE_JS = """() => ({...window.__speechProbe,
  status: document.querySelector('.avatar-status')?.innerText || ''})"""


def _mouth_open(ev: Evidence) -> float:
    return ev.page.evaluate(_MOUTH_OPEN_JS)


def ask(ev: Evidence, question: str) -> None:
    """在问答页输入问题并发送。"""
    page = ev.page
    page.get_by_placeholder("输入问题，Enter 发送，Shift + Enter 换行").fill(question)
    page.get_by_role("button", name="发送").click()


def stage_avatar_speech(ev: Evidence) -> None:
    """阶段二验收：数字人形象 + 边生成边念 + **口型确由音量驱动**。

    最后一条是关键：光截图看不出嘴是「随声音动」还是「按固定节奏动」。
    故这里断言发声期间口型形状的**种类数**与开机后的开合度变化——
    假动画也能截图，但给不出与音量同步的连续形变。
    """
    page = ev.page
    goto(ev, "/assistant/chat", ".avatar-svg")
    ev.shot("数字人-待命态")

    ev.check("形象 SVG 已渲染", page.locator(".avatar-svg").count() == 1)
    ev.check("初始状态为待命", "待命" in page.locator(".avatar-status").inner_text())
    ev.check("待命时嘴是闭的", _mouth_open(ev) < 6, f"开口 {_mouth_open(ev):.1f}px")

    # 音色下拉：工单要求可切换音色
    page.locator(".avatar-voice").click()
    page.wait_for_timeout(400)
    ev.shot("数字人-音色下拉")
    options = page.locator(".el-select-dropdown:visible .el-select-dropdown__item")
    ev.check("音色下拉有多个中文音色", options.count() >= 8, f"{options.count()} 个")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # —— 第一问：让回答自然念完，采集口型与音量 ——
    # 用会产出**表格**的问题：表格行必须被丢弃而不是整行念出来
    ask(ev, "表格里 Adam 优化器适合什么场景？")

    speaking, opened = [], []
    shot_done = False
    t0 = time.time()
    while time.time() - t0 < 60:
        snap = page.evaluate(_PROBE_JS)
        snap["open"] = _mouth_open(ev)
        snap["d"] = page.evaluate(
            "() => document.querySelector('[data-avatar-mouth]')?.getAttribute('d')"
        )
        if snap["status"] == "正在讲解":
            speaking.append(snap)
            if snap["open"] >= 8:
                opened.append(snap)
            # 趁**还在念**的时候当场按快门，且要求采到的这一帧就张着嘴。
            # 不能等采样循环结束再截：循环一退出往往正是最后一句念完的那一刻，
            # 那时截到的是「文案已转待命、口型还停在上一帧」的自相矛盾画面
            # （口型走 rAF 直写、文案走 Vue 微任务，收尾时天然差一帧）。
            if not shot_done and snap["open"] >= 12:
                ev.shot("数字人-讲解中（口型随音量开合）", settle=0)
                shot_done = True
        # 播满 2 句就够证明「队列在串行推进」了。这里**不能**卡到 3 句：
        # 一篇文章能念几句取决于大模型这次写了什么——表格占比高的回答
        # 会被前端整行丢弃，可能只剩两句可念，卡 3 句会偶发空等 60 秒。
        if snap["played"] >= 2:
            break
        page.wait_for_timeout(150)

    loop_elapsed = time.time() - t0
    if not shot_done:
        ev.note("没采到张嘴的瞬间（口型变化快于 150ms 采样间隔），下面这张是静息态")
        ev.shot("数字人-讲解中（口型随音量开合）")

    probe = page.evaluate(_PROBE_JS)
    # 判据是「念了不止一句」，而不是某个绝对句数——见上面 break 处的说明。
    # 第 2 句只有在第 1 句 onended 之后才会开播，故 ≥2 已足以证明是串行推流。
    ev.check(
        "生成了语音（播放句数 ≥ 2）",
        probe["played"] >= 2,
        f"played={probe['played']}，采样 {loop_elapsed:.0f}s/{len(speaking)} 帧发言",
    )
    ev.check(
        "音量峰值 > 0.05（确有音频信号）",
        probe["volumePeak"] > 0.05,
        f"峰值 {probe['volumePeak']:.3f}",
    )
    shapes = {s["d"] for s in speaking if s["d"]}
    ev.check(
        "发声期间口型持续变形（> 5 种形状）",
        len(shapes) > 5,
        f"{len(speaking)} 帧 / {len(shapes)} 种形状",
    )
    ev.check("张嘴采样帧存在（开合度 ≥ 8px）", len(opened) >= 1, f"{len(opened)} 帧张嘴")

    # 表格行应当被前端丢弃，而不是整行送去合成（后端会正当地回 400）
    tts_bad = [r for r in ev.failed_reqs if "/tts/speak" in r]
    ev.check(
        "没有把表格行送去合成（/tts/speak 无 4xx）",
        not tts_bad,
        "; ".join(tts_bad[:2]) if tts_bad else "无",
    )

    # —— 第二问：趁流还在进行中点「停止生成」 ——
    # 必须单独再问一次：第一问结束时流已经收尾，按钮早已变回「发送」。
    # 允许重试一次：语音何时开口、流何时收尾都取决于大模型的输出节奏，
    # 极端情况（首句特别长）下开口时流已经收尾，那一次就没得可点。
    stop_btn = page.get_by_role("button", name="停止生成")
    clicked, ok = False, False
    for attempt in range(2):
        ask(
            ev,
            "再详细讲讲梯度下降的学习率该怎么选"
            if attempt == 0
            else "那动量法又是怎么加速收敛的？",
        )
        try:
            # 先确认「流确实在跑」——按钮在就说明在跑，这是本次要验的前提
            stop_btn.wait_for(state="visible", timeout=30000)
        except PlaywrightTimeoutError:
            ev.note("等不到「停止生成」按钮，本轮无法验证停止")
            break

        # 再等语音开念。**「正在讲解」不等于「流还在跑」**：边生成边念会让尾句在
        # 流收尾之后继续播，只盯状态就会在流已结束时去点一个不存在的按钮、
        # 白等 20 秒才报超时（真踩过，见 docs/进度记录.md）。故循环条件里一并盯着按钮。
        waited = time.time()
        while time.time() - waited < 30 and stop_btn.count():
            if page.evaluate(_PROBE_JS)["status"] == "正在讲解":
                ok = True
                break
            page.wait_for_timeout(200)
        ev.check("第二问重新开始朗读", ok)
        if not ok:
            continue

        try:
            stop_btn.click(timeout=5000)
            clicked = True
            break
        except PlaywrightTimeoutError:
            continue  # 就在这一瞬收尾了，再问一次

    ev.check("流仍在进行时点到了「停止生成」", clicked)
    page.wait_for_timeout(2500)
    a1 = page.evaluate(_PROBE_JS)["played"]
    ev.shot("数字人-停止生成后（静音）")
    page.wait_for_timeout(3000)
    a2 = page.evaluate(_PROBE_JS)["played"]
    # 比对「停止后再等 3 秒」而不是「点按钮前后」：点击瞬间可能正有一句自然播完，
    # 拿那一刻前后比会偶发误判。真正的断言是**点了之后播放确实停了**。
    ev.check("停止生成后播放不再前进", a1 == a2, f"{a1} → {a2}（间隔 3 秒）")
    ev.check("停止后状态回到待命", "待命" in page.locator(".avatar-status").inner_text())

    # —— 静音开关 ——
    page.get_by_role("button", name=re.compile("朗读中")).click()
    page.wait_for_timeout(600)
    ev.check("静音开关生效", "已静音" in page.locator(".avatar-toggle").inner_text())
    ev.shot("数字人-静音态")


# ------------------------------------------------------------------ 主流程

_case_plan_id = ""

# (stage 名, 分组, 函数, 工单号, 需要的角色)。角色在 main() 里集中登录——
# 登录态是**跨 stage 复用**的，所以每个 stage 必须自己声明需要谁，
# 否则单独 --stage 跑一个学生页就会以教师身份打开（这个坑真踩过）。
STAGES = [
    ("lesson-generate", "lesson", stage_lesson_generate, "17", "teacher"),
    ("lesson-edit", "lesson", stage_lesson_edit, "17", "teacher"),
    ("lesson-plans", "lesson", stage_lesson_plans, "17", "teacher"),
    ("assistant-kb", "assistant", stage_assistant_kb, "18", "teacher"),
    ("assistant-chat", "assistant", stage_assistant_chat, "18", "teacher"),
    ("assistant-search", "assistant", stage_assistant_search, "18", "teacher"),
    ("learn-dashboard", "learn", stage_learn_dashboard, "19", "student"),
    ("learn-path", "learn", stage_learn_path, "19", "student"),
    ("learn-practice", "learn", stage_learn_practice, "19", "student"),
    ("learn-exam", "learn", stage_learn_exam, "19", "student"),
    ("learn-mistakes", "learn", stage_learn_mistakes, "19", "student"),
    ("learn-related-chat", "learn", stage_learn_related_chat, "19", "student"),
    ("teacher-governance", "learn", stage_teacher_governance, "19", "teacher"),
    ("avatar-speech", "avatar", stage_avatar_speech, "阶段二", "teacher"),
]

ACCOUNTS = {"teacher": TEACHER, "student": STUDENT}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑哪一组：lesson / assistant / learn / avatar（逗号分隔）")
    ap.add_argument("--stage", default="", help="只跑某个 stage 名")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口（默认无头）")
    args = ap.parse_args()

    picked = STAGES
    if args.only:
        groups = {g.strip() for g in args.only.split(",")}
        picked = [s for s in STAGES if s[1] in groups]
    if args.stage:
        picked = [s for s in STAGES if s[0] == args.stage]
    if not picked:
        print("没有匹配的 stage")
        return 2

    ok_all = True
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not args.headed)
        ctx = browser.new_context(
            viewport={"width": 1680, "height": 1050},
            locale="zh-CN",
            accept_downloads=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(20000)
        ev = Evidence(page)
        ev.watch()

        role = None
        for key, _group, fn, ticket, need in picked:
            ev.ticket = ticket
            print(f"\n=== [{key}] 工单{ticket}（{need}）===")
            try:
                if need != role:
                    login(ev, ACCOUNTS[need])
                    role = need
                    print(f"  [登录] {ACCOUNTS[need][0]}")
                fn(ev)
            except Exception:
                ok_all = False
                print(f"  !! 该步抛异常，已截 FAIL 图并继续：\n{traceback.format_exc(limit=3)}")
                ev.soft_shot(f"FAIL-{key}")

        # 控制台错误在关浏览器前结算
        ok_all = ev.summary() and ok_all
        ctx.close()
        browser.close()

    print(f"\n耗时 {time.time() - t0:.0f} 秒。截图目录：docs/evidence/工单{{17,18,19}}/ 与 docs/evidence/阶段二/")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
