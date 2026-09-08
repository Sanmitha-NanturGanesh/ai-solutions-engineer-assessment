from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path


class SQLiteTokenRateLimiter:
    """Per-tenant token budget over a rolling time window."""

    def __init__(self, db_path: str, limit: int = 50_000, window_seconds: int = 60) -> None:
        self.db_path = db_path
        self.limit = limit
        self.window_seconds = window_seconds
        self._init_lock = asyncio.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def initialize(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS token_events ("
                "tenant TEXT NOT NULL, ts REAL NOT NULL, tokens INTEGER NOT NULL CHECK(tokens >= 0))"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_events_tenant_ts "
                "ON token_events(tenant, ts)"
            )

    async def allow(self, tenant: str, tokens: int, *, now: float | None = None) -> tuple[bool, int]:
        await self.initialize()
        timestamp = time.time() if now is None else now
        return await asyncio.to_thread(self._allow_sync, tenant, tokens, timestamp)

    def _allow_sync(self, tenant: str, tokens: int, now: float) -> tuple[bool, int]:
        if tokens < 0:
            return False, 0

        cutoff = now - self.window_seconds
        conn = self._connect()
        try:
            # Admission has to be check+insert atomically; otherwise concurrent
            # requests can both observe the same remaining budget.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM token_events WHERE ts < ?", (cutoff,))
            used = int(
                conn.execute(
                    "SELECT COALESCE(SUM(tokens), 0) FROM token_events "
                    "WHERE tenant = ? AND ts >= ?",
                    (tenant, cutoff),
                ).fetchone()[0]
            )

            remaining = max(0, self.limit - used)
            if tokens > remaining:
                conn.execute("ROLLBACK")
                return False, remaining

            conn.execute(
                "INSERT INTO token_events(tenant, ts, tokens) VALUES (?, ?, ?)",
                (tenant, now, tokens),
            )
            conn.execute("COMMIT")
            return True, remaining - tokens
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
