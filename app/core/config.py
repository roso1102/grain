from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # API credentials
    SUPABASE_URL: str
    SUPABASE_KEY: str
    GEMINI_API_KEY: str
    TELEGRAM_BOT_TOKEN: str
    NOTION_API_KEY: Optional[str] = None
    NOTION_WORKSPACE_ID: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_MODEL: str = "deepseek-ai/deepseek-v4-flash"
    NVIDIA_FALLBACK_MODEL: str = "minimaxai/minimax-m2.7"
    NVIDIA_ALT_FALLBACK_MODEL: str = "moonshotai/kimi-k2.6"

    BRAVE_API_KEY: Optional[str] = None

    # App thresholds / settings
    TOPIC_SNAP_THRESHOLD: float = 0.90
    ENRICH_THRESHOLD: float = 0.88
    
    # Port / Host configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Embedding model name
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings (will read from environment and .env)
settings = Settings()
