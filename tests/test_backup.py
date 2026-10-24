import pytest
from yf.backup import restore_to_new_directory
from yf.store import Store

from .conftest import memory_data


def test_restore_refuses_overwrite_and_restores_into_fresh_directory(tmp_path, store):
    memory = store.add_memory(memory_data())
    backup = store.backup(tmp_path / "snapshot.sqlite3")
    target = restore_to_new_directory(backup, tmp_path / "recovered")
    recovered = Store(target)
    try:
        assert recovered.memory(memory["id"])["outline"] == "第一次开发 yf"
    finally:
        recovered.close()
    with pytest.raises(ValueError, match="拒绝覆盖"):
        restore_to_new_directory(backup, tmp_path / "recovered")
