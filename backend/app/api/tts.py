# [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 语音合成接口
"""数字人语音接口：配置下发、音色清单、按句合成。

调用链：前端问答页按句切分 SSE delta → 逐句 POST /speak → 拿到 MP3 字节 →
Web Audio 解码播放，同时用 AnalyserNode 分析音量驱动头像口型。

权限：登录即可（师生都可能要听），不限制角色。

错误约定：走 main.py 的全局异常处理器，输出 {code, msg, data}。
- 400 文本清洗后没有可朗读内容（整句只含代码块/表格/标点）
- 503 TTS 未启用、provider 未知，或 Edge-TTS 服务不可达
**两种错误都不泄露堆栈**，并给中文可读提示——语音是增强项，不可用时前端静默跳过。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import get_current_user
from app.config import settings
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.tts import SpeakRequest, TtsConfigOut, VoiceOut
from app.services import tts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["数字人·语音合成"])


@router.get("/config", response_model=ApiResponse[TtsConfigOut], summary="数字人配置（开关/音色/provider）")
def get_config(user: User = Depends(get_current_user)) -> ApiResponse[TtsConfigOut]:
    """前端启动时读一次，据此决定要不要朗读、用哪个形象 provider。"""
    return ApiResponse.ok(
        TtsConfigOut(
            enabled=tts.is_enabled(),
            provider=settings.TTS_PROVIDER,
            avatar_provider=settings.AVATAR_PROVIDER,
            voice=settings.TTS_VOICE,
            rate=settings.TTS_RATE,
            max_chars=settings.TTS_MAX_CHARS,
        )
    )


@router.get("/voices", response_model=ApiResponse[list[VoiceOut]], summary="可用音色清单")
def list_voices(user: User = Depends(get_current_user)) -> ApiResponse[list[VoiceOut]]:
    """静态清单，不联网——打开问答页不该依赖外网。"""
    return ApiResponse.ok([VoiceOut(**item) for item in tts.available_voices()])


@router.post("/speak", summary="文本转语音（返回 MP3 字节流）")
async def speak(payload: SpeakRequest, user: User = Depends(get_current_user)) -> Response:
    try:
        audio = await tts.synthesize(
            payload.text, voice=payload.voice, rate=payload.rate, pitch=payload.pitch
        )
    except tts.TTSEmptyTextError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except tts.TTSNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except tts.TTSUnavailableError as exc:
        logger.warning("语音合成失败：%s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # 直接返回字节流，不包 ApiResponse（见 schemas/common.py 的约定）。
    # Cache-Control 交给浏览器缓存没有意义：同一句话前端只会要一次，重复的话走的是服务端缓存。
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
