from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str

    finlight_api_key: str

    genai_url: str
    genai_user: str
    genai_password: str

    admin_api_key: str

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

    @field_validator("supabase_url", "genai_url")
    @classmethod
    def must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("URL must start with https://")
        return v.rstrip("/")

    @field_validator("admin_api_key")
    @classmethod
    def must_be_strong(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("ADMIN_API_KEY must be at least 16 characters")
        return v

    @field_validator("finlight_api_key", "genai_user", "genai_password")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Required field must not be empty")
        return v


settings = Settings()
