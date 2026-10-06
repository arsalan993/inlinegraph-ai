from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    llm_mode: str = "auto"
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'inlinegraph.db').as_posix()}"
    langgraph_checkpoint_db: str = str(PROJECT_ROOT / "inlinegraph-checkpoints.sqlite")
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def use_mock_model(self) -> bool:
        mode = self.llm_mode.lower().strip()
        if mode == "mock":
            return True
        if mode == "groq" and not self.groq_api_key:
            raise RuntimeError("LLM_MODE=groq requires GROQ_API_KEY to be set in .env")
        return mode != "groq" and not self.groq_api_key

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
