# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 全局配置（pydantic-settings 读 .env）
# [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 追加 TTS / 形象 provider 配置组
"""全局配置。所有模型名、base_url、开关一律从 .env 读取，代码中不得硬编码。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：app/config.py -> app -> backend -> Education-agent
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置，字段名与 .env 中的键一一对应（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- LLM ----------
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"

    # ---------- Embedding ----------
    EMBEDDING_PROVIDER: str = "api"
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    # 本地兜底模型：与 EMBEDDING_MODEL 分开配置，避免切到 local 时误用云端的大模型
    # （bge-m3 在无 GPU 机器上加载/推理都很慢，本地一律用 small 级别）
    EMBEDDING_LOCAL_MODEL: str = "BAAI/bge-small-zh-v1.5"

    # ---------- 重排序 ----------
    RERANK_ENABLED: bool = False
    RERANK_BASE_URL: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # ---------- 知识库 / RAG（工单18） ----------
    CHROMA_DIR: str = "./data/chroma"
    KB_CHUNK_SIZE: int = 500        # 切块长度（约 500 字）
    KB_CHUNK_OVERLAP: int = 80      # 相邻块重叠字数
    KB_TOP_K: int = 5               # 检索返回条数
    KB_MAX_UPLOAD_MB: int = 50      # 单文档大小上限

    # ---------- 个性化学习（工单19） ----------
    # 跨用户常用问题聚合的总开关。关闭时高频栏退化为只显示 kp_faq 中 source='seed'
    # 的种子问题——聚合等于部分打破 conversations「按 user_id 隔离」的承诺，
    # 故留一个可一键关闭的开关（设计文档 2.2 场景三第 7 条）
    ASSISTANT_HOTQ_ENABLED: bool = True

    # ---------- 数字人 / TTS（阶段二） ----------
    # 阶段二只做输出侧（文字→语音+口型）；输入侧的 ASR 随工单20 一并移出，见下方 ASR 分组。
    TTS_ENABLED: bool = True            # 总开关。关闭后前端不朗读，形象仍在（只眨眼睛不说话）
    TTS_PROVIDER: str = "edge"          # edge=本地 Edge-TTS；阶段三换 cloud=云端数字人 API
    TTS_VOICE: str = "zh-CN-XiaoxiaoNeural"
    TTS_RATE: str = "+0%"               # 语速，形如 "+20%" / "-10%"
    TTS_VOLUME: str = "+0%"
    TTS_MAX_CHARS: int = 300            # 单次合成文本上限，超出截断（防止误传整篇答案）
    TTS_CACHE_ENABLED: bool = True
    # 合成结果落盘缓存：重复语句不只是提速，还能在断网时照常播放——演示可靠性靠它
    TTS_CACHE_DIR: str = "./data/tts_cache"
    # 形象驱动 provider。阶段三接云端数字人 SDK 时改这一项即可，前端业务代码不动
    AVATAR_PROVIDER: str = "svg-face"

    # ---------- ASR ----------
    WHISPER_MODEL: str = "small"

    # ---------- 认证 ----------
    JWT_SECRET: str = "change-me-in-prod"
    JWT_EXPIRE_MINUTES: int = 10080
    JWT_ALGORITHM: str = "HS256"

    # ---------- 应用 ----------
    DATA_DIR: str = "./data"
    UPLOAD_DIR: str = "./uploads"

    @property
    def data_dir(self) -> Path:
        """数据目录绝对路径（相对路径按项目根解析，保证从任意 CWD 启动都一致）。"""
        return self._resolve(self.DATA_DIR)

    @property
    def upload_dir(self) -> Path:
        return self._resolve(self.UPLOAD_DIR)

    @property
    def chroma_dir(self) -> Path:
        """ChromaDB 持久化目录（设计文档 3.2 节：collection 按知识库隔离）。"""
        return self._resolve(self.CHROMA_DIR)

    @property
    def kb_image_dir(self) -> Path:
        """知识库文档中抽取出的图片与表格截图存放目录（工单18 引用回显用）。"""
        return self.upload_dir / "kb"

    @property
    def tts_cache_dir(self) -> Path:
        """TTS 合成结果缓存目录（阶段二）。落在 data/ 下，已在 .gitignore 中。"""
        return self._resolve(self.TTS_CACHE_DIR)

    @staticmethod
    def _resolve(raw: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def database_url(self) -> str:
        db_path = self.data_dir / "edu_agent.db"
        return f"sqlite:///{db_path.as_posix()}"


settings = Settings()

# 启动即确保运行期目录存在（data/ 与 uploads/ 已在 .gitignore 中）
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.chroma_dir.mkdir(parents=True, exist_ok=True)
settings.kb_image_dir.mkdir(parents=True, exist_ok=True)
settings.tts_cache_dir.mkdir(parents=True, exist_ok=True)
