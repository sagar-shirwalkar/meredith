from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.config import AppConfig, MemoryConfig
from coding_agent.memory.store import MemoryStore


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(memory=MemoryConfig(store_path=str(tmp_path / "memory.db")))


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return _make_config(tmp_path)


@pytest.fixture
def store(config: AppConfig) -> MemoryStore:
    return MemoryStore(config=config)


@pytest.mark.asyncio
async def test_setup_creates_tables(store: MemoryStore):
    await store.start()
    result = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'",
    ).fetchall()
    tables = {r[0] for r in result}
    assert "memories" in tables


@pytest.mark.asyncio
async def test_store_and_recall(store: MemoryStore):
    await store.start()
    store.store(type="convention", content="Use f-strings", tags="python")
    store.store(type="error_pattern", content="Avoid bare excepts", tags="python")
    recalled = store.recall_relevant(query="python")
    assert "Use f-strings" in recalled
    assert "Avoid bare excepts" in recalled


@pytest.mark.asyncio
async def test_recall_by_type(store: MemoryStore):
    await store.start()
    store.store(type="convention", content="Naming: snake_case")
    store.store(type="structure", content="src/ contains the package")
    recalled = store.recall_relevant(query="convention")
    assert "Naming: snake_case" in recalled
    assert "src/" in recalled


@pytest.mark.asyncio
async def test_recall_no_match(store: MemoryStore):
    await store.start()
    store.store(type="convention", content="Use f-strings")
    # Use a query with >2 words that don't overlap
    recalled = store.recall_relevant(query="completely unrelated topic")
    assert recalled == ""


@pytest.mark.asyncio
async def test_store_with_confidence(store: MemoryStore):
    await store.start()
    store.store(type="tool_pattern", content="Use web_search for docs", confidence="high")
    recalled = store.recall_relevant(query="web")
    assert "Use web_search for docs" in recalled


@pytest.mark.asyncio
async def test_start_creates_db_file(config: AppConfig, tmp_path: Path):
    store = MemoryStore(config=config)
    await store.start()
    assert store._conn is not None


@pytest.mark.asyncio
async def test_close(store: MemoryStore):
    await store.start()
    await store.close()
    assert store._conn is None


@pytest.mark.asyncio
async def test_double_start(store: MemoryStore):
    await store.start()
    await store.start()
    assert store._conn is not None


def test_repr(store: MemoryStore):
    r = repr(store)
    assert "MemoryStore" in r


@pytest.mark.asyncio
async def test_prune_old_entries(store: MemoryStore):
    await store.start()
    store.store(type="convention", content="Old note", tags="old")
    pruned = store.prune_old_entries(max_age_days=0)
    assert isinstance(pruned, int)


@pytest.mark.asyncio
async def test_get_stats(store: MemoryStore):
    await store.start()
    store.store(type="convention", content="Note", tags="test")
    stats = store.get_stats()
    assert "total" in stats
    assert stats["total"] == 1
