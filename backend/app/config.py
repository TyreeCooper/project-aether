from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aether_env: str = "paper"
    venue: str = "kraken"
    symbol: str = "BTC/USD"
    database_url: str = "postgresql+asyncpg://aether:aether@localhost:5432/aether"
    redis_url: str = "redis://localhost:6379/0"
    persistence_enabled: bool = False
    operator_auth_secret: str = "dev-only-change-me"
    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    exchange_api_passphrase: str = ""


settings = Settings()
