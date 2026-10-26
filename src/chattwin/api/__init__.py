"""Authenticated local owner API. Live QQ is configured separately from sandbox."""

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from chattwin import __version__
from chattwin.api.control_routes import control_router
from chattwin.api.data_routes import data_router
from chattwin.api.job_routes import job_router
from chattwin.api.ops_routes import ops_router
from chattwin.auth import OwnerAuth, auth_router
from chattwin.channels import FakeChannel
from chattwin.channels.onebot import OneBotAdapter
from chattwin.conversation import ConversationEngine
from chattwin.domain import Binding, Contract, DomainError, ModeCommand, Scope, uid
from chattwin.importers import DataService
from chattwin.jobs import JobManager
from chattwin.models import configured_provider
from chattwin.models.registry import ModelRegistry, model_router
from chattwin.outbox import Coordinator
from chattwin.storage import Store, bindings, memories, personas, relationships
from chattwin.usage import BudgetService, usage_router


class NamedInput(Contract):
    name: str = Field(min_length=1, max_length=100)


class RelationshipInput(NamedInput):
    persona_id: str


class SandboxInput(Contract):
    binding_id: str
    text: str = Field(min_length=1, max_length=4000)
    variant: Literal["B0", "B1", "B2", "B3"] = "B2"


class MemoryInput(Scope):
    text: str = Field(min_length=1, max_length=2000)
    source_message_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False


class NotificationStatus(Contract):
    id: str
    kind: str
    status: str
    text: str


class ModeStatus(Contract):
    binding_id: str
    mode: str
    control_epoch: int
    context_seq: int
    payload: dict
    notifications: list[NotificationStatus]
    in_flight: list[str]
    ai_stopped: bool


class AppState(Contract):
    personas: list[dict]
    relationships: list[dict]
    bindings: list[Binding]
    training: dict
    provider: dict
    version: str


def owner_token(root: Path) -> str:
    if os.environ.get("CHATTWIN_TOKEN"):
        return os.environ["CHATTWIN_TOKEN"]
    path = root / "owner-token"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(32))
    path.chmod(0o600)
    return path.read_text().strip()


def seed_demo(store, data, coordinator):
    existing = store.rows(bindings, bindings.c.id == "demo-binding")
    if existing:
        return existing[0]["payload"]
    persona = data.create_persona("林间 · 虚构档案")
    relationship = data.create_relationship(persona["id"], "小禾 · 虚构好友")
    fixture = Path(__file__).parents[1] / "fixtures" / "canonical_messages.synthetic.jsonl"
    data.import_file(
        fixture,
        persona["id"],
        relationship["id"],
        "demo_owner",
        "demo_source_account",
        format="canonical_jsonl",
        mapping={"conversation_kind": "private"},
        confirm_human=True,
    )
    binding = Binding(
        id="demo-binding",
        persona_id=persona["id"],
        relationship_id=relationship["id"],
        channel_account_id=coordinator.channel.account_id,
        conversation_id="demo-conversation",
        recipient_id="demo_partner",
        channel="fake",
    )
    coordinator.create_binding(binding)
    return binding.model_dump()


