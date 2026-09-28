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
# 公式片段。前三组（$$..$$ / \[..\] / \(..\)）是行间，一定转中文口语；
# 第四组 $..$ 是行内，**要过 _looks_like_math 守卫**——散文里也有成对的美元号。
_MATH_SPAN_RE = re.compile(
    r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$([^$\n]+?)\$", re.DOTALL
)
# 行内公式的「像公式」特征：反斜杠命令 / 上下标 / 等号
_MATH_SIGNAL_RE = re.compile(r"[\\^_=]")
# 短到不可能是价格区间的单 token（$x$、$0.01$）也算公式
_SHORT_TOKEN_RE = re.compile(r"[A-Za-z0-9.,]{1,5}")
_CJK_RE = re.compile(r"[一-鿿]")
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


# ---------------------------------------------------------------- 公式朗读
# LaTeX → 中文口语。**查表 + 少量结构规则，不是 LaTeX 解析器**——目标是把
# `\frac{1}{m}\sum_{i=1}^{m}(y_i - \hat{y}_i)^2` 念成人话，而不是让数字人念出
# 反斜杠和花括号。
#
# 三条兜底原则（改这段前先读）：
# 1. **认不出的命令丢命令名、保留花括号内容**——`\mathcal{D}` 该念成 "D"；
# 2. **整条公式一个字都没认出来就返回空串**，调用方自然整块跳过；
# 3. **念错比不念更糟**——数字人当众念出「反斜杠 n a b l a」比沉默更伤，
#    所以不认识的命令一律不猜、不硬拼读音。

# 希腊字母（小写 + 大写）。按中文数学课堂的读法，不用英文字母名。
_GREEK: dict[str, str] = {
    "alpha": "阿尔法", "beta": "贝塔", "gamma": "伽马", "delta": "德尔塔",
    "epsilon": "艾普西龙", "varepsilon": "艾普西龙", "zeta": "泽塔", "eta": "伊塔",
    "theta": "西塔", "vartheta": "西塔", "iota": "约塔", "kappa": "卡帕",
    "lambda": "拉姆达", "mu": "缪", "nu": "纽", "xi": "克西", "pi": "派",
    "rho": "柔", "sigma": "西格玛", "tau": "陶", "upsilon": "宇普西龙",
    "phi": "斐", "varphi": "斐", "chi": "卡方", "psi": "普西", "omega": "欧米伽",
    "Gamma": "伽马", "Delta": "德尔塔", "Theta": "西塔", "Lambda": "拉姆达",
    "Pi": "派", "Sigma": "西格玛", "Phi": "斐", "Psi": "普西", "Omega": "欧米伽",
}

# 运算符与函数名。log / sin / max 这类保持拉丁字母——中文课堂也这么念。
_MATH_CMDS: dict[str, str] = {
    "nabla": "梯度", "partial": "偏导", "infty": "无穷", "cdot": "乘以",
    "times": "乘以", "div": "除以", "pm": "正负",
    "leq": "小于等于", "le": "小于等于", "geq": "大于等于", "ge": "大于等于",
    "neq": "不等于", "ne": "不等于", "approx": "约等于", "equiv": "恒等于",
    "propto": "正比于", "to": "趋近于", "rightarrow": "趋近于", "Rightarrow": "推出",
    "in": "属于", "notin": "不属于", "forall": "任意", "exists": "存在",
    "subset": "包含于", "cup": "并集", "cap": "交集",
    "log": "log", "ln": "ln", "exp": "exp", "sin": "sin", "cos": "cos", "tan": "tan",
    "max": "max", "min": "min", "arg": "arg", "lim": "lim", "det": "det",
    "quad": "", "qquad": "", "limits": "", "nolimits": "", "displaystyle": "",
}

# 修饰命令：内容在前、修饰词在后，与中文口语同序（`\hat{y}` → "y 帽"）
_ACCENT_CMDS: dict[str, str] = {"hat": "帽", "bar": "拔"}

# 带上下限的命令：`\sum_{i=1}^{m}` → "求和 从 i 等于 1 到 m"。
# 必须走结构规则——按通用上下标拼会念成「求和 下标 i 等于 1 的 m 次方」，
# 把上标误当成幂，是**主动念错**。
_BOUNDED_CMDS: dict[str, str] = {
    "sum": "求和", "prod": "连乘", "int": "积分", "iint": "二重积分"
}

# 命令连同花括号参数一起丢弃（参数是排版名，不是内容）
_DROP_ARG_CMDS = frozenset(
    {"begin", "end", "label", "tag", "color", "textcolor", "hspace", "vspace"}
)

