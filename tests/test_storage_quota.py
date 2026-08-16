"""
Coverage for the storage-quota building block routers/videos.py's upload check relies on.

Doesn't go through the HTTP upload route: that requires an authenticated cloud-mode user
against the shared database (see conftest.py's constraint on mutating shared state), and the
route's quota check itself is a one-line comparison against this function's return value.
Testing get_user_storage_bytes in isolation, with a real temp directory and no DB involved,
covers the part that was actually at risk of being wrong.
"""
from app import config


def test_get_user_storage_bytes_sums_files_recursively(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_user_dir", lambda username: tmp_path)
    (tmp_path / "a.bin").write_bytes(b"x" * 1000)
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    (items_dir / "b.bin").write_bytes(b"y" * 2000)

    assert config.get_user_storage_bytes("someuser") == 3000


def test_get_user_storage_bytes_empty_dir_is_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_user_dir", lambda username: tmp_path)
    assert config.get_user_storage_bytes("someuser") == 0


def test_max_user_storage_bytes_is_2gb():
    assert config.MAX_USER_STORAGE_BYTES == 2 * 1024 * 1024 * 1024
