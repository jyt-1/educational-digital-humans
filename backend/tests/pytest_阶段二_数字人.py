# [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— TTS 语音合成用例
"""阶段二语音合成测试：Markdown 清洗、provider 分派、磁盘缓存、鉴权与降级。

**本文件绝不联网**。Edge-TTS 是外部服务，测试一旦真连就会受网络与代理影响而抖动，
故统一 monkeypatch `tts._synthesize_edge` 或 `edge_tts.Communicate` 为假实现。
真实链路的手工冒烟另做（见 docs/进度记录.md 阶段二一节）。

阶段二无对应工单号，源文件头注释按 CLAUDE.md §2.2 的精神用 `[阶段二]` 标识
（完整项目名与任务名仍保留）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import tts

FAKE_AUDIO = b"ID3fake-mp3-bytes"


# ---------------------------------------------------------------- 夹具

@pytest.fixture
def fake_edge(monkeypatch):
    """把本地合成实现换成假实现，并返回调用记录。

    `synthesize()` 调用的是模块级 `_synthesize_edge`，所以打模块属性即可生效。
    记录保持 (text, voice, rate, pitch) 四元组——**前两位是既有断言在用的位置**，不要调换。
    """
    calls: list[tuple[str, str, str, str]] = []

    async def _fake(text: str, voice: str, rate: str = "", pitch: str = "") -> bytes:
        calls.append((text, voice, rate, pitch))
        return FAKE_AUDIO

    monkeypatch.setattr(tts, "_synthesize_edge", _fake)
    return calls


@pytest.fixture
def tts_on(monkeypatch):
    """确保 TTS 处于可用状态（.env 可能被改，测试不依赖本机配置）。"""
    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(settings, "TTS_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_MAX_CHARS", 300)


# ---------------------------------------------------------------- 1. Markdown 清洗

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 标题 / 粗体 / 引用角标：角标念出来是干扰
        ("## 梯度下降\n\n**学习率过大**会导致震荡[1]，甚至发散。",
         "梯度下降 学习率过大会导致震荡，甚至发散。"),
        # 行内代码 / 斜体 / 删除线
        ("加粗 **粗**、斜体 *斜*、删除 ~~删~~、行内代码 `code`。",
         "加粗 粗、斜体 斜、删除 删、行内代码 code。"),
        # 链接保留文字；**图片整条丢弃**（不能只剩一个 alt 文本被念出来）
        ("链接 [文档](https://a.com) 和图片 ![示意图](https://b.png) 都要处理。",
         "链接 文档 和图片 都要处理。"),
        # 代码围栏整块丢弃（含语言标注行）
        ("```python\nprint(1)\n```\n代码后的话", "代码后的话"),
        # 未闭合的围栏：其后全部丢弃，宁可少念也不要把代码念出来
        ("```未闭合\nprint(2)", ""),
        # 表格整行丢弃，表格外的句子保留
        ("| 名称 | 说明 |\n| --- | --- |\n| A | B |\n表格外的句子。", "表格外的句子。"),
        # 引用 / 列表去标记；分隔线丢弃
        ("> 引用内容\n- 列表项\n1. 有序项\n\n---\n结尾。", "引用内容 列表项 有序项 结尾。"),
        # 行首标记只在行首生效，正文里的 * 不该被动
        ("3 * 5 = 15", "3 * 5 = 15"),
        # HTML 标签去标签留内容
        ("带 HTML <sup>上标</sup> 的句子", "带 HTML 上标 的句子"),
        # 转义还原
        (r"转义 \* 星号", "转义 * 星号"),
        # 行间公式整块丢弃（LaTeX 念出来是纯噪音）
        ("行间公式：\n$$\n\\frac{a}{b} = c\n$$\n后面还有话。", "行间公式： 后面还有话。"),
        # 行内公式与箭头**保留**——价格、变量、"A → B"在教学文本里都是内容
        ("段落里有 $E=mc^2$ 行内公式", "段落里有 $E=mc^2$ 行内公式"),
        ("序号 A → B 的推导", "序号 A → B 的推导"),
        # emoji 丢弃，但不误伤箭头（U+2192 不在 emoji 区间内）
        ("这里有 emoji 😀🎉 和箭头 →", "这里有 emoji 和箭头 →"),
        # 清洗后只剩标点 / 空白 → 空串
        ("***", ""),
        ("   ", ""),
        ("【】", ""),
        ("", ""),
    ],
)
def test_to_speakable(raw: str, expected: str) -> None:
    assert tts.to_speakable(raw) == expected


def test_to_speakable_leaves_no_space_before_cjk_punct() -> None:
    """回归用例：角标被替换成空串后曾在中文标点前留下空格，朗读时多一个突兀停顿。"""
    assert "震荡 ，" not in tts.to_speakable("震荡[1]，甚至发散")
    assert tts.to_speakable("震荡[1]，甚至发散") == "震荡，甚至发散"


# ---------------------------------------------------------------- 2. provider 分派与开关

def test_is_enabled_follows_switch(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_PROVIDER", "edge")
    assert tts.is_enabled() is True

    monkeypatch.setattr(settings, "TTS_ENABLED", False)
    assert tts.is_enabled() is False

    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_PROVIDER", "cloud")  # 阶段三才实现
    assert tts.is_enabled() is False


async def test_synthesize_dispatches_to_edge(tts_on, fake_edge) -> None:
    audio = await tts.synthesize("这是一句用来分派测试的话。")
    assert audio == FAKE_AUDIO
    assert len(fake_edge) == 1
    assert fake_edge[0][1] == settings.TTS_VOICE  # 未指定音色时用 .env 默认值


async def test_synthesize_unknown_provider_raises(monkeypatch, tts_on) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "cloud")
    with pytest.raises(tts.TTSNotConfiguredError) as exc:
        await tts.synthesize("任意文本")
    assert "cloud" in str(exc.value)  # 报错要点名是哪个 provider 不认识


async def test_synthesize_disabled_raises(monkeypatch, tts_on) -> None:
    monkeypatch.setattr(settings, "TTS_ENABLED", False)
    with pytest.raises(tts.TTSNotConfiguredError):
        await tts.synthesize("任意文本")


async def test_synthesize_empty_after_cleaning_raises(tts_on) -> None:
    """纯 Markdown 符号清洗后为空 → 抛 TTSEmptyTextError（接口层映射成 400）。"""
    with pytest.raises(tts.TTSEmptyTextError):
        await tts.synthesize("```\nprint(1)\n```")


# ---------------------------------------------------------------- 3. 截断

async def test_truncate_by_max_chars(monkeypatch, tts_on, fake_edge) -> None:
    monkeypatch.setattr(settings, "TTS_MAX_CHARS", 20)
    long_text = "第一句话在这里。" * 20
    await tts.synthesize(long_text)
    spoken = fake_edge[0][0]
    assert len(spoken) <= 20
    assert spoken.endswith("。")  # 截断尽量落在句读上，不从词中间切断


async def test_truncate_disabled_when_zero(monkeypatch, tts_on, fake_edge) -> None:
    monkeypatch.setattr(settings, "TTS_MAX_CHARS", 0)
    text = "短句。" * 50
    await tts.synthesize(text)
    assert len(fake_edge[0][0]) == len(text)  # 0 = 不限长


# ---------------------------------------------------------------- 4. 磁盘缓存

async def test_cache_hit_skips_synthesis(tts_on, fake_edge) -> None:
    """同一句话第二次合成必须命中缓存，不再调边缘服务——断网演示靠它兜底。"""
    text = "缓存命中用例：这句话会被合成两次，但只应真正合成一次。"
    first = await tts.synthesize(text)
    second = await tts.synthesize(text)
    assert first == second == FAKE_AUDIO
    assert len(fake_edge) == 1


async def test_cache_key_varies_by_voice(tts_on, fake_edge) -> None:
    """换音色必须重新合成，不能串音。"""
    text = "换音色用例：同一句话换音色后应当重新合成。"
    await tts.synthesize(text, voice="zh-CN-XiaoxiaoNeural")
    await tts.synthesize(text, voice="zh-CN-YunxiNeural")
    assert len(fake_edge) == 2
    assert {call[1] for call in fake_edge} == {"zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"}


async def test_cache_disabled_always_synthesizes(monkeypatch, tts_on, fake_edge) -> None:
    monkeypatch.setattr(settings, "TTS_CACHE_ENABLED", False)
    text = "关闭缓存用例：这句话应当每次都被真正合成。"
    await tts.synthesize(text)
    await tts.synthesize(text)
    assert len(fake_edge) == 2


# ---------------------------------------------------------------- 4.5 形象音色风格（rate/pitch）

async def test_synthesize_passes_voice_style(tts_on, fake_edge) -> None:
    """形象级音色风格要原样透传到合成实现（小满的萌音靠它生效）。"""
    await tts.synthesize("萌音用例：这句应当带音调提升。", rate="+8%", pitch="+30Hz")
    assert fake_edge[0][2:] == ("+8%", "+30Hz")


async def test_synthesize_defaults_to_env_rate_without_pitch(tts_on, fake_edge) -> None:
    """不传风格时回落 .env 的 TTS_RATE，且音调为空——空串进 SSML 会让服务端断流。"""
    await tts.synthesize("默认风格用例：不传 rate/pitch。")
    text, _voice, rate, pitch = fake_edge[0]
    assert rate == settings.TTS_RATE
    assert pitch == ""


async def test_cache_key_varies_by_pitch(tts_on, fake_edge) -> None:
    """同一句话换音调必须重新合成（否则小满会念出晓雯的调）。"""
    text = "音调缓存用例：同文本、不同 pitch 不应命中同一份缓存。"
    await tts.synthesize(text, pitch="+30Hz")
    await tts.synthesize(text, pitch="+0Hz")
    assert len(fake_edge) == 2


def test_speak_rejects_malformed_pitch(client: TestClient, teacher_token, auth, tts_on) -> None:
    """pitch/rate 走白名单正则——防注入非法 prosody 串。"""
    resp = client.post(
        "/api/tts/speak",
        json={"text": "你好", "pitch": "'; drop--"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 422


def test_speak_forwards_voice_style(client: TestClient, teacher_token, auth, tts_on, fake_edge) -> None:
    resp = client.post(
        "/api/tts/speak",
        json={"text": "接口透传用例", "voice": "zh-CN-XiaoyiNeural", "rate": "+8%", "pitch": "+30Hz"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    assert fake_edge[0][1:] == ("zh-CN-XiaoyiNeural", "+8%", "+30Hz")


# ---------------------------------------------------------------- 5. 音色清单

def test_available_voices_is_static_and_complete() -> None:
    voices = tts.available_voices()
    names = [v["short_name"] for v in voices]
    assert len(voices) >= 8
    assert "zh-CN-XiaoxiaoNeural" in names  # 默认音色必须在清单里
    assert all(v["gender"] in {"Female", "Male"} for v in voices)

    # 返回的是副本：调用方改它不该污染模块级常量
    voices[0]["short_name"] = "tampered"
    assert tts.available_voices()[0]["short_name"] != "tampered"


# ---------------------------------------------------------------- 6. 降级：假 Communicate

async def test_edge_failure_becomes_readable_error(monkeypatch) -> None:
    """底层网络异常必须转成可读的 TTSUnavailableError，且不泄露堆栈。"""
    import edge_tts

    class _Boom:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def stream(self):
            raise OSError("connection reset by peer")
            yield  # pragma: no cover - 让函数成为异步生成器

    monkeypatch.setattr(edge_tts, "Communicate", _Boom)
    with pytest.raises(tts.TTSUnavailableError) as exc:
        await tts._synthesize_edge("任意文本", "zh-CN-XiaoxiaoNeural")
    msg = str(exc.value)
    assert "connection reset" not in msg  # 原始异常不进用户可见文案
    assert "网络" in msg


async def test_edge_empty_audio_raises(monkeypatch) -> None:
    """只回了 SentenceBoundary 没有音频 → 当作失败，不能把 0 字节当成功返回。"""
    import edge_tts

    class _NoAudio:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def stream(self):
            yield {"type": "SentenceBoundary", "data": b""}

    monkeypatch.setattr(edge_tts, "Communicate", _NoAudio)
    with pytest.raises(tts.TTSUnavailableError):
        await tts._synthesize_edge("任意文本", "zh-CN-XiaoxiaoNeural")


# ---------------------------------------------------------------- 7. 接口层

def test_speak_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/tts/speak", json={"text": "你好"})
    assert resp.status_code == 401


def test_config_requires_auth(client: TestClient) -> None:
    assert client.get("/api/tts/config").status_code == 401


def test_voices_requires_auth(client: TestClient) -> None:
    assert client.get("/api/tts/voices").status_code == 401


def test_speak_returns_audio_bytes(client: TestClient, teacher_token, auth, tts_on, fake_edge) -> None:
    resp = client.post(
        "/api/tts/speak",
        json={"text": "**你好**，这是一句接口层测试。[1]"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert resp.content == FAKE_AUDIO
    # 到服务端时已是清洗后的文本
    assert fake_edge[-1][0] == "你好，这是一句接口层测试。"


def test_speak_student_allowed(client: TestClient, student_token, auth, tts_on, fake_edge) -> None:
    """语音是师生都可能用的功能，不限制角色。"""
    resp = client.post(
        "/api/tts/speak",
        json={"text": "学生也可以请求朗读。"},
        headers=auth(student_token),
    )
    assert resp.status_code == 200


def test_speak_empty_text_returns_400(client: TestClient, teacher_token, auth, tts_on) -> None:
    resp = client.post(
        "/api/tts/speak",
        json={"text": "```\nprint(1)\n```"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 400
    assert "可朗读" in resp.json()["msg"]


def test_speak_blank_text_returns_422(client: TestClient, teacher_token, auth, tts_on) -> None:
    """空串连参数校验都过不了（min_length=1）。"""
    resp = client.post(
        "/api/tts/speak", json={"text": ""}, headers=auth(teacher_token)
    )
    assert resp.status_code == 422


def test_speak_unavailable_returns_503(client: TestClient, teacher_token, auth, monkeypatch, tts_on) -> None:
    async def _boom(text: str, voice: str, rate: str = "", pitch: str = "") -> bytes:
        raise tts.TTSUnavailableError("语音合成服务暂时不可用，请检查网络连接（Edge-TTS 需要联网）。")

    monkeypatch.setattr(tts, "_synthesize_edge", _boom)
    resp = client.post(
        "/api/tts/speak",
        json={"text": "这句话会触发降级用例。"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 503
    assert "网络" in resp.json()["msg"]


def test_speak_disabled_returns_503(client: TestClient, teacher_token, auth, monkeypatch, tts_on) -> None:
    monkeypatch.setattr(settings, "TTS_ENABLED", False)
    resp = client.post(
        "/api/tts/speak",
        json={"text": "关闭开关后应当拒绝。"},
        headers=auth(teacher_token),
    )
    assert resp.status_code == 503


def test_config_payload(client: TestClient, teacher_token, auth, tts_on) -> None:
    resp = client.get("/api/tts/config", headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["enabled"] is True
    assert data["provider"] == "edge"
    assert data["avatar_provider"] == settings.AVATAR_PROVIDER
    assert data["voice"] == settings.TTS_VOICE
    assert data["max_chars"] == settings.TTS_MAX_CHARS


def test_voices_endpoint(client: TestClient, teacher_token, auth) -> None:
    resp = client.get("/api/tts/voices", headers=auth(teacher_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert any(item["short_name"] == "zh-CN-XiaoxiaoNeural" for item in data)
