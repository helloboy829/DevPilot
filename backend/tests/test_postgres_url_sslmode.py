"""Keep libpq TLS policy intact when adapting configured URLs to asyncpg."""

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.dialects.postgresql.asyncpg import dialect
from sqlalchemy.engine import make_url

from deerflow.config.database_config import DatabaseConfig


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+asyncpg"])
@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
def test_libpq_sslmode_is_adapted_only_for_asyncpg(scheme, mode):
    original = f"{scheme}://user:p%40ss%3Aword@localhost:5432/db?sslmode={mode}"
    config = DatabaseConfig(backend="postgres", postgres_url=original)

    url = make_url(config.app_sqlalchemy_url)
    _, kwargs = dialect().create_connect_args(url)

    assert url.drivername == "postgresql+asyncpg"
    assert kwargs["ssl"] == mode
    assert "sslmode" not in kwargs
    assert url.password == "p@ss:word"
    assert config.postgres_url == original
    assert parse_qs(urlsplit(config.app_sync_sqlalchemy_url).query) == {"sslmode": [mode]}


def test_tls_translation_preserves_query_values_and_encoded_credentials():
    original = "postgresql://user:p%40ss%2Fword@[::1]:5432/db?sslmode=verify-full&tag=a%2Bb%26c&tag=second&empty="
    config = DatabaseConfig(backend="postgres", postgres_url=original)

    url = config.app_sqlalchemy_url
    parts = urlsplit(url)

    assert parts.netloc == urlsplit(original).netloc
    assert parse_qs(parts.query, keep_blank_values=True) == {"ssl": ["verify-full"], "tag": ["a+b&c", "second"], "empty": [""]}
    assert config.postgres_url == original


@pytest.mark.parametrize("query", ["sslmode=verify-full&ssl=disable", "ssl=verify-full&sslmode=disable", "sslmode=require&sslmode=disable", "sslmode=require&sslmode=require", "sslmode=", "sslmode=unknown-private-value"])
def test_ambiguous_or_invalid_libpq_tls_modes_fail_without_url_disclosure(query):
    config = DatabaseConfig(backend="postgres", postgres_url=f"postgresql://private-user:private-secret@private-host/private-db?{query}")

    with pytest.raises(ValueError, match="PostgreSQL TLS") as exc:
        _ = config.app_sqlalchemy_url

    message = str(exc.value)
    for private in ("private-user", "private-secret", "private-host", "private-db", "unknown-private-value"):
        assert private not in message


@pytest.mark.parametrize("query", ["ssl=verify-full", "ssl=disable", "prepared_statement_cache_size=0", ""])
def test_urls_without_libpq_sslmode_keep_existing_query_exactly(query):
    original = f"postgresql+asyncpg://user:password@localhost/db{('?' + query) if query else ''}"
    config = DatabaseConfig(backend="postgres", postgres_url=original)

    assert config.app_sqlalchemy_url == original
