import asyncio
import json

from yf.memory import build_context
from yf.provider import ModelError

from .conftest import memory_data


def new_conversation(client):
    return client.post("/api/conversations", json={}).json()["id"]


def chat(client, conversation_id, text, request_id="request-test-001"):
    return client.post(
        f"/api/conversations/{conversation_id}/chat",
        json={"content": text, "request_id": request_id},
    )


def test_chat_stream_persists_and_duplicate_request_replays_without_new_model_call(client, model):
    conversation_id = new_conversation(client)
    response = chat(client, conversation_id, "今天开始做 yf")
    assert response.status_code == 200
    assert "event: delta" in response.text and "event: done" in response.text
    assert len(model.prompts) == 1
    replay = chat(client, conversation_id, "今天开始做 yf")
    assert '"replayed": true' in replay.text
    assert len(model.prompts) == 1
    assert len(client.get(f"/api/conversations/{conversation_id}/messages").json()) == 2
    assert chat(client, conversation_id, "不同消息").status_code == 409


def test_failed_stream_is_visible_and_does_not_start_memory_job(client, model):
    model.failure = ModelError("测试：连接中断")
    conversation_id = new_conversation(client)
    response = chat(client, conversation_id, "你好")
    assert "event: error" in response.text
    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    assert messages[-1]["status"] == "failed"
    assert messages[-1]["content"] == "我听到了，"
    assert client.get("/api/status").json()["jobs"] == []


def test_automatic_extraction_uses_user_sources_and_not_assistant_facts(client, model):
    conversation_id = new_conversation(client)
    chat(client, conversation_id, "第一次跟朋友去杭州旅行")

    def result(context):
        return {
            "memories": [
                memory_data(
                    outline="第一次杭州旅行",
                    tags=["旅行"],
                    source_ids=[context["current_source_id"]],
                )
            ],
            "feedback": [],
        }

    model.result = result
    asyncio.run(client.app.state.worker.run_once())
    memories = client.get("/api/memories").json()
    assert len(memories) == 1
    detail = client.get("/api/memories/" + memories[0]["id"]).json()
    assert detail["sources"][0]["content"] == "第一次跟朋友去杭州旅行"
    assert client.get("/api/status").json()["jobs"][0]["status"] == "done"


def test_bad_extraction_source_is_rejected_and_retried(client, model):
    conversation_id = new_conversation(client)
    chat(client, conversation_id, "用户真实经历")
    assistant_id = client.get(f"/api/conversations/{conversation_id}/messages").json()[-1]["id"]
    model.result = {"memories": [memory_data(source_ids=[assistant_id])], "feedback": []}
    asyncio.run(client.app.state.worker.run_once())
    assert client.get("/api/memories").json() == []
    job = client.get("/api/status").json()["jobs"][0]
    assert job["status"] == "pending" and job["attempts"] == 1


def test_conversation_feedback_adjusts_importance_without_fine_tuning(client, model):
    memory = client.post("/api/memories", json={"outline": "杭州旅行", "tags": ["旅行"]}).json()
    conversation_id = new_conversation(client)
    chat(client, conversation_id, "杭州旅行你还记得吗")
    chat(client, conversation_id, "那件事对我很重要", request_id="request-test-002")
    # Skip the older extraction task to isolate the explicit correction in this scenario.
    store = client.app.state.store
    with store.db:
        store.db.execute(
            "UPDATE jobs SET status='done' WHERE turn_id=(SELECT id FROM turns WHERE request_id='request-test-001')"
        )
    model.result = lambda context: {
        "memories": [],
        "feedback": [
            {
                "memory_id": memory["id"],
                "direction": "more",
                "reason": "用户明确重视这段旅行",
                "source_id": context["current_source_id"],
            }
        ],
    }
    asyncio.run(client.app.state.worker.run_once())
    updated = client.get("/api/memories/" + memory["id"]).json()
    assert updated["importance"] == 0.7
    assert client.get("/api/status").json()["fine_tuning_available"] is False


def test_context_budget_excludes_irrelevant_archive_and_keeps_current_message(client):
    store = client.app.state.store
    conversation_id = new_conversation(client)
    for index in range(20):
        turn, _ = store.begin_turn(
            conversation_id, f"long-request-{index:02}", "很长的旧消息" * 200
        )
        store.finish_turn(turn["id"], "旧回答" * 200, "completed")
    client.post("/api/memories", json={"outline": "杭州旅行", "detail": "西湖" * 1000})
    from yf.config import Config

    config = Config(data_dir=store.path.parent)
    prompt, recalled, size = build_context(store, config, conversation_id, "帮我讨论数学问题")
    assert size <= config.context_chars
    assert prompt[-1]["content"] == "帮我讨论数学问题"
    assert recalled == []
    assert len(prompt) < 41


def test_pause_auto_extraction_keeps_chat_history_and_manual_memory(client):
    assert client.patch("/api/settings", json={"auto_memory": False}).status_code == 200
    conversation_id = new_conversation(client)
    chat(client, conversation_id, "这一轮不自动提取")
    assert client.get("/api/status").json()["jobs"] == []
    assert len(client.get(f"/api/conversations/{conversation_id}/messages").json()) == 2
    assert client.post("/api/memories", json={"outline": "手动记录"}).status_code == 201


def test_local_boundary_validation_and_no_private_key_in_status(client):
    assert (
        client.get("/api/status", headers={"Origin": "https://untrusted.example"}).status_code
        == 403
    )
    assert (
        client.post("/api/conversations", json={}, headers={"Host": "evil.example"}).status_code
        == 400
    )
    assert client.post("/api/memories", json={"outline": "", "importance": 100}).status_code == 422
    assert "api_key" not in client.get("/api/status").text
    assert client.patch("/api/settings", json={"fine_tuning": True}).status_code == 422


def test_exports_and_consistent_backup_are_real_files(client):
    client.post("/api/memories", json={"outline": "值得保存的回忆"})
    archive = client.get("/api/export")
    assert archive.json()["format"] == "yf-archive"
    assert "值得保存的回忆" in json.dumps(archive.json(), ensure_ascii=False)
    backup = client.post("/api/backup")
    assert backup.status_code == 200
    assert backup.content.startswith(b"SQLite format 3")


def test_cancelled_generator_preserves_partial_answer_and_releases_conversation(client, model):
    from yf.schemas import ChatRequest

    conversation_id = new_conversation(client)
    endpoint = next(
        route.endpoint
        for route in client.app.routes
        if getattr(route, "path", "") == "/api/conversations/{conversation_id}/chat"
    )

    async def interrupt():
        response = await endpoint(
            conversation_id, ChatRequest(content="还没说完", request_id="request-cancel-001")
        )
        iterator = response.body_iterator
        await anext(iterator)  # Context event.
        await anext(iterator)  # First text delta.
        await iterator.aclose()

    asyncio.run(interrupt())
    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    assert messages[-1]["status"] == "cancelled"
    assert messages[-1]["content"] == "我听到了，"
    assert (
        chat(client, conversation_id, "重新开始", request_id="request-cancel-002").status_code
        == 200
    )


def test_second_service_cannot_open_active_data_directory(client):
    import pytest
    from fastapi.testclient import TestClient
    from yf.app import create_app
    from yf.config import Config

    with pytest.raises(RuntimeError, match="已有 yf 服务运行"):
        with TestClient(create_app(Config(data_dir=client.app.state.store.path.parent))):
            pass
