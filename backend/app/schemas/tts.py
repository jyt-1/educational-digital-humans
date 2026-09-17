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
