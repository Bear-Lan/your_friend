from datetime import UTC, datetime, timedelta

import pytest
from yf.search import project_memory
from yf.store import Conflict, Missing, Store

from .conftest import memory_data


def test_unimportant_details_fade_but_original_is_recoverable(store):
    memory = store.add_memory(memory_data(importance=0.1))
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    with store.db:
        store.db.execute("UPDATE memories SET created_at=? WHERE id=?", (old, memory["id"]))
    faded = store.memory(memory["id"])
    assert faded["detail_level"] == "archived"
    assert faded["detail"] == ""
    assert store.memory(memory["id"], archive=True)["archived_detail"] == "一起讨论了长期陪伴与记忆"
    assert not store.retrieve("开发 yf")
    assert store.retrieve("开发 yf", archive=True)[0]["id"] == memory["id"]


def test_importance_and_pin_change_detail_retention_without_inventing_missing_details(store):
    memory = store.add_memory(memory_data(importance=0.9, missing_details=["确切日期未知"]))
    raw = store.raw_memory(memory["id"])
    later = datetime.fromisoformat(raw["created_at"]) + timedelta(days=90)
    assert project_memory(raw, later)["detail_level"] == "full"
    raw["pinned"] = True
    assert project_memory(raw, later + timedelta(days=3650))["detail_level"] == "full"
    assert store.memory(memory["id"])["missing_details"] == ["确切日期未知"]


def test_lexical_retrieval_does_not_force_unrelated_important_memories(store):
    trip = store.add_memory(
        memory_data(outline="杭州旅行时去了西湖", tags=["旅行"], importance=0.8)
    )
    store.add_memory(memory_data(outline="正在开发 yf 陪伴应用", importance=1, pinned=True))
    assert store.retrieve("那次杭州旅行")[0]["id"] == trip["id"]
    assert store.retrieve("量子力学的方程") == []
    assert isinstance(store.retrieve('" OR DROP TABLE memories; --'), list)


def test_feedback_adapts_events_immediately_and_category_after_distinct_examples(store):
    ids = [
        store.add_memory(memory_data(outline=f"旅行经历 {index}", tags=["旅行"]))["id"]
        for index in range(3)
    ]
    store.feedback(ids[0], "more", "这次很珍贵")
    store.feedback(ids[0], "more", "重复点击")
    assert store.memory(ids[0])["importance"] == pytest.approx(0.7)
    assert store.preference_profile()[0] == {"tag": "旅行", "examples": 1, "bias": 0}
    for memory_id in ids[1:]:
        store.feedback(memory_id, "more", "我重视这段经历")
    later = store.add_memory(memory_data(outline="新的旅行经历", tags=["旅行"]))
    assert later["importance"] > 0.5
    assert store.preference_profile()[0]["examples"] == 3


def test_pausing_memory_does_not_delete_archives_or_existing_memories(store):
    memory = store.add_memory(memory_data())
    store.update_settings({"memory_enabled": False})
    assert store.retrieve("开发 yf") == []
    assert store.memory(memory["id"])["outline"] == "第一次开发 yf"
    with pytest.raises(Conflict):
        store.add_memory(memory_data())


def test_forgetting_cleans_connected_sources_recalled_answers_and_job_outputs(store):
    conversation = store.create_conversation("私密昵称")
    turn, _ = store.begin_turn(conversation["id"], "request-001", "昵称是小熊")
    store.finish_turn(turn["id"], "以后我叫你小熊", "completed")
    source = store.one("SELECT id FROM messages WHERE turn_id=? AND role='user'", (turn["id"],))[
        "id"
    ]
    memory = store.add_memory(memory_data(outline="昵称小熊", detail="昵称是小熊"), [source])
    other = store.add_memory(memory_data(outline="同一段交流中的事实"), [source])
    later, _ = store.begin_turn(conversation["id"], "request-002", "我叫什么")
    store.set_recalled(later["id"], [memory["id"]])
    store.finish_turn(later["id"], "小熊", "completed")
    preview = store.deletion_preview(memory["id"])
    assert set(preview["memory_ids"]) == {memory["id"], other["id"]}
    assert len(preview["message_ids"]) == 4
    with pytest.raises(Conflict):
        store.forget(memory["id"], [memory["id"]])
    store.forget(memory["id"], preview["memory_ids"])
    assert all(row["content"] == "[已删除]" for row in store.messages(conversation["id"]))
    assert not store.search_archive("小熊")
    assert store.conversation(conversation["id"])["title"] == "已清理的会话"
    assert all(job["status"] == "cancelled" for job in store.jobs())
    with pytest.raises(Missing):
        store.memory(memory["id"])


def test_backup_restores_history_settings_memories_and_feedback(tmp_path, store):
    conversation = store.create_conversation("值得保留")
    turn, _ = store.begin_turn(conversation["id"], "request-003", "第一次说你好")
    store.finish_turn(turn["id"], "你好", "completed")
    memory = store.add_memory(memory_data())
    store.feedback(memory["id"], "more", "很重要")
    store.update_settings({"personality": "安静而好奇"})
    path = store.backup(tmp_path / "restored" / "yf.sqlite3")
    restored = Store(path)
    try:
        assert restored.messages(conversation["id"])[0]["content"] == "第一次说你好"
        assert restored.memory(memory["id"])["importance"] == pytest.approx(0.7)
        assert restored.settings()["personality"] == "安静而好奇"
    finally:
        restored.close()


def test_restart_marks_interrupted_turn_and_recovers_running_job(tmp_path):
    path = tmp_path / "restart.sqlite3"
    first = Store(path)
    conversation = first.create_conversation("恢复")
    running, _ = first.begin_turn(conversation["id"], "request-004", "没有生成完")
    completed, _ = first.begin_turn(
        first.create_conversation("其他")["id"], "request-005", "已完成"
    )
    first.finish_turn(completed["id"], "好的", "completed")
    first.claim_job()
    first.close()
    second = Store(path)
    try:
        assert (
            second.one("SELECT status FROM turns WHERE id=?", (running["id"],))["status"]
            == "interrupted"
        )
        assert second.jobs()[0]["status"] == "pending"
        assert second.messages(conversation["id"])[0]["content"] == "没有生成完"
    finally:
        second.close()