def create_app(
    data_dir: Path | str | None = None, token: str | None = None, live_config: dict | None = None
) -> FastAPI:
    store = Store(data_dir)
    store.migrate()
    secret = token or owner_token(store.root)
    owner_auth = OwnerAuth(
        secret, require_session=os.environ.get("CHATTWIN_REQUIRE_SESSION") == "1"
    )
    data = DataService(store)
    provider = configured_provider()
    manager = JobManager(store)
    budget = BudgetService(store)

    @asynccontextmanager
    async def lifespan(app):
        instance_lock = store.instance_lock()
        instance_lock.acquire()
        live = None
        coordinator = None
        channel: FakeChannel | OneBotAdapter = FakeChannel()
        try:
            if live_config:
                from chattwin.channels.runtime import LiveRuntime
                from chattwin.models import MockProvider

                if isinstance(provider, MockProvider):
                    raise RuntimeError(
                        "Live QQ requires a configured real model; mock is sandbox-only"
                    )
                data.require_scope(live_config["persona_id"], live_config["relationship_id"])
                channel = OneBotAdapter(
                    live_config["url"],
                    live_config["account"],
                    os.environ.get("CHATTWIN_ONEBOT_TOKEN", ""),
                    allow_send=True,
                )
                channel.allowed_recipients = {live_config["recipient"]}
                await channel.open()
            coordinator = Coordinator(store, channel)
            app.state.coordinator = coordinator
            app.state.conversation = ConversationEngine(
                coordinator, provider, data, registry, budget
            )

            async def sources_revoked(result):
                for job_id in result.get("cancel_job_ids", []):
                    manager.cancel(job_id)

            coordinator.on_sources_revoked = sources_revoked
            await manager.startup()
            app.state.generations = {}
            if live_config:
                existing = store.rows(
                    bindings,
                    bindings.c.active.is_(True),
                    bindings.c.channel_account_id == live_config["account"],
                    bindings.c.conversation_id == live_config["recipient"],
                )
                binding = Binding(
                    id=existing[0]["id"] if existing else uid(),
                    persona_id=live_config["persona_id"],
                    relationship_id=live_config["relationship_id"],
                    channel_account_id=live_config["account"],
                    conversation_id=live_config["recipient"],
                    recipient_id=live_config["recipient"],
                    channel="onebot",
                )
                coordinator.create_binding(binding)
                live = LiveRuntime(coordinator, app.state.conversation, binding)
                live.start()
            app.state.live = live
            yield
        finally:
            if live:
                await live.close()
            await manager.close()
            if coordinator:
                await coordinator.close()
            if isinstance(channel, OneBotAdapter):
                await channel.close()
            store.close()
            instance_lock.release()

    app = FastAPI(title="ChatTwin", version=__version__, lifespan=lifespan)
    app.state.store = store
    registry = ModelRegistry(store, provider, lambda: app.state.coordinator, budget=budget)
    app.state.registry = registry
    app.state.jobs = manager
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
        + os.environ.get("CHATTWIN_ALLOWED_HOSTS", "").split(","),
    )
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and (
            urlparse(origin).netloc != request.headers.get("host")
            or urlparse(origin).scheme != request.url.scheme
        ):
            return JSONResponse(
                {"code": "ORIGIN_REJECTED", "detail": "Cross-origin control is disabled"},
                status_code=403,
            )
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"code": "BAD_LENGTH"}, status_code=400)
        if length > 25 * 1024 * 1024:
            return JSONResponse({"code": "UPLOAD_TOO_LARGE"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    async def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not owner_auth.valid(credentials.credentials):
            raise DomainError("UNAUTHENTICATED", "本人访问凭证无效", 401)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status)

    auth = [Depends(authenticate)]

    def state() -> AppState:
        return AppState(
            personas=[r["payload"] for r in store.rows(personas)],
            relationships=[r["payload"] for r in store.rows(relationships)],
            bindings=[
                r["payload"]
                for r in store.rows(
                    bindings,
                    bindings.c.active.is_(True),
                    bindings.c.channel_account_id == app.state.coordinator.channel.account_id,
                )
            ],
            training={
                "available": manager.python.is_file(),
                "detail": "持久训练队列已接入；提交后先校验环境。正式 Qwen 需要 Linux/CUDA；tiny 验证不代表个人模型质量。",
            },
            provider={"name": provider.name, "remote": provider.remote},
            version=__version__,
        )

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": __version__, "mode": "local-sandbox"}

    @app.get("/api/v1/state", dependencies=auth)
    def get_state() -> AppState:
        return state()

    @app.post("/api/v1/demo", dependencies=auth)
    def demo() -> AppState:
        if live_config:
            raise DomainError(
                "SANDBOX_ONLY", "Synthetic demo is available only on the sandbox server"
            )
        seed_demo(store, data, app.state.coordinator)
        return state()

    @app.post("/api/v1/personas", dependencies=auth)
    def persona(body: NamedInput):
        return data.create_persona(body.name)

    @app.post("/api/v1/relationships", dependencies=auth)
    def relationship(body: RelationshipInput):
        return data.create_relationship(body.persona_id, body.name)

    @app.post("/api/v1/bindings", dependencies=auth)
    def binding(body: Scope):
        if live_config:
            raise DomainError(
                "SANDBOX_ONLY", "Live bindings are immutable and configured at startup"
            )
        data.require_scope(body.persona_id, body.relationship_id)
        result = Binding(
            **body.model_dump(),
            channel_account_id=app.state.coordinator.channel.account_id,
            conversation_id=uid(),
            recipient_id="sandbox-peer",
            channel="web",
        )
        app.state.coordinator.create_binding(result)
        return result

    @app.get("/api/v1/conversations/{binding_id}/status", dependencies=auth)
    def status(binding_id: str) -> ModeStatus:
        return ModeStatus(**app.state.coordinator.status(binding_id))

    @app.post("/api/v1/conversations/{binding_id}/mode", dependencies=auth)
    async def mode(binding_id: str, body: ModeCommand) -> ModeStatus:
        if body.action == "enable" and live_config and not app.state.coordinator.channel.verified:
            raise DomainError("BRIDGE_UNAVAILABLE", "Bridge identity is not verified", 503)
        if body.action == "enable":
            current = app.state.coordinator.status(binding_id)
            active_binding = store.rows(bindings, bindings.c.id == binding_id)[0]["payload"]
            registry.provider(
                current["payload"]["model_deployment_id"],
                active_binding["persona_id"],
                active_binding["relationship_id"],
            )
        await app.state.coordinator.command(binding_id, body)
        if body.action != "enable":
            for task in list(app.state.generations.get(binding_id, set())):
                task.cancel()
            if app.state.live:
                app.state.live.cancel_generation()
        if live_config:
            await app.state.coordinator.drain()
        else:
            await app.state.coordinator.settle()
        return ModeStatus(**app.state.coordinator.status(binding_id))

    @app.post("/api/v1/sandbox/messages", dependencies=auth)
    async def sandbox(body: SandboxInput):
        if live_config:
            raise DomainError("SANDBOX_ONLY", "Open the sandbox server for web test messages")
        task = asyncio.current_task()
        app.state.generations.setdefault(body.binding_id, set()).add(task)
        try:
            result = await app.state.conversation.reply(body.binding_id, body.text, body.variant)
            await app.state.coordinator.settle()
            return {**result, "status": app.state.coordinator.status(body.binding_id)}
        except asyncio.CancelledError as exc:
            raise DomainError("GENERATION_CANCELLED", "本人接管已取消生成") from exc
        finally:
            app.state.generations[body.binding_id].discard(task)

    async def upload(file):
        target_dir = store.root / "uploads"
        target_dir.mkdir(exist_ok=True, mode=0o700)
        suffix = Path(file.filename or "upload").suffix[:10]
        path = target_dir / (uid() + suffix)
        size = 0
        try:
            with path.open("xb") as handle:
                path.chmod(0o600)
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > 20 * 1024 * 1024:
                        raise DomainError(
                            "UPLOAD_TOO_LARGE", "First release upload limit is 20 MiB", 413
                        )
                    handle.write(chunk)
            return path
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    async def complete_thread(function, *args):
        # A cancelled HTTP request cannot release the version barrier while its
        # database-writing thread is still running.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    def parse_mapping(raw):
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("object required")
            return result
        except (ValueError, TypeError) as exc:
            raise DomainError("INVALID_MAPPING", "字段映射必须是 JSON 对象", 422) from exc

    @app.post("/api/v1/imports/inspect", dependencies=auth)
    async def inspect_import(
        file: UploadFile = File(),
        format: str = Form("auto"),
        source_account_id: str = Form("preview"),
        mapping: str = Form("{}"),
    ):
        path = await upload(file)
        try:
            return await asyncio.to_thread(
                data.inspect,
                path,
                format,
                {**parse_mapping(mapping), "source_account_id": source_account_id},
            )
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/v1/imports", dependencies=auth)
    async def run_import(
        file: UploadFile = File(),
        format: str = Form("auto"),
        source_account_id: str = Form(),
        persona_id: str = Form(),
        relationship_id: str = Form(),
        owner_sender_id: str = Form(),
        confirmed_human: bool = Form(False),
        mapping: str = Form("{}"),
    ):
        path = await upload(file)
        try:
            async with app.state.coordinator.scope_update(persona_id, relationship_id):
                return await complete_thread(
                    data.import_file,
                    path,
                    persona_id,
                    relationship_id,
                    owner_sender_id,
                    source_account_id,
                    format,
                    parse_mapping(mapping),
                    confirmed_human,
                )
        finally:
            path.unlink(missing_ok=True)

    @app.get("/api/v1/messages", dependencies=auth)
    def list_messages(persona_id: str, relationship_id: str):
        return data.list_messages(persona_id, relationship_id)

    @app.get("/api/v1/memories", dependencies=auth)
    def list_memories(persona_id: str, relationship_id: str):
        data.require_scope(persona_id, relationship_id)
        return [
            r["payload"]
            for r in store.rows(
                memories,
                memories.c.persona_id == persona_id,
                memories.c.relationship_id == relationship_id,
            )
            if not r["payload"].get("deleted")
        ]

    @app.post("/api/v1/memories", dependencies=auth)
    async def add_memory(body: MemoryInput):
        async with app.state.coordinator.scope_update(body.persona_id, body.relationship_id):
            return data.add_memory(**body.model_dump())

    @app.delete("/api/v1/memories/{memory_id}", dependencies=auth)
    async def delete_memory(memory_id: str):
        found = store.rows(memories, memories.c.id == memory_id)
        if not found:
            raise DomainError("MEMORY_NOT_FOUND", "Memory not found", 404)
        row = found[0]
        async with app.state.coordinator.scope_update(row["persona_id"], row["relationship_id"]):
            return data.update_memory(
                memory_id, row["persona_id"], row["relationship_id"], deleted=True
            )

    @app.post("/api/v1/datasets", dependencies=auth)
    async def dataset(body: Scope):
        async with app.state.coordinator.scope_update(body.persona_id, body.relationship_id):
            return await complete_thread(data.build_dataset, body.persona_id, body.relationship_id)

    app.include_router(data_router(store, lambda: app.state.coordinator, authenticate))
    app.include_router(
        job_router(store, lambda: app.state.coordinator, authenticate, manager=manager)
    )
    app.include_router(model_router(registry, authenticate))
    app.include_router(ops_router(store, authenticate))
    app.include_router(usage_router(budget, authenticate))
    app.include_router(control_router(store, lambda: app.state.coordinator, authenticate))
    app.include_router(auth_router(owner_auth))
    static = Path(__file__).parents[1] / "web_dist"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app
