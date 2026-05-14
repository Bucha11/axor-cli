from __future__ import annotations

"""
SQLite-backed MemoryProvider for axor-cli.

Stores memory fragments in ~/.axor/memory.db.
Uses FTS5 for full-text search.
Falls back gracefully if sqlite3 FTS5 is unavailable (LIKE search).
"""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from axor_core.contracts.memory import (
    FragmentValue,
    MemoryFragment,
    MemoryProvider,
    MemoryQuery,
)

_DB_PATH = Path.home() / ".axor" / "memory.db"

_DDL = """
CREATE TABLE IF NOT EXISTS memory_fragments (
    namespace    TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    value        TEXT    NOT NULL DEFAULT 'working',
    token_count  INTEGER NOT NULL DEFAULT 0,
    tags         TEXT    NOT NULL DEFAULT '[]',
    created_at   TEXT    NOT NULL,
    accessed_at  TEXT    NOT NULL,
    metadata     TEXT    NOT NULL DEFAULT '{}',
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_mf_namespace ON memory_fragments (namespace);
CREATE INDEX IF NOT EXISTS idx_mf_value     ON memory_fragments (value);
CREATE INDEX IF NOT EXISTS idx_mf_accessed  ON memory_fragments (accessed_at);
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    namespace UNINDEXED,
    key UNINDEXED,
    content=memory_fragments,
    content_rowid=rowid,
    tokenize='porter ascii'
);
CREATE TRIGGER IF NOT EXISTS mf_ai AFTER INSERT ON memory_fragments BEGIN
    INSERT INTO memory_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS mf_ad AFTER DELETE ON memory_fragments BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS mf_au AFTER UPDATE OF content ON memory_fragments BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO memory_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_fragment(row: tuple) -> MemoryFragment:
    ns, key, content, value, token_count, tags_json, created_at, accessed_at, meta_json = row
    return MemoryFragment(
        namespace=ns,
        key=key,
        content=content,
        value=FragmentValue(value),
        token_count=token_count,
        tags=json.loads(tags_json or "[]"),
        created_at=datetime.fromisoformat(created_at),
        accessed_at=datetime.fromisoformat(accessed_at),
        metadata=json.loads(meta_json or "{}"),
    )


def project_namespace(cwd: Path | None = None) -> str:
    """Derive a short namespace from the project directory path."""
    path = str(cwd or Path.cwd())
    return "proj_" + hashlib.sha1(path.encode()).hexdigest()[:8]


class SQLiteMemoryProvider(MemoryProvider):
    """
    Local SQLite memory store. Zero extra dependencies.

    All blocking sqlite3 calls run in asyncio.to_thread to keep the event loop free.
    FTS5 is used for full-text search when available; falls back to LIKE.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._has_fts = self._init_db()

    def _init_db(self) -> bool:
        """Initialize schema. Returns True if FTS5 is available."""
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_DDL)
            try:
                conn.executescript(_FTS_DDL)
                return True
            except sqlite3.OperationalError:
                return False  # FTS5 not compiled in

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── MemoryProvider API ─────────────────────────────────────────────────────

    async def load(self, query: MemoryQuery) -> list[MemoryFragment]:
        return await asyncio.to_thread(self._load_sync, query)

    def _load_sync(self, query: MemoryQuery) -> list[MemoryFragment]:
        conds: list[str] = []
        params: list = []

        if query.namespaces:
            ph = ",".join("?" * len(query.namespaces))
            conds.append(f"namespace IN ({ph})")
            params.extend(query.namespaces)
        if query.values:
            ph = ",".join("?" * len(query.values))
            conds.append(f"value IN ({ph})")
            params.extend(v.value for v in query.values)

        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        params.append(query.max_results)

        sql = f"""
            SELECT namespace, key, content, value, token_count, tags,
                   created_at, accessed_at, metadata
            FROM memory_fragments {where}
            ORDER BY accessed_at DESC LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_fragment(tuple(r)) for r in rows]

    async def save(self, fragments: list[MemoryFragment]) -> None:
        await asyncio.to_thread(self._save_sync, fragments)

    def _save_sync(self, fragments: list[MemoryFragment]) -> None:
        with self._connect() as conn:
            for f in fragments:
                conn.execute(
                    """
                    INSERT INTO memory_fragments
                        (namespace, key, content, value, token_count, tags,
                         created_at, accessed_at, metadata)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        content     = excluded.content,
                        value       = excluded.value,
                        token_count = excluded.token_count,
                        tags        = excluded.tags,
                        accessed_at = excluded.accessed_at,
                        metadata    = excluded.metadata
                    """,
                    (
                        f.namespace, f.key, f.content, f.value.value,
                        f.token_count or len(f.content) // 4,
                        json.dumps(f.tags),
                        f.created_at.isoformat(),
                        f.accessed_at.isoformat(),
                        json.dumps(f.metadata),
                    ),
                )

    async def delete(self, namespace: str, keys: list[str]) -> int:
        return await asyncio.to_thread(self._delete_sync, namespace, keys)

    def _delete_sync(self, namespace: str, keys: list[str]) -> int:
        ph = ",".join("?" * len(keys))
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM memory_fragments WHERE namespace=? AND key IN ({ph})",
                [namespace, *keys],
            )
            return cur.rowcount

    async def evict(self, namespace: str, values=(), max_age_seconds=None) -> int:
        return await asyncio.to_thread(self._evict_sync, namespace, values, max_age_seconds)

    def _evict_sync(self, namespace: str, values, max_age_seconds) -> int:
        conds = ["namespace = ?"]
        params: list = [namespace]
        if values:
            ph = ",".join("?" * len(values))
            conds.append(f"value IN ({ph})")
            params.extend(v.value for v in values)
        if max_age_seconds is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()
            conds.append("accessed_at < ?")
            params.append(cutoff)
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM memory_fragments WHERE {' AND '.join(conds)}", params
            )
            return cur.rowcount

    async def namespaces(self) -> list[str]:
        return await asyncio.to_thread(self._namespaces_sync)

    def _namespaces_sync(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT namespace FROM memory_fragments ORDER BY namespace"
            ).fetchall()
        return [r[0] for r in rows]

    async def search(
        self,
        query_text: str,
        namespace: str | None = None,
        max_results: int = 10,
    ) -> list[MemoryFragment]:
        return await asyncio.to_thread(self._search_sync, query_text, namespace, max_results)

    def _search_sync(
        self, query_text: str, namespace: str | None, max_results: int
    ) -> list[MemoryFragment]:
        with self._connect() as conn:
            if self._has_fts:
                if namespace:
                    sql = """
                        SELECT f.namespace, f.key, f.content, f.value, f.token_count,
                               f.tags, f.created_at, f.accessed_at, f.metadata
                        FROM memory_fragments f
                        JOIN memory_fts fts ON f.rowid = fts.rowid
                        WHERE memory_fts MATCH ? AND f.namespace = ?
                        ORDER BY rank LIMIT ?
                    """
                    rows = conn.execute(sql, [query_text, namespace, max_results]).fetchall()
                else:
                    sql = """
                        SELECT f.namespace, f.key, f.content, f.value, f.token_count,
                               f.tags, f.created_at, f.accessed_at, f.metadata
                        FROM memory_fragments f
                        JOIN memory_fts fts ON f.rowid = fts.rowid
                        WHERE memory_fts MATCH ?
                        ORDER BY rank LIMIT ?
                    """
                    rows = conn.execute(sql, [query_text, max_results]).fetchall()
            else:
                # FTS5 not available — fall back to LIKE
                like = f"%{query_text}%"
                conds = ["content LIKE ?"]
                params: list = [like]
                if namespace:
                    conds.append("namespace = ?")
                    params.append(namespace)
                params.append(max_results)
                sql = f"""
                    SELECT namespace, key, content, value, token_count,
                           tags, created_at, accessed_at, metadata
                    FROM memory_fragments
                    WHERE {' AND '.join(conds)}
                    ORDER BY accessed_at DESC LIMIT ?
                """
                rows = conn.execute(sql, params).fetchall()
        return [_row_to_fragment(tuple(r)) for r in rows]

    # ── Extra helpers used by CLI commands ────────────────────────────────────

    def count_sync(self, namespace: str | None = None) -> int:
        with self._connect() as conn:
            if namespace:
                return conn.execute(
                    "SELECT COUNT(*) FROM memory_fragments WHERE namespace=?", [namespace]
                ).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM memory_fragments").fetchone()[0]
