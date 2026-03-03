from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_key: str
    finnhub_api_key: str
    genai_server_url: str = "http://localhost:8001"

    class Config:
        env_file = ".env"

settings = Settings()