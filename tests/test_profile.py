import asyncio
import sqlite3

from fastapi.testclient import TestClient
from yf.app import create_app
from yf.config import Config
from yf.profile import FeatureProfile, compile_style
from yf.store import Store

from .conftest import TestModel, memory_data


def test_profile_update_history_restore_and_stale_write(client):
    original = client.get("/api/profile").json()
    document = original["document"]
    document["expression"]["humor"] = 0.9
    document["behavior_notes"] = "先听完，少说教"
    saved = client.put(
        "/api/profile", json={"expected_version": original["version"], "document": document}
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == original["version"] + 1
    stale = client.put(
        "/api/profile", json={"expected_version": original["version"], "document": document}
    )
    assert stale.status_code == 409
    restored = client.post(
        "/api/profile/restore",
        json={"version": original["version"], "expected_version": saved.json()["version"]},
    )
    assert restored.status_code == 200
    assert restored.json()["document"]["expression"]["humor"] == 0.35
    assert len(client.get("/api/status").json()["profile_history"]) == 3
    assert (
        client.post(
            "/api/profile/restore", json={"version": 99999, "expected_version": 3}
        ).status_code
        == 404
    )


def test_profile_rejects_invalid_weights_and_unbounded_text(client):
    document = FeatureProfile().model_dump()
    document["expression"]["humor"] = 1.1
    assert (
        client.put("/api/profile", json={"expected_version": 1, "document": document}).status_code
        == 422
    )
    document = FeatureProfile().model_dump()
    document["importance"] = dict.fromkeys(document["importance"], 0)
    assert (
        client.put("/api/profile", json={"expected_version": 1, "document": document}).status_code
        == 422
    )
    document = FeatureProfile().model_dump()
    document["behavior_notes"] = "长" * 501
    assert (
        client.put("/api/profile", json={"expected_version": 1, "document": document}).status_code
        == 422
    )


def test_api_switch_preserves_local_profile_and_memories(tmp_path):
    models = [TestModel(), TestModel()]
    for index, name in enumerate(["provider-a", "provider-b"]):
        with TestClient(
            create_app(
                Config(data_dir=tmp_path, model_name=name), provider=models[index], background=False
            )
        ) as client:
            if index == 0:
                document = FeatureProfile(
                    behavior_notes="先听完，少说教",
                    examples=[{"user": "今天很累", "assistant": "要不要先歇会儿？我听你说。"}],
                ).model_dump()
                client.put("/api/profile", json={"expected_version": 1, "document": document})
                memory_id = client.post(
                    "/api/memories", json={"outline": "杭州旅行", "importance": 0.8}
                ).json()["id"]
            else:
                assert client.get("/api/profile").json()["document"] == document
            conversation_id = client.post("/api/conversations", json={}).json()["id"]
            response = client.post(
                f"/api/conversations/{conversation_id}/chat",
                json={"content": "杭州旅行还记得吗", "request_id": f"profile-api-switch-{index}"},
            )
            assert response.status_code == 200
            assert memory_id in response.text
            system = models[index].prompts[-1][0]["content"]
            assert "先听完，少说教" in system
            assert "要不要先歇会儿" in system
    assert models[0].prompts[0][0] == models[1].prompts[0][0]


def test_importance_weights_are_passed_to_extraction_independently_of_style(client, model):
    profile = FeatureProfile().model_dump()
    profile["importance"] = {
        "explicit_emphasis": 0.8,
        "personal_significance": 0.2,
        "lasting_relevance": 0,
    }
    profile["behavior_notes"] = "用于聊天的风格，不用于推断重要事实"
    client.put("/api/profile", json={"expected_version": 1, "document": profile})
    conversation_id = client.post("/api/conversations", json={}).json()["id"]
    client.post(
        f"/api/conversations/{conversation_id}/chat",
        json={"content": "这件事我很重视", "request_id": "importance-weights-001"},
    )
    asyncio.run(client.app.state.worker.run_once())
    context = model.extractions[-1]
    assert context["importance_policy"]["relative_weights"]["explicit_emphasis"] == 0.8
    assert context["profile_version"] == 2
    assert "behavior_notes" not in context


def test_style_compilation_bounds_examples_without_changing_original():
    document = FeatureProfile(
        behavior_notes="说明" * 250,
        examples=[{"user": "问题" * 100, "assistant": "回答" * 200}] * 3,
    ).model_dump()
    compiled = compile_style(document)
    assert len(compiled) <= 2000
    assert "不是模型参数" in compiled
    assert len(document["examples"]) == 3
    assert "风格样例" in compiled
    escaped = FeatureProfile(behavior_notes="\x00" * 500).model_dump()
    assert len(compile_style(escaped)) <= 2000
    assert escaped["behavior_notes"] == "\x00" * 500


def test_schema_one_migration_backs_up_and_preserves_original_data(tmp_path):
    path = tmp_path / "yf.sqlite3"
    first = Store(path)
    memory = first.add_memory(memory_data())
    first.update_settings({"personality": "旧版本的个性设定"})
    first.close()
    with sqlite3.connect(path) as old:
        old.execute("DROP TABLE feature_profiles")
        old.execute("PRAGMA user_version=1")
    migrated = Store(path)
    try:
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert migrated.memory(memory["id"])["outline"] == "第一次开发 yf"
        assert migrated.settings()["personality"] == "旧版本的个性设定"
        assert migrated.feature_profile()["version"] == 1
        snapshots = list((tmp_path / "backups").glob("before-schema-2-*.sqlite3"))
        assert len(snapshots) == 1
        with sqlite3.connect(snapshots[0]) as snapshot:
            assert snapshot.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        migrated.close()


def test_profile_included_in_export_and_backup(tmp_path, store):
    document = FeatureProfile(behavior_notes="需要一起保留下来的风格").model_dump()
    store.update_profile(document, expected_version=1)
    assert store.export()["feature_profiles"][-1]["document"] == document
    restored = Store(store.backup(tmp_path / "snapshot" / "yf.sqlite3"))
    try:
        assert restored.feature_profile()["document"] == document
    finally:
        restored.close()
