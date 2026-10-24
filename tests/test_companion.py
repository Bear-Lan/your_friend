from fastapi.testclient import TestClient
from yf.app import create_app
from yf.config import Config

from .conftest import TestModel


def test_companion_is_shared_and_resumes_after_restart(tmp_path):
    config = Config(data_dir=tmp_path, model_name="test")
    with TestClient(create_app(config, provider=TestModel(), background=False)) as client:
        companion = client.post("/api/companion").json()
        assert client.post("/api/companion").json()["id"] == companion["id"]
        response = client.post(
            f"/api/conversations/{companion['id']}/chat",
            json={"content": "明天还在这里接着聊", "request_id": "continuous-companion-001"},
        )
        assert response.status_code == 200
        assert "event: done" in response.text
    with TestClient(create_app(config, provider=TestModel(), background=False)) as client:
        resumed = client.post("/api/companion").json()
        assert resumed["id"] == companion["id"]
        messages = client.get(f"/api/conversations/{resumed['id']}/messages").json()
        assert len(messages) == 2
        assert messages[0]["content"] == "明天还在这里接着聊"
        assert len(client.get("/api/conversations").json()) == 1


def test_old_history_remains_searchable_without_switching_companion(client):
    old = client.post("/api/conversations", json={}).json()
    client.post(
        f"/api/conversations/{old['id']}/chat",
        json={"content": "那次杭州旅行", "request_id": "old-conversation-001"},
    )
    companion = client.post("/api/companion").json()
    assert companion["id"] != old["id"]
    history = client.get("/api/archive", params={"q": "杭州旅行"}).json()
    assert len(history) == 1
    source = history[0]
    assert source["conversation_id"] == old["id"]
    context = client.get(
        f"/api/conversations/{old['id']}/messages",
        params={"before": source["seq"] + 1, "limit": 12},
    ).json()
    assert context[-1]["content"] == "那次杭州旅行"
    assert client.post("/api/companion").json()["id"] == companion["id"]
