"""Voice cache — content-addressed storage with optional LRU and disk monitoring.

Design decisions:
- Default max 10 GB — user-configurable.
- LRU eviction is OFF by default. Users opt in explicitly.
- When free disk space drops below 5 GB, warn and signal the caller to pause.
- No automatic deletion without user consent.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ling_chat.core.logger import logger


@dataclass
class DiskStatus:
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    cache_size_gb: float = 0.0
    is_low: bool = False          # below warning threshold


class CacheManager:
    """Content-addressed voice cache.

    Usage::

        cm = CacheManager(max_size_mb=10240)

        # Optional — user explicitly opts in:
        cm.enable_lru()

        path = await cm.get_or_generate("ema", text, generate_fn)

        # Check disk health periodically:
        status = cm.check_disk_space()
        if status.is_low:
            # caller should pause / notify user
            ...
    """

    # ── tunable defaults ─────────────────────────────────────────
    DEFAULT_MAX_SIZE_MB = 10_240       # 10 GB
    DISK_WARN_THRESHOLD_GB = 5         # warn when free space < 5 GB

    def __init__(
        self,
        cache_dir: str = "",
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
    ):
        cache_dir = cache_dir or os.path.join(
            os.environ.get("DATA_DIR", "data"), "cache"
        )
        self.voice_dir = Path(cache_dir) / "voice"
        self.voice_dir.mkdir(parents=True, exist_ok=True)

        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.lru_enabled: bool = False

        db_path = Path(cache_dir) / "cache_index.db"
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    # ── tables ───────────────────────────────────────────────────

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                hash TEXT PRIMARY KEY,
                character TEXT NOT NULL,
                tts_text TEXT NOT NULL,
                params_json TEXT NOT NULL,
                file_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                last_access REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cache_lru
                ON cache_entries(character, last_access);

            CREATE TABLE IF NOT EXISTS cache_readable (
                hash TEXT PRIMARY KEY,
                character TEXT NOT NULL,
                readable_text TEXT NOT NULL
            );
        """)
        self.conn.commit()

    # ── LRU toggle ───────────────────────────────────────────────

    def enable_lru(self) -> None:
        """User explicitly opts in to automatic LRU eviction."""
        self.lru_enabled = True
        logger.info("CacheManager: LRU eviction enabled by user")

    def disable_lru(self) -> None:
        self.lru_enabled = False
        logger.info("CacheManager: LRU eviction disabled")

    # ── hash helpers ─────────────────────────────────────────────

    @staticmethod
    def _compute_hash(
        character: str, tts_text: str, params: dict | None = None
    ) -> str:
        payload = f"{character}|{tts_text}|{json.dumps(params or {}, sort_keys=True)}"
        return hashlib.sha1(payload.encode()).hexdigest()[:16]

    @staticmethod
    def _hash_path(hash_str: str) -> str:
        """Two-level sharding: ab/cd/hash.wav"""
        return f"{hash_str[:2]}/{hash_str[2:4]}/{hash_str}.wav"

    # ── core API ─────────────────────────────────────────────────

    async def get_or_generate(
        self,
        character: str,
        tts_text: str,
        generate_fn,  # async callable(text) -> bytes
        params: dict | None = None,
    ) -> str:
        """Return cached file path, or generate + cache on miss.

        After storing a new file the method checks disk space and logs a
        warning when free space drops below the threshold.  It does NOT
        evict anything unless *lru_enabled* is True.
        """
        hash_str = self._compute_hash(character, tts_text, params)

        # hit
        row = self.conn.execute(
            "SELECT file_path, size FROM cache_entries WHERE hash = ?", [hash_str]
        ).fetchone()
        if row and os.path.exists(row["file_path"]):
            self.conn.execute(
                "UPDATE cache_entries SET last_access = ? WHERE hash = ?",
                [time.time(), hash_str],
            )
            self.conn.commit()
            return row["file_path"]

        # miss → generate
        audio_data = await generate_fn(tts_text)

        # store
        rel_path = self._hash_path(hash_str)
        abs_path = self.voice_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(audio_data)

        file_size = len(audio_data)
        self.conn.execute(
            "INSERT OR REPLACE INTO cache_entries "
            "(hash, character, tts_text, params_json, file_path, size, last_access) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                hash_str, character, tts_text, json.dumps(params or {}),
                str(abs_path), file_size, time.time(),
            ],
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO cache_readable (hash, character, readable_text) "
            "VALUES (?, ?, ?)",
            [hash_str, character, tts_text[:60]],
        )
        self.conn.commit()

        # disk check
        status = self.check_disk_space()
        if status.is_low:
            logger.warning(
                "CacheManager: 磁盘空间不足！剩余 %.1f GB（警告阈值 %.0f GB）。"
                "请考虑清理缓存或启用 LRU 淘汰。",
                status.free_gb,
                self.DISK_WARN_THRESHOLD_GB,
            )

        # LRU (only when user opted in)
        if self.lru_enabled:
            await self._evict_lru()

        return str(abs_path)

    # ── disk monitoring ──────────────────────────────────────────

    def check_disk_space(self) -> DiskStatus:
        """Return disk usage info for the volume hosting the cache.

        ``is_low`` is True when free space < 5 GB — callers should pause
        and notify the user.
        """
        usage = shutil.disk_usage(self.voice_dir)

        # total cache size from index
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size), 0) AS total FROM cache_entries"
        ).fetchone()
        cache_bytes = row["total"] if row else 0

        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        cache_gb = cache_bytes / (1024 ** 3)

        is_low = free_gb < self.DISK_WARN_THRESHOLD_GB

        if is_low:
            logger.warning(
                "CacheManager: 磁盘剩余空间仅 %.1f GB！建议暂停程序。"
                "缓存当前占用 %.1f GB。",
                free_gb, cache_gb,
            )

        return DiskStatus(
            total_gb=round(total_gb, 1),
            used_gb=round(used_gb, 1),
            free_gb=round(free_gb, 1),
            cache_size_gb=round(cache_gb, 1),
            is_low=is_low,
        )

    # ── LRU eviction (explicit opt-in only) ───────────────────────

    async def _evict_lru(self) -> None:
        """Evict oldest entries until total size is below 80% of max.

        Only called when ``lru_enabled`` is True.
        """
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size), 0) AS total FROM cache_entries"
        ).fetchone()
        if not row or row["total"] < self.max_size_bytes:
            return

        target = int(self.max_size_bytes * 0.8)
        removed = 0
        while True:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(size), 0) AS total FROM cache_entries"
            ).fetchone()
            if not row or row["total"] < target:
                break

            oldest = self.conn.execute(
                "SELECT hash, file_path FROM cache_entries "
                "ORDER BY last_access ASC LIMIT 1"
            ).fetchone()
            if not oldest:
                break

            try:
                os.remove(oldest["file_path"])
            except OSError:
                pass
            self.conn.execute(
                "DELETE FROM cache_entries WHERE hash = ?", [oldest["hash"]]
            )
            self.conn.execute(
                "DELETE FROM cache_readable WHERE hash = ?", [oldest["hash"]]
            )
            removed += 1
        self.conn.commit()

        if removed:
            logger.info(
                "CacheManager: LRU 淘汰了 %d 条旧缓存记录", removed
            )

    # ── manual cleanup ───────────────────────────────────────────

    def clear_character_cache(self, character: str) -> int:
        """Remove all cached voice files for *character*.  Returns count."""
        rows = self.conn.execute(
            "SELECT file_path FROM cache_entries WHERE character = ?", [character]
        ).fetchall()
        for row in rows:
            try:
                os.remove(row["file_path"])
            except OSError:
                pass
        self.conn.execute(
            "DELETE FROM cache_entries WHERE character = ?", [character]
        )
        self.conn.execute(
            "DELETE FROM cache_readable WHERE character = ?", [character]
        )
        self.conn.commit()
        logger.info("CacheManager: 已清除 %s 的全部缓存（%d 条）", character, len(rows))
        return len(rows)

    def get_cache_stats(self) -> dict:
        """Return human-readable cache statistics."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS total "
            "FROM cache_entries"
        ).fetchone()
        return {
            "entry_count": row["count"] if row else 0,
            "total_size_mb": round(
                (row["total"] if row else 0) / (1024 * 1024), 1
            ),
        }