# LaTeX 里的转义字符：反斜杠是「去掉特殊含义」，字符本身要照念
# （`100\%` 得念出「百分之」而不是丢成 "100"）
_ESCAPED_LITERAL = frozenset("%$&#_{}")
# 间距命令：`\,` `\;` 是细空格，`\!` 是负空格——念出来都是停顿，故只留一个空格
_SPACING_CMDS = frozenset({",", ";", ":", " "})

# 公式里的单字符运算符
_PLAIN_MAP = {"=": " 等于 ", "+": " 加 ", "-": " 减 ", "<": " 小于 ", ">": " 大于 "}

_LATEX_CMD_RE = re.compile(r"\\([A-Za-z]+|.)", re.DOTALL)
# 转换后可能留下「西塔 )」这样的空格（\theta 自带尾空格），朗读会多一个停顿
_SPACE_BEFORE_CLOSER_RE = re.compile(r"\s+([)\]},;.])")


def _read_braced(tex: str, i: int) -> tuple[str, int] | None:
    """``tex[i]`` 是 ``{`` 时读出配对花括号内的**原文**；否则返回 None。

    手写配平而不是用正则：``\\frac{\\partial J}{\\partial \\theta}`` 的分子分母
    各自还带花括号，正则的 ``.+?`` 会在第一个 ``}`` 就收尾，把分母切错。
    """
    if i >= len(tex) or tex[i] != "{":
        return None
    depth, j = 1, i + 1
    while j < len(tex) and depth:
        if tex[j] == "{":
            depth += 1
        elif tex[j] == "}":
            depth -= 1
        j += 1
    return (tex[i + 1 : j - 1], j) if depth == 0 else (tex[i + 1 :], j)


def _read_atom(tex: str, i: int) -> tuple[str, int]:
    """读一个 ``{...}`` 或单个字符的原文（``_i`` 的 ``i``、``x^2`` 的 ``2``）。"""
    braced = _read_braced(tex, i)
    if braced is not None:
        return braced
    if i < len(tex):
        return tex[i], i + 1
    return "", i


def _read_bracket(tex: str, i: int) -> tuple[str, int]:
    """读 ``[..]``（``\\sqrt[3]{x}`` 的次数）；没有则返回空串且不动位置。"""
    if i >= len(tex) or tex[i] != "[":
        return "", i
    j = tex.find("]", i + 1)
    if j == -1:
        return "", i
    return tex[i + 1 : j], j + 1


def _emit_script(tex: str, i: int, out: list[str], *, sup: bool) -> int:
    """处理 ``^...`` / ``_...``，返回新位置。"""
    raw, i = _read_atom(tex, i)
    key = raw.strip()
    if not key:
        return i
    # 前置空格不能省：`x^2` 拼成 "x的平方" 会与变量名黏成一个词，朗读断不开
    if not sup:
        out.append(f" 下标 {_scan(raw).strip()} ")
        return i
    # 幂次特例：这三个在机器学习文本里高频，念成「的 2 次方」不自然
    special = {"2": "的平方", "3": "的立方", "T": "的转置", "-1": "的逆"}
    out.append(f" {special.get(key) or f'的 {_scan(raw).strip()} 次方'} ")
    return i


def _emit_cmd(cmd: str, tex: str, i: int, out: list[str]) -> int:
    """处理一个 ``\\命令``，把朗读文本追加进 out，返回新位置。"""
    if cmd in _GREEK:
        out.append(_GREEK[cmd] + " ")
        return i
    if cmd in _MATH_CMDS:
        word = _MATH_CMDS[cmd]
        if word:
            out.append(word + " ")
        return i
    if cmd in _ACCENT_CMDS:
        raw, i = _read_atom(tex, i)
        if not raw.strip():  # `\bar` 后面没跟内容（退化写法）→ 丢，别念出孤零零的"拔"
            return i
        out.append(f"{_scan(raw).strip()} {_ACCENT_CMDS[cmd]} ")
        return i
    if cmd == "frac":
        num, i = _read_atom(tex, i)
        den, i = _read_atom(tex, i)
        out.append(f"{_scan(num).strip()} 除以 {_scan(den).strip()} ")
        return i
    if cmd == "sqrt":
        deg, i = _read_bracket(tex, i)
        rad, i = _read_atom(tex, i)
        body = _scan(rad).strip()
        out.append(f"{body} 的 {_scan(deg).strip()} 次方根 " if deg.strip() else f"根号 {body} ")
        return i
    if cmd in _BOUNDED_CMDS:
        word = _BOUNDED_CMDS[cmd]
        sub_raw = sup_raw = ""
        if i < len(tex) and tex[i] == "_":
            sub_raw, i = _read_atom(tex, i + 1)
        if i < len(tex) and tex[i] == "^":
            sup_raw, i = _read_atom(tex, i + 1)
        sub, sup = _scan(sub_raw).strip(), _scan(sup_raw).strip()
        if sub and sup:
            out.append(f"{word} 从 {sub} 到 {sup} ")
        elif sub:
            out.append(f"{word} 从 {sub} ")
        elif sup:
            out.append(f"{word} 到 {sup} ")
        else:
            out.append(word + " ")
        return i
    if cmd in _DROP_ARG_CMDS:
        _, i = _read_atom(tex, i)
        return i
    if cmd in _ESCAPED_LITERAL:
        out.append(cmd)  # `\%` `\$` `\&` 的字符本身是要念的
        return i
    if cmd in _SPACING_CMDS or cmd == "!" or cmd.strip() == "":
        out.append(" ")
        return i
    # 未知命令：丢命令名、保留花括号内容（`\mathcal{D}` → "D"），无花括号则什么都不留。
    # **不猜**——猜错会念出原文里根本没有的东西。
    braced = _read_braced(tex, i)
    if braced is not None:
        out.append(_scan(braced[0]) + " ")
        return braced[1]
    return i


