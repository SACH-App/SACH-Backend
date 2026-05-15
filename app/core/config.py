"""
Configuration settings for the SACH Backend.
Loads environment variables from .env file and provides typed access.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "SACH Unified Backend"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    NADRA_API_URL: str
    NADRA_USERNAME: str = "partner_user"
    NADRA_PASSWORD: str = "partner12345"


    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str

    # Token settings
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Email OTP settings
    RESEND_API_KEY: str = ""
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
