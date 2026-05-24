from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    huggingface_token: str = Field(..., env="HUGGINGFACE_TOKEN")

    ollama_base_url: str = Field(default="http://ollama:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1:8b", env="OLLAMA_MODEL")

    whisper_model_size: str = Field(default="base", env="WHISPER_MODEL_SIZE")

    confidence_threshold: float = Field(default=0.6, env="CONFIDENCE_THRESHOLD")
    min_segment_duration: float = Field(default=1.5, env="MIN_SEGMENT_DURATION")

    environment: str = Field(default="development", env="ENVIRONMENT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()