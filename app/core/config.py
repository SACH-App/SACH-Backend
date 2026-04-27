from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    NADRA_API_URL: str
    NADRA_PARTNER_KEY: str

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
