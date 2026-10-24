import pytest
from fastapi.testclient import TestClient
from yf.app import create_app
from yf.config import Config
from yf.store import Store


class TestModel:
    __test__ = False
    configured = True

    def __init__(self):
        self.prompts = []
        self.extractions = []
        self.result = {"memories": [], "feedback": []}
        self.failure = None

    async def stream(self, messages):
        self.prompts.append(messages)
        yield "我听到了，"
        if self.failure:
            raise self.failure
        yield "我们慢慢聊。"

    async def extract(self, context):
        self.extractions.append(context)
        return self.result(context) if callable(self.result) else self.result

    async def close(self):
        pass


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "yf.sqlite3")
    yield instance
    instance.close()


@pytest.fixture
def model():
    return TestModel()


@pytest.fixture
def client(tmp_path, model):
    app = create_app(
        Config(data_dir=tmp_path, model_name="test-only"), provider=model, background=False
    )
    with TestClient(app) as connection:
        yield connection


def memory_data(**kwargs):
    return {
        "outline": "第一次开发 yf",
        "detail": "一起讨论了长期陪伴与记忆",
        "importance": 0.5,
        "confidence": 1,
        "reason": "用户明确陈述",
        "tags": ["开发"],
        "occurred_on": None,
        "missing_details": [],
        "pinned": False,
    } | kwargs
