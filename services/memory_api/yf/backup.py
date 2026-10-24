import sqlite3
from pathlib import Path


def restore_to_new_directory(source: Path, destination: Path) -> Path:
    """Restore a verified snapshot without overwriting any existing database."""
    source = source.resolve(strict=True)
    destination = destination.resolve()
    target_path = destination / "yf.sqlite3"
    if target_path.exists():
        raise ValueError("目标目录已有数据库，拒绝覆盖；请选择新的数据目录。")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        if original.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("备份一致性检查失败，未恢复。")
        tables = {
            row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"memories", "messages", "settings", "deletion_records"} <= tables:
            raise ValueError("这不是 yf 的数据库备份。")
        if original.execute("PRAGMA user_version").fetchone()[0] not in {1, 2}:
            raise ValueError("备份版本不兼容，请使用与备份匹配的 yf 版本。")
        destination.mkdir(parents=True, exist_ok=True)
        with target_path.open("xb"):
            pass
        with sqlite3.connect(target_path) as target:
            original.backup(target)
    return target_path
