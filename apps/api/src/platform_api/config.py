from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VPN-SALE API"
    environment: str = "local"
    version: str = "0.0.0-milestone0"
    database_url: str = Field(
        default="postgresql+asyncpg://vpnsale:vpnsale_dev_password@localhost:5432/vpnsale"
    )
    redis_url: str = "redis://localhost:6379/0"
    metrics_enabled: bool = True
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VPN_SALE_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
