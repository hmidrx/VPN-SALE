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
    password_argon2_time_cost: int = 3
    password_argon2_memory_cost: int = 65536
    password_argon2_parallelism: int = 4
    opaque_token_bytes: int = 32
    opaque_token_hash_salt: str = "vpnsale-identity-token-v1"  # noqa: S105
    identity_encryption_key: str = ""
    identity_encryption_key_version: str = "dev-v1"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VPN_SALE_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
