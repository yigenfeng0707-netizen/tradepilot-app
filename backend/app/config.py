"""TradePilot backend settings — env only, never commit secrets."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # tradepilot-app/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TradePilot"
    host: str = "0.0.0.0"
    port: int = 8787
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'tradepilot.db').as_posix()}"

    # mock | api — mock 永不调用外网；api 走 OpenAI 兼容网关（默认魔搭）
    llm_mode: str = "api"
    llm_provider: str = "modelscope"  # modelscope | openai_compat | mock
    modelscope_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api-inference.modelscope.cn/v1"
    llm_model: str = "Qwen/Qwen3.5-35B-A3B"
    llm_fallback_model: str = "Qwen/Qwen3.5-27B"
    llm_timeout_sec: float = 90.0

    upload_dir: Path = ROOT / "data" / "uploads"
    output_dir: Path = ROOT / "data" / "outputs"
    samples_dir: Path = ROOT / "samples"
    schema_sql: Path = ROOT / "sql" / "001_schema.sql"
    media_dir: Path = ROOT / "docs" / "media"

    prepaid_risk_threshold: float = 0.30
    cors_origins: str = '["http://127.0.0.1:8787","http://localhost:8787"]'

    @property
    def resolved_api_key(self) -> str:
        return (self.modelscope_api_key or self.llm_api_key or "").strip()

    @property
    def effective_llm_mode(self) -> str:
        if self.llm_mode == "mock":
            return "mock"
        if self.resolved_api_key:
            return "api"
        return "mock"

    @property
    def provider_label(self) -> str:
        if self.effective_llm_mode == "mock":
            return "mock"
        if "modelscope" in (self.llm_base_url or "").lower() or self.llm_provider == "modelscope":
            return "modelscope"
        return self.llm_provider or "openai_compat"

    @property
    def demo_ready(self) -> bool:
        # 规则引擎始终可跑；有魔搭 Key 时走真模型
        return True

    @property
    def real_llm_ready(self) -> bool:
        return self.effective_llm_mode == "api"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw.startswith("["):
            import json

            try:
                return list(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return [x.strip() for x in raw.split(",") if x.strip()]


def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    s.output_dir.mkdir(parents=True, exist_ok=True)
    s.media_dir.mkdir(parents=True, exist_ok=True)
    return s
