# [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 语音合成接口的请求与响应模型
"""数字人语音接口的 Pydantic 模型。

注意：`POST /api/tts/speak` 返回音频字节流，**不使用** ApiResponse 包装
（见 schemas/common.py 模块 docstring：SSE 与文件下载接口不使用该结构）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakRequest(BaseModel):
    """按句合成请求。前端切好句后逐句发来，文本是**原始 Markdown**，清洗在后端做。"""

    text: str = Field(..., min_length=1, max_length=2000, description="待朗读文本（可含 Markdown）")
    voice: str | None = Field(None, description="音色，缺省用 .env 里的 TTS_VOICE")
    # 形象级音色风格（如小满的萌音：rate=+8%、pitch=+30Hz）。
    # 格式白名单：edge-tts 要求 [+-]数字% 或 [+-]数字Hz；不限制的话用户可注入任意 prosody 串。
    rate: str | None = Field(
        None, pattern=r"^[+-]\d{1,3}%$", description="语速（如 +8%），缺省用 .env 的 TTS_RATE"
    )
    pitch: str | None = Field(
        None, pattern=r"^[+-]\d{1,3}Hz$", description="音调（如 +30Hz），缺省不调整"
    )


class TtsConfigOut(BaseModel):
    """前端启动时读一次：决定是否朗读、用哪个音色、形象用哪个 provider。"""

    enabled: bool
    provider: str
    avatar_provider: str
    voice: str
    rate: str
    max_chars: int


class VoiceOut(BaseModel):
    short_name: str
    gender: str
    personalities: str