def _scan(tex: str) -> str:
    """递归扫描一段 LaTeX，拼出可朗读的中文。"""
    out: list[str] = []
    i, n = 0, len(tex)
    while i < n:
        ch = tex[i]
        if ch == "\\":
            m = _LATEX_CMD_RE.match(tex, i)
            if m is None:  # 尾部孤立的反斜杠
                i += 1
                continue
            i = _emit_cmd(m.group(1), tex, m.end(), out)
        elif ch in "{}":
            i += 1  # 分组花括号本身不念，内容照常
        elif ch in "^_":
            i = _emit_script(tex, i + 1, out, sup=ch == "^")
        elif ch in _PLAIN_MAP:
            out.append(_PLAIN_MAP[ch])
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def latex_to_speech(tex: str) -> str:
    """把一段 LaTeX 公式转成中文口语；一个字都认不出时返回空串。

    返回空串是**正常结果**不是错误——调用方据此整块跳过，等价于旧行为「公式不念」。
    """
    if not tex or not tex.strip():
        return ""
    text = _SPACE_BEFORE_CLOSER_RE.sub(r"\1", _scan(tex))
    return _WS_RE.sub(" ", text).strip()


def _looks_like_math(tex: str) -> bool:
    """行内 ``$...$`` 的守卫：只有确实像公式才转中文。

    旧注释的担忧是对的——「价格 $5 到 $10」里也有成对美元号。故要求内容
    **不含汉字**（含汉字基本是散文里被误配的一对 ``$``），且要么带 LaTeX 特征
    （反斜杠命令 / 上下标 / 等号），要么短到不可能是价格区间（``$x$``、``$0.01$``）。
    拿不准就返回 False，退回「原样保留」——那不会念出错误内容。
    """
    if _CJK_RE.search(tex):
        return False
    return bool(_MATH_SIGNAL_RE.search(tex)) or bool(_SHORT_TOKEN_RE.fullmatch(tex.strip()))


def _math_repl(m: re.Match) -> str:
    """把文本里的一段公式替换成可朗读的中文（认不出则替换成空格）。"""
    tex = next((g for g in m.groups() if g is not None), "")
    if m.group(4) is not None and not _looks_like_math(tex):
        return m.group(0)  # 行内 $..$ 但不像公式（价格等）→ 原样保留
    spoken = latex_to_speech(tex)
    return f" {spoken} " if spoken else " "


def to_speakable(markdown_text: str) -> str:
    """把答案里的 Markdown 片段清洗成适合朗读的纯文本。

    没有可朗读内容时返回空串（调用方据此返回 400）。清洗分四步，**顺序不能换**：

    1. 先删代码围栏——围栏里的 `|` `#` `-` 都不是 Markdown 语法，先做行处理会把代码当表格；
    2. 再逐行处理表格行、分隔线、标题/引用/列表的行首标记；
    3. 然后处理行内语法，**图片必须早于链接**（`![a](b)` 里含有 `[a](b)` 的形状）；
    4. 最后折叠空白并判断是否只剩标点。

    公式在第 1 步就转成中文口语：`\\frac{a}{b}` 念「a 除以 b」，而不是让数字人念
    反斜杠和花括号。**必须在逐行处理之前做**——`$$...$$` 常跨行，先按行切会把它拆碎。
    """
    if not markdown_text:
        return ""

    # 1. 代码围栏整块丢弃（含未闭合的尾部围栏）；公式转中文口语
    text = _FENCE_RE.sub(" ", markdown_text)
    text = _MATH_SPAN_RE.sub(_math_repl, text)

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
