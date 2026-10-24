import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Config
from .memory import MemoryWorker, build_context
from .profile import ProfileRestore, ProfileUpdate
from .provider import ModelError, Provider
from .schemas import (
    ChatRequest,
    ConversationCreate,
    FeedbackRequest,
    MemoryCreate,
    PinRequest,
    SettingsUpdate,
    StrictModel,
)
from .store import Conflict, Missing, Store, uid


def event(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ForgetRequest(StrictModel):
    expected_memory_ids: list[str] = Field(min_length=1, max_length=10000)


def create_app(config=None, provider=None, background=True):
    config = config or Config.load()

    @asynccontextmanager
    async def lifespan(app):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        instance_lock = FileLock(config.data_dir / "service.lock")
        try:
            instance_lock.acquire(timeout=0)
        except Timeout as error:
            raise RuntimeError(
                "该数据目录已有 yf 服务运行，请使用已有页面或先关闭旧服务。"
            ) from error
        try:
            store = Store(config.data_dir / "yf.sqlite3")
        except Exception:
            instance_lock.release()
            raise
        model = provider or Provider(config)
        worker = MemoryWorker(store, model)
        app.state.store, app.state.provider, app.state.worker = store, model, worker
        task = asyncio.create_task(worker.run()) if background else None
        try:
            yield
        finally:
            worker.stopped.set()
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            try:
                await model.close()
            finally:
                store.close()
                instance_lock.release()

    app = FastAPI(title="your friend", version=__version__, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        origin = request.headers.get("origin")
        same_origin = str(request.base_url).rstrip("/")
        if (origin and origin != same_origin) or request.headers.get(
            "sec-fetch-site"
        ) == "cross-site":
            return JSONResponse({"detail": "此版本仅允许本机同源访问。"}, status_code=403)
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "手机配对尚未实现，请只在本机使用。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(Missing)
    async def missing_handler(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict_handler(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/status")
    def status():
        store = app.state.store
        return {
            "version": __version__,
            "model_configured": app.state.provider.configured,
            "model_name": config.model_name,
            "settings": store.settings(),
            "jobs": store.jobs(),
            "memory_preferences": store.preference_profile(),
            "feature_profile": store.feature_profile(),
            "profile_history": store.profile_history(),
            "retrieval": "中文字符组合与关键词检索；语义向量检索尚未接入",
            "fine_tuning_available": False,
            "platform": "本机验证版，Windows / Android 正式客户端尚未实现",
        }

    @app.patch("/api/settings")
    def settings(body: SettingsUpdate):
        return app.state.store.update_settings(body.model_dump(exclude_none=True))

    @app.get("/api/profile")
    def profile():
        return app.state.store.feature_profile()

    @app.put("/api/profile")
    def update_profile(body: ProfileUpdate):
        return app.state.store.update_profile(body.document.model_dump(), body.expected_version)

    @app.post("/api/profile/restore")
    def restore_profile(body: ProfileRestore):
        return app.state.store.restore_profile(body.version, body.expected_version)

    @app.get("/api/conversations")
    def conversations():
        return app.state.store.conversations()

    @app.post("/api/companion")
    def companion():
        return app.state.store.companion_conversation()

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: ConversationCreate):
        return app.state.store.create_conversation(body.title)

    @app.get("/api/conversations/{conversation_id}/messages")
    def messages(
        conversation_id: str, before: int | None = None, limit: int = Query(80, ge=1, le=100)
    ):
        return app.state.store.messages(conversation_id, before=before, limit=limit)

    @app.post("/api/conversations/{conversation_id}/chat")
    async def chat(conversation_id: str, body: ChatRequest):
        store, model = app.state.store, app.state.provider
        if not model.configured:
            raise HTTPException(
                503, "尚未配置模型；先在 .env 填写模型地址、名称及所需密钥，再重启服务。"
            )
        turn, replay = store.begin_turn(conversation_id, body.request_id, body.content)
        if replay:
            answer = store.one(
                "SELECT content FROM messages WHERE turn_id=? AND role='assistant'", (turn["id"],)
            )

            async def replay_events():
                yield event("delta", {"text": answer["content"]})
                yield event("done", {"turn_id": turn["id"], "replayed": True})

            return StreamingResponse(replay_events(), media_type="text/event-stream")
        try:
            context, recalled_ids, chars = build_context(
                store, config, conversation_id, body.content
            )
            store.set_recalled(turn["id"], recalled_ids)
        except Exception:
            store.finish_turn(turn["id"], "", "failed")
            raise

        async def generate():
            text, finished = "", False
            try:
                yield event(
                    "context",
                    {
                        "turn_id": turn["id"],
                        "memory_ids": recalled_ids,
                        "input_chars": chars,
                        "char_budget": config.context_chars,
                    },
                )
                async for chunk in model.stream(context):
                    if len(text) + len(chunk) > config.max_reply_chars:
                        raise ModelError("回答达到长度上限，已保留收到的部分，请分步继续。")
                    text += chunk
                    yield event("delta", {"text": chunk})
                if not text:
                    raise ModelError("模型未返回文本内容。")
                store.finish_turn(turn["id"], text, "completed")
                finished = True
                yield event("done", {"turn_id": turn["id"], "replayed": False})
            except asyncio.CancelledError:
                store.finish_turn(turn["id"], text, "cancelled")
                finished = True
                raise
            except Exception as error:
                store.finish_turn(turn["id"], text, "failed")
                finished = True
                logging.getLogger("yf.chat").warning("Chat failed (%s)", type(error).__name__)
                yield event(
                    "error",
                    {
                        "message": str(error)
                        if isinstance(error, ModelError)
                        else "回答生成失败，已保存原消息和收到的部分回答。"
                    },
                )
            finally:
                if not finished:
                    store.finish_turn(turn["id"], text, "cancelled")

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/memories")
    def memories(
        q: str = Query("", max_length=200), archive: bool = False, offset: int = Query(0, ge=0)
    ):
        return (
            app.state.store.retrieve(q, archive=archive, limit=30)
            if q
            else app.state.store.memories(offset=offset)
        )

    @app.post("/api/memories", status_code=201)
    def add_memory(body: MemoryCreate):
        return app.state.store.add_memory(body.model_dump())

    @app.get("/api/memories/{memory_id}")
    def memory(memory_id: str):
        return app.state.store.memory(memory_id, archive=True)

    @app.post("/api/memories/{memory_id}/feedback")
    def feedback(memory_id: str, body: FeedbackRequest):
        return app.state.store.feedback(memory_id, body.direction, body.reason)

    @app.patch("/api/memories/{memory_id}/pin")
    def pin(memory_id: str, body: PinRequest):
        return app.state.store.pin(memory_id, body.pinned)

    @app.get("/api/memories/{memory_id}/deletion-preview")
    def deletion_preview(memory_id: str):
        return app.state.store.deletion_preview(memory_id)

    @app.post("/api/memories/{memory_id}/forget")
    def forget(memory_id: str, body: ForgetRequest):
        return app.state.store.forget(memory_id, body.expected_memory_ids)

    @app.get("/api/archive")
    def archive(q: str = Query(min_length=1, max_length=200)):
        return app.state.store.search_archive(q)

    @app.get("/api/export")
    def export():
        return JSONResponse(
            app.state.store.export(),
            headers={"Content-Disposition": 'attachment; filename="yf-archive.json"'},
        )

    @app.post("/api/backup")
    def backup():
        name = "yf-backup-" + uid() + ".sqlite3"
        path = app.state.store.backup(config.data_dir / "backups" / name)
        return FileResponse(path, filename=name, media_type="application/octet-stream")

    web = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(web / "index.html")

    return app
