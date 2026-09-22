# [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— TTS 语音合成（provider 可切换）
"""文字转语音：默认走本地 Edge-TTS（微软免费服务，无需 API Key，不占显卡）。

策略（见 CLAUDE.md 第 19 节与设计文档 3.4 阶段二扩展位）：
1. 本模块是**语音合成 provider 接口**，`TTS_PROVIDER` 决定用哪个实现；
   阶段三接云端数字人 API 时，加一个 `_synthesize_cloud()` 分支即可，调用方不动。
2. 生成类接口只做「怎么念」；**「在哪切句」由前端负责**——切句要低延迟，
   必须在流式 delta 到达时就地判断，等后端来回一趟首句就慢了。
3. 答案原文是 Markdown，直接送 TTS 会把 `##`、`**`、`|` 都念出来，
   故 `to_speakable()` 负责清洗。这一步放后端是因为它最易出错，
   而前端没有测试框架、本项目测试一律用 pytest。
4. 落盘缓存：同一句话第二次合成直接读文件。**缓存的价值不只是提速**——
   Edge-TTS 需要联网，缓存命中意味着断网也能播，演示可靠性靠它兜底。

沿用本仓库既有的函数式 provider 范式（见 services/embedding.py）：模块级公开函数 +
settings 字符串开关 + if/else 分派 + 私有实现 + 模块级可读异常，不引入 Protocol/ABC/工厂。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 已实现的 provider。阶段三加 "cloud" 时只需在此登记 + 补一个 _synthesize_cloud 分支
_PROVIDERS = ("edge",)

# 缓存目录的软上限：超过就按 mtime 淘汰最旧的，防止无限增长
_CACHE_KEEP = 400
_CACHE_PRUNE_THRESHOLD = 500

# zh-CN 音色清单（实测 2026-09-17 从微软 voices/list 接口取得，共 8 个）。
# 写死成静态清单而不是每次联网拉取：这个列表极少变动，而问答页每次打开都要读它，
# 联网拉会让「打开页面」依赖外网。需要刷新时手工调一次该接口比对即可。
_ZH_VOICES: tuple[dict, ...] = (
    {"short_name": "zh-CN-XiaoxiaoNeural", "gender": "Female", "personalities": "Warm"},
    {"short_name": "zh-CN-XiaoyiNeural", "gender": "Female", "personalities": "Lively"},
    {"short_name": "zh-CN-YunxiNeural", "gender": "Male", "personalities": "Lively,Sunshine"},
    {"short_name": "zh-CN-YunjianNeural", "gender": "Male", "personalities": "Passion"},
    {"short_name": "zh-CN-YunyangNeural", "gender": "Male", "personalities": "Professional,Reliable"},
    {"short_name": "zh-CN-YunxiaNeural", "gender": "Male", "personalities": "Cute"},
    {"short_name": "zh-CN-liaoning-XiaobeiNeural", "gender": "Female", "personalities": "Humorous"},
    {"short_name": "zh-CN-shaanxi-XiaoniNeural", "gender": "Female", "personalities": "Bright"},
)

# ---------------------------------------------------------------- 清洗用正则
# 顺序敏感：见 to_speakable() 里的分步注释，改动前先读那一段
_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~|```.*\Z", re.DOTALL)
_HR_RE = re.compile(r"^[-*_]{3,}$")
_HEADING_RE = re.compile(r"^#{1,6}\s*")
_QUOTE_RE = re.compile(r"^>\s?")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}\.)\s+")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CITE_RE = re.compile(r"\[\d{1,2}\]")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_ITALIC_RE = re.compile(r"(\*|_)(.+?)\1")
_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|>])")
# 行间公式 $$...$$ 整块丢弃：LaTeX 念出来是纯噪音（行内 $x$ 不动——价格、变量都长这样，误伤代价更大）
_MATH_BLOCK_RE = re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]", re.DOTALL)
# emoji 与变体选择符。**不含箭头区（U+2190~21FF）**——"A → B"在教学文本里是内容，删了会粘成"AB"
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0000fe00-\U0000fe0f\U0000200d]+"
)
_WS_RE = re.compile(r"\s+")
# 删掉「，」前的空格。角标/图片被替换成空串后，原位置与中文标点之间会留下空格，
# 变成「震荡 ，甚至」——朗读时多一个突兀停顿，故单独清一遍。
_SPACE_BEFORE_CJK_PUNCT_RE = re.compile(r"\s+([，。！？；：、）】」』%])")
_SPACE_AFTER_CJK_OPEN_RE = re.compile(r"([（【「『])\s+")
# 「有实质内容」= 至少含一个汉字或字母数字。只有标点的串视为无可朗读内容
_MEANINGFUL_RE = re.compile(r"[0-9A-Za-z一-鿿]")


class TTSNotConfiguredError(RuntimeError):
    """TTS 未启用或 provider 未知时抛出，便于接口层给出可读提示。"""


class TTSUnavailableError(RuntimeError):
    """Edge-TTS 服务不可达或合成失败时抛出。属增强项故障，不得阻断问答主流程。"""


class TTSEmptyTextError(ValueError):
    """清洗后没有可朗读的内容（整句只含代码块、表格或标点）。"""


def is_enabled() -> bool:
    """TTS 是否可用：总开关打开且 provider 是已实现的。"""
    return bool(settings.TTS_ENABLED) and settings.TTS_PROVIDER.lower() in _PROVIDERS


def available_voices() -> list[dict]:
    """可选音色清单（静态，不联网）。"""
    return [dict(item) for item in _ZH_VOICES]


def to_speakable(markdown_text: str) -> str:
    """把答案里的 Markdown 片段清洗成适合朗读的纯文本。

    没有可朗读内容时返回空串（调用方据此返回 400）。清洗分四步，**顺序不能换**：

    1. 先删代码围栏——围栏里的 `|` `#` `-` 都不是 Markdown 语法，先做行处理会把代码当表格；
    2. 再逐行处理表格行、分隔线、标题/引用/列表的行首标记；
    3. 然后处理行内语法，**图片必须早于链接**（`![a](b)` 里含有 `[a](b)` 的形状）；
    4. 最后折叠空白并判断是否只剩标点。
    """
    if not markdown_text:
        return ""

    # 1. 代码围栏与行间公式整块丢弃（含未闭合的尾部围栏）
    text = _FENCE_RE.sub(" ", markdown_text)
    text = _MATH_BLOCK_RE.sub(" ", text)

    # 2. 逐行处理
    kept: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 表格行整行丢弃：念表格是噪声大于信息，属已知限制（见设计文档阶段二"不做的事"）
        if line.count("|") >= 2:
            continue
        if _HR_RE.match(line):
            continue
        line = _HEADING_RE.sub("", line)
        line = _QUOTE_RE.sub("", line)
        line = _LIST_RE.sub("", line)
        if line:
            kept.append(line)
    text = " ".join(kept)

    # 3. 行内语法。这几处用空串而不是空格：替换成空格会在中文标点前留下空档
    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _CITE_RE.sub("", text)           # 引用角标 [1]，念出来是干扰
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(r"\2", text)        # 粗体须早于斜体
    text = _STRIKE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\2", text)
    text = _HTML_RE.sub("", text)
    text = _ESCAPE_RE.sub(r"\1", text)
    text = _EMOJI_RE.sub("", text)

    # 4. 收尾
    text = _SPACE_BEFORE_CJK_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_AFTER_CJK_OPEN_RE.sub(r"\1", text)
    text = _WS_RE.sub(" ", text).strip()
    if not _MEANINGFUL_RE.search(text):
        return ""
    return text


def _truncate(text: str) -> str:
    """按 TTS_MAX_CHARS 截断，尽量落在句读上，避免从词中间切断。"""
    limit = int(settings.TTS_MAX_CHARS)
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[:limit]
    for punct in "。！？；，、,.;":
        pos = head.rfind(punct)
        if pos > limit * 0.6:
            return head[: pos + 1]
    return head


def _cache_key(text: str, voice: str, rate: str = "", pitch: str = "") -> str:
    """缓存键：把影响音频的所有参数一起哈希，换音色/语速/音调不会串音。"""
    raw = (
        f"{settings.TTS_PROVIDER}|{voice}|{rate or settings.TTS_RATE}|"
        f"{pitch}|{settings.TTS_VOLUME}|{text}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    return settings.tts_cache_dir / f"{key}.mp3"


def _prune_cache() -> None:
    """缓存目录超过阈值时按 mtime 淘汰最旧的一批。"""
    try:
        files = sorted(settings.tts_cache_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        if len(files) <= _CACHE_PRUNE_THRESHOLD:
            return
        for path in files[: len(files) - _CACHE_KEEP]:
            path.unlink(missing_ok=True)
        logger.info("TTS 缓存已清理，保留最近 %d 条", _CACHE_KEEP)
    except OSError as exc:  # noqa: BLE001 - 清理失败不影响合成
        logger.warning("TTS 缓存清理失败：%s", exc)


async def synthesize(
    text: str,
    *,
    voice: str | None = None,
    rate: str | None = None,
    pitch: str | None = None,
) -> bytes:
    """把一段文本合成为 MP3 字节。文本会先做 Markdown 清洗。

    rate / pitch 为形象级音色风格（如小满的「萌音」= 语速 +8%、音调 +30Hz）：
    缺省走 .env 的 TTS_RATE、不加音调。两者进缓存键，同一句话不同风格不会互相串音。

    并发说明：本机不做服务端限流——前端按句串行播放、最多预取一句，
    同一时刻在途请求不超过 2 个（见 frontend/src/audio/speechQueue.js）。
    在服务端再加一层信号量收益很小，却会引入事件循环绑定问题（TestClient 每次可能换循环）。
    """
    if not settings.TTS_ENABLED:
        raise TTSNotConfiguredError("语音合成未启用（TTS_ENABLED=false）。")
    if settings.TTS_PROVIDER.lower() not in _PROVIDERS:
        raise TTSNotConfiguredError(
            f"未知的 TTS provider：{settings.TTS_PROVIDER}。"
            f"当前已实现：{'、'.join(_PROVIDERS)}。"
        )

    speakable = _truncate(to_speakable(text))
    if not speakable:
        raise TTSEmptyTextError("这段话没有可朗读的内容（可能只含代码块、表格或标点）。")

    actual_voice = voice or settings.TTS_VOICE
    actual_rate = rate or settings.TTS_RATE
    actual_pitch = pitch or ""
    cache_path = _cache_path(_cache_key(speakable, actual_voice, actual_rate, actual_pitch))

    if settings.TTS_CACHE_ENABLED and cache_path.exists():
        try:
            audio = await asyncio.to_thread(cache_path.read_bytes)
            if audio:
                logger.info("TTS 缓存命中：%s（%d 字节）", cache_path.name, len(audio))
                return audio
        except OSError as exc:  # noqa: BLE001 - 读缓存失败就重新合成
            logger.warning("TTS 缓存读取失败，改为重新合成：%s", exc)

    if settings.TTS_PROVIDER.lower() == "edge":
        audio = await _synthesize_edge(speakable, actual_voice, actual_rate, actual_pitch)
    else:  # pragma: no cover - 上面的 _PROVIDERS 校验已挡住
        raise TTSNotConfiguredError(f"provider {settings.TTS_PROVIDER} 没有对应实现。")

    if settings.TTS_CACHE_ENABLED:
        try:
            await asyncio.to_thread(cache_path.write_bytes, audio)
            _prune_cache()
        except OSError as exc:  # noqa: BLE001 - 写缓存失败不影响本次返回
            logger.warning("TTS 缓存写入失败：%s", exc)
    return audio


async def _synthesize_edge(text: str, voice: str, rate: str = "", pitch: str = "") -> bytes:
    """本地实现：Edge-TTS（微软免费服务，纯 CPU，无需 Key，**需要联网**）。

    pitch 为空串时**不传该参数**：edge-tts 对空串会拼出非法 prosody 属性，服务端直接断流。
    这里**惰性导入** edge_tts：未安装时应用照常启动，只在真正调用时报可读错，
    与 llm_client.py「没有 Key 不影响启动」的既有约定一致。
    """
    try:
        import edge_tts
    except ImportError as exc:
        raise TTSNotConfiguredError(
            "未安装 edge-tts。请执行：pip install -i https://pypi.tuna.tsinghua.edu.cn/simple edge-tts"
        ) from exc

    timeout = int(settings.TTS_TIMEOUT_SECONDS)
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate or settings.TTS_RATE,
        volume=settings.TTS_VOLUME,
        **({"pitch": pitch} if pitch else {}),
        # 超时下推到库：它自己管 connect/receive 两级，比外层包一层粗暴的 asyncio.timeout 精确。
        # proxy 必须传 None 而非空串——库内会校验 isinstance(proxy, str)，空串能过校验却是个坏代理。
        connect_timeout=10,
        receive_timeout=timeout,
        proxy=settings.TTS_PROXY or None,
    )
    buffer = bytearray()
    try:
        # 外层再兜一道：库的 receive_timeout 只覆盖单次读，卡在握手后会漏网
        async with asyncio.timeout(timeout + 10):
            async for chunk in communicate.stream():
                # 除 audio 外还有 SentenceBoundary 等事件，只取音频
                if chunk["type"] == "audio":
                    buffer.extend(chunk["data"])
    except TimeoutError as exc:
        raise TTSUnavailableError(f"语音合成超时（超过 {timeout} 秒）。请检查网络后重试。") from exc
    except Exception as exc:  # noqa: BLE001 - 网络/协议异常统一转成可读提示
        raise TTSUnavailableError(
            "语音合成服务暂时不可用，请检查网络连接（Edge-TTS 需要联网）。"
        ) from exc

    if not buffer:
        raise TTSUnavailableError("语音合成返回了空音频。")
    logger.info("TTS 合成完成：%d 字 → %d 字节（音色 %s）", len(text), len(buffer), voice)
    return bytes(buffer)
