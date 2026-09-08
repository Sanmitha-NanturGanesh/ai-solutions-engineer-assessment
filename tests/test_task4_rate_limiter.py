import asyncio

import pytest

from task4_model_router.rate_limiter import SQLiteTokenRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_is_per_tenant(tmp_path):
    limiter = SQLiteTokenRateLimiter(str(tmp_path / "limit.sqlite3"), limit=100, window_seconds=60)

    assert await limiter.allow("tenant-a", 60, now=1000) == (True, 40)
    assert await limiter.allow("tenant-a", 50, now=1001) == (False, 40)
    assert await limiter.allow("tenant-b", 100, now=1001) == (True, 0)


@pytest.mark.asyncio
async def test_old_entries_expire(tmp_path):
    limiter = SQLiteTokenRateLimiter(str(tmp_path / "limit.sqlite3"), limit=100, window_seconds=60)

    assert await limiter.allow("tenant-a", 100, now=1000) == (True, 0)
    assert await limiter.allow("tenant-a", 1, now=1059) == (False, 0)
    assert await limiter.allow("tenant-a", 100, now=1061) == (True, 0)


@pytest.mark.asyncio
async def test_concurrent_admission_does_not_oversubscribe(tmp_path):
    limiter = SQLiteTokenRateLimiter(str(tmp_path / "limit.sqlite3"), limit=100, window_seconds=60)

    results = await asyncio.gather(
        limiter.allow("tenant-a", 60, now=1000),
        limiter.allow("tenant-a", 60, now=1000),
    )

    assert sorted(allowed for allowed, _ in results) == [False, True]
