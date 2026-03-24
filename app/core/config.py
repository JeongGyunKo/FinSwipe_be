from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_key: str

    finlight_api_key: str

    genai_url: str = "https://fin-ft1a.onrender.com"
    genai_user: str
    genai_password: str

    class Config:
        env_file = ".env"


settings = Settings()
