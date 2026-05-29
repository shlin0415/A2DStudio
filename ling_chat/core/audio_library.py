"""Audio library index — parse .list files and build FTS5 search"""
import sqlite3
import os
import re

from ling_chat.core.logger import logger


class AudioLibraryIndex:
    """Parse .list files at startup and build FTS5 full-text search index"""

    def __init__(self, db_path: str = ""):
        db_path = db_path or os.path.join(
            os.environ.get("DATA_DIR", "data"), "cache", "audio_index.db"
        )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS audio_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                character TEXT NOT NULL,
                language TEXT NOT NULL,
                text TEXT NOT NULL,
                text_normalized TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clips_char ON audio_clips(character);

            CREATE VIRTUAL TABLE IF NOT EXISTS audio_clips_fts USING fts5(
                file_path UNINDEXED,
                character,
                language,
                text_normalized,
                content='audio_clips',
                content_rowid='id'
            );
        """)
        self.conn.commit()

    def load_list(self, list_path: str, character: str, base_dir: str) -> int:
        """Parse .list file and insert into index. Returns count of inserted rows."""
        if not os.path.exists(list_path):
            logger.warning(f"Audio list file not found: {list_path}")
            return 0

        count = 0
        with open(list_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 4:
                    continue
                rel_path, _, lang, text = parts[0], parts[1], parts[2], parts[3]
                filename = os.path.basename(rel_path)
                actual_path = os.path.join(base_dir, filename)

                text_normalized = self._normalize(text)

                self.conn.execute(
                    "INSERT OR IGNORE INTO audio_clips (file_path, character, language, text, text_normalized) VALUES (?, ?, ?, ?, ?)",
                    [actual_path, character, lang, text, text_normalized],
                )
                count += 1

        self.conn.commit()
        self.conn.execute(
            "INSERT INTO audio_clips_fts(audio_clips_fts) VALUES('rebuild')"
        )
        self.conn.commit()
        logger.info(f"Loaded {character} audio library: {count} clips")
        return count

    @staticmethod
    def _normalize(text: str) -> str:
        """Remove punctuation and extra spaces, keep Japanese kana and kanji"""
        text = text.lower()
        text = re.sub(r"[^\w\s぀-ゟ゠-ヿ一-鿿]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def search(self, character: str, query: str, limit: int = 20) -> list[dict]:
        """FTS5 full-text search"""
        normalized = self._normalize(query)
        rows = self.conn.execute(
            """
            SELECT ac.id, ac.file_path, ac.character, ac.language, ac.text
            FROM audio_clips_fts fts
            JOIN audio_clips ac ON fts.rowid = ac.id
            WHERE audio_clips_fts MATCH ? AND ac.character = ?
            ORDER BY rank
            LIMIT ?
            """,
            [normalized, character, limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_clip(self, clip_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM audio_clips WHERE id = ?", [clip_id]
        ).fetchone()
        return dict(row) if row else None

    def close(self):
        self.conn.close()
