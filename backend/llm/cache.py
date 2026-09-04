import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class SQLiteResponseCache:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache (cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self.connection.commit()

    def get(self, cache_key: str) -> str | None:
        row = self.connection.execute(
            "SELECT response FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        return str(row[0]) if row else None

    def put(self, cache_key: str, response: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO llm_cache(cache_key, response, created_at) VALUES (?, ?, ?)",
            (cache_key, response, datetime.now(UTC).isoformat()),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


__all__ = ["SQLiteResponseCache"]
