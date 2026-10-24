import asyncio
import json

import httpx
import pytest
from yf.config import Config
from yf.provider import ModelError, Provider


def test_openai_compatible_stream_and_memory_json(tmp_path):
    def handle(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-private-key"
        if body["stream"]:
            return httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n'
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"memories":[],"feedback":[]}'}}]}
        )

    async def run():
        provider = Provider(
            Config(
                data_dir=tmp_path,
                model_base_url="http://model.test/v1",
                model_name="chat",
                api_key="test-private-key",
            ),
            httpx.MockTransport(handle),
        )
        try:
            assert [
                chunk async for chunk in provider.stream([{"role": "user", "content": "你好"}])
            ] == ["你好"]
            assert await provider.extract({"messages": []}) == {"memories": [], "feedback": []}
        finally:
            await provider.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,text",
    [
        (401, "secret-body"),
        (200, 'data: {"choices":[{"delta":{"content":"部分"}}]}\n\n'),
        (200, 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'),
    ],
)
def test_provider_errors_do_not_expose_response_body_and_truncated_stream_is_failed(
    tmp_path, status, text
):
    async def run():
        provider = Provider(
            Config(data_dir=tmp_path, model_base_url="http://model.test/v1", model_name="chat"),
            httpx.MockTransport(lambda request: httpx.Response(status, text=text)),
        )
        try:
            with pytest.raises(ModelError) as error:
                async for _ in provider.stream([]):
                    pass
            assert "secret-body" not in str(error.value)
        finally:
            await provider.close()

    asyncio.run(run())
