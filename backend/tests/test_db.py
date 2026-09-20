from app.db import normalize_database_url, parse_connection_kv


def test_parse_azure_service_connector_string():
    raw = (
        "dbname=postgres host=aether-prod-db.postgres.database.azure.com "
        "port=5432 sslmode=require user=aether-prod-api"
    )
    parsed = parse_connection_kv(raw)
    assert parsed["dbname"] == "postgres"
    assert parsed["host"] == "aether-prod-db.postgres.database.azure.com"
    assert parsed["port"] == "5432"
    assert parsed["sslmode"] == "require"
    assert parsed["user"] == "aether-prod-api"


def test_normalize_sqlalchemy_asyncpg_url():
    raw = "postgresql+asyncpg://user:pass@localhost:5432/aether"
    assert (
        normalize_database_url(raw)
        == "postgresql://user:pass@localhost:5432/aether"
    )
