from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_key: str
    finnhub_api_key: str

    finbert_url: str = "https://finbert-du3j.onrender.com"
    finbert_user: str
    finbert_password: str

    class Config:
        env_file = ".env"


settings = Settings()
