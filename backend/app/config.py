from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aether_env: str = "paper"
    venue: str = "kraken"
    symbol: str = "BTC/USD"
    market_data_provider: str = "kraken_ws"
    database_url: str = "postgresql+asyncpg://aether:aether@localhost:5432/aether"
    redis_url: str = "redis://localhost:6379/0"
    persistence_enabled: bool = False
    operator_auth_secret: str = "dev-only-change-me"
    operator_step_up_secret: str = "dev-only-step-up-change-me"
    kraken_read_api_key: str = ""
    kraken_read_api_secret: str = ""
    venue_reconciliation_required: bool = False
    venue_reconciliation_max_age_seconds: int = 60
    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    exchange_api_passphrase: str = ""


settings = Settings()
