# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 全局配置（pydantic-settings 读 .env）
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

    # ---------- 重排序 ----------
    RERANK_ENABLED: bool = False
    RERANK_BASE_URL: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"

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
