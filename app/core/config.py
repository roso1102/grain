from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # API credentials
    SUPABASE_URL: str
    SUPABASE_KEY: str
    DATABASE_URL: str = ""  # Direct Postgres connection string for running migrations
    GEMINI_API_KEY: str
    TELEGRAM_BOT_TOKEN: str
    GROQ_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_MODEL: str = "deepseek-ai/deepseek-v4-flash"
    NVIDIA_FALLBACK_MODEL: str = "minimaxai/minimax-m2.7"
    NVIDIA_ALT_FALLBACK_MODEL: str = "moonshotai/kimi-k2.6"

    BRAVE_API_KEY: Optional[str] = None
    
    # Obsidian sync
    OBSIDIAN_VAULT_PATH: str = ""  # e.g. C:/Users/you/Obsidian/Grain

    # App thresholds / settings
    TOPIC_SNAP_THRESHOLD: float = 0.90
    CLUSTER_THRESHOLD: float = 0.70
    TOPIC_REVIEW_THRESHOLD: float = 0.70   # minimum sim to trigger LLM merge review
    ENRICH_THRESHOLD: float = 0.88
    
    # Security
    TELEGRAM_WEBHOOK_SECRET: str = ""  # Secret token for Telegram webhook verification
    SESSION_SECRET: str = ""           # Secret for signing dashboard session JWTs (generate a random string)
    SUPABASE_SERVICE_KEY: str = ""     # service_role key for Supabase (bypasses RLS)
    
    # Port / Host configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings (will read from environment and .env)
settings = Settings()
