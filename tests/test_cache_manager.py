"""测试 CacheManager — hash / disk / lru / stats"""
from ling_chat.core.cache_manager import CacheManager, DiskStatus


def make_cm(tmp_path):
    """创建临时目录下的 CacheManager，不污染生产缓存"""
    return CacheManager(cache_dir=str(tmp_path), max_size_mb=100)


class TestHash:
    def test_same_input_same_hash(self, tmp_path):
        cm = make_cm(tmp_path)
        h1 = cm._compute_hash("ema", "こんにちは")
        h2 = cm._compute_hash("ema", "こんにちは")
        assert h1 == h2

    def test_different_text_different_hash(self, tmp_path):
        cm = make_cm(tmp_path)
        h1 = cm._compute_hash("ema", "こんにちは")
        h2 = cm._compute_hash("ema", "さようなら")
        assert h1 != h2

    def test_different_character_different_hash(self, tmp_path):
        cm = make_cm(tmp_path)
        h1 = cm._compute_hash("ema", "こんにちは")
        h2 = cm._compute_hash("hiro", "こんにちは")
        assert h1 != h2

    def test_hash_is_16_chars(self, tmp_path):
        cm = make_cm(tmp_path)
        h = cm._compute_hash("ema", "test")
        assert len(h) == 16

    def test_hash_path_two_level_sharding(self, tmp_path):
        cm = make_cm(tmp_path)
        h = cm._compute_hash("ema", "test")
        path = cm._hash_path(h)
        parts = path.replace("\\", "/").split("/")
        assert len(parts) == 3  # ab/cd/hash.wav
        assert parts[2].endswith(".wav")


class TestDiskStatus:
    def test_check_disk_space_returns_disk_status(self, tmp_path):
        cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
        status = cm.check_disk_space()
        assert isinstance(status, DiskStatus)
        assert status.total_gb > 0
        assert status.free_gb > 0

    def test_disk_status_has_is_low_field(self, tmp_path):
        cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
        status = cm.check_disk_space()
        assert isinstance(status.is_low, bool)


class TestLRU:
    def test_lru_disabled_by_default(self, tmp_path):
        cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
        assert cm.lru_enabled is False

    def test_enable_disable_lru(self, tmp_path):
        cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
        cm.enable_lru()
        assert cm.lru_enabled is True
        cm.disable_lru()
        assert cm.lru_enabled is False


class TestStats:
    def test_empty_cache_stats(self, tmp_path):
        cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
        stats = cm.get_cache_stats()
        assert stats["entry_count"] == 0
        assert stats["total_size_mb"] == 0
