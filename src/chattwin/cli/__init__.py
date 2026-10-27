import asyncio
import json
import os
import platform
from pathlib import Path

import typer

from chattwin.host.cli import app as host_app
from chattwin.storage import Store, default_data_dir

app = typer.Typer(help="ChatTwin 本地个人 AI；默认无真实发送")
app.add_typer(host_app, name="host")
imports_app = typer.Typer()
app.add_typer(imports_app, name="import")
dataset_app = typer.Typer()
app.add_typer(dataset_app, name="dataset")
qq_app = typer.Typer()
app.add_typer(qq_app, name="qq")
backup_app = typer.Typer()
app.add_typer(backup_app, name="backup")
train_app = typer.Typer()
app.add_typer(train_app, name="train")
model_app = typer.Typer()
app.add_typer(model_app, name="model")


@app.command()
def doctor():
    from importlib.metadata import version

    typer.echo(
        json.dumps(
            {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "core_version": version("chattwin"),
                "data_dir": str(default_data_dir()),
                "real_qq_verified": False,
                "reference_lora_verified": False,
                "model_configured": bool(os.environ.get("CHATTWIN_MODEL_URL")),
            },
            indent=2,
        )
    )


@app.command()
def token():
    """在本机终端显示本人登录凭证；请勿放入 URL 或共享日志。"""
    from chattwin.api import owner_token

    store = Store()
    typer.echo(owner_token(store.root))


@app.command()
def serve(port: int = 8765, host: str = "127.0.0.1"):
    """启动本地 API 与构建后的网页。远程入口尚待 T26 验收。"""
    import uvicorn

    from chattwin.api import create_app

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise typer.BadParameter(
            "This milestone supports loopback only; remote access is unverified"
        )
    uvicorn.run(create_app(), host=host, port=port, access_log=False)


@app.command()
def demo():
    """虚构历史 → 导入 → 开启通知 → 本地回复 → 本人接管。没有 QQ/模型 API 请求。"""
    from tempfile import TemporaryDirectory

    from chattwin.api import seed_demo
    from chattwin.channels import FakeChannel
    from chattwin.conversation import ConversationEngine
    from chattwin.domain import ModeCommand, uid
    from chattwin.importers import DataService
    from chattwin.models import MockProvider
    from chattwin.outbox import Coordinator

    async def run(root):
        store = Store(root)
        store.migrate()
        channel = FakeChannel()
        coordinator = Coordinator(store, channel)
        data = DataService(store)
        try:
            seed_demo(store, data, coordinator)
            await coordinator.command(
                "demo-binding",
                ModeCommand(command_id=uid(), action="enable", expected_control_epoch=0),
            )
            await coordinator.settle()
            engine = ConversationEngine(coordinator, MockProvider(), data)
            await engine.reply("demo-binding", "周末一起去看展吗？")
            await coordinator.settle()
            await coordinator.command(
                "demo-binding", ModeCommand(command_id=uid(), action="takeover")
            )
            await coordinator.settle()
            typer.echo(
                json.dumps(
                    {
                        "evidence": "synthetic local only",
                        "messages": [s.text for s in channel.started],
                        "final_mode": coordinator.status("demo-binding")["mode"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            await coordinator.close()
            store.close()

    with TemporaryDirectory(prefix="chattwin-demo-") as root:
        asyncio.run(run(root))


@imports_app.command("inspect")
def inspect_file(file: Path, format: str = "auto"):
    from chattwin.importers import inspect

    typer.echo(json.dumps(inspect(file, format), ensure_ascii=False, indent=2))


@imports_app.command("probe")
def probe_import_file(file: Path):
    """只读识别文件/备份类型，不显示文件名、账号、密钥或聊天正文，不解包。"""
    from chattwin.domain import DomainError
    from chattwin.importers.probe import probe

    try:
        result = probe(file)
    except DomainError as exc:
        typer.echo(json.dumps({"error": exc.code, "message": str(exc)}, ensure_ascii=False))
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@imports_app.command("run")
def import_file(file: Path, mapping: Path):
    from chattwin.importers import DataService

    store = Store()
    store.migrate()
    with store.instance_lock():
        result = DataService(store).import_file(file, **json.loads(mapping.read_text()))
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@dataset_app.command("build")
def build_dataset(persona: str, scope: str):
    from chattwin.importers import DataService

    store = Store()
    store.migrate()
    with store.instance_lock():
        result = DataService(store).build_dataset(persona, scope)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@qq_app.command("probe")
def probe(url: str, account: str):
    """只读核验桥版本与账号；从 CHATTWIN_ONEBOT_TOKEN 读取 token。"""
    from chattwin.channels.onebot import OneBotAdapter

    async def run():
        bridge = OneBotAdapter(url, account, os.environ.get("CHATTWIN_ONEBOT_TOKEN", ""))
        try:
            result = await bridge.open()
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            await bridge.close()

    asyncio.run(run())


@qq_app.command("serve")
def qq_serve(
    url: str,
    account: str,
    recipient: str,
    persona: str,
    scope: str,
    allow_send: bool = False,
    port: int = 8765,
):
    """用户在自己的终端显式启用指定 QQ 原私聊。此命令会实际发送通知和回复。"""
    if not allow_send:
        raise typer.BadParameter(
            "Use qq probe for read-only inspection; actual sends require --allow-send"
        )
    import uvicorn

    from chattwin.api import create_app

    uvicorn.run(
        create_app(
            live_config={
                "url": url,
                "account": account,
                "recipient": recipient,
                "persona_id": persona,
                "relationship_id": scope,
            }
        ),
        host="127.0.0.1",
        port=port,
        access_log=False,
    )


@backup_app.command("create")
def backup_create(destination: Path):
    from chattwin.ops import create_backup

    store = Store()
    store.migrate()
    typer.echo(json.dumps(create_backup(store, destination), ensure_ascii=False, indent=2))


@backup_app.command("inspect")
def backup_inspect(backup: Path):
    from chattwin.ops import inspect_backup

    typer.echo(json.dumps(inspect_backup(backup), ensure_ascii=False, indent=2))


@backup_app.command("restore")
def backup_restore(backup: Path, destination: Path):
    from chattwin.ops import restore_backup

    typer.echo(json.dumps(restore_backup(backup, destination), ensure_ascii=False, indent=2))


def training_process(module, arguments, *, model_server=False):
    import subprocess

    from chattwin.runtime_paths import training_python_path
    from chattwin.training.worker import worker_environment

    python = training_python_path()
    if not python.is_file():
        raise typer.BadParameter(
            "Install isolated training dependencies or set CHATTWIN_TRAINING_PYTHON to their absolute interpreter path"
        )
    environment = worker_environment()
    if model_server:
        environment["CHATTWIN_MODEL_TOKEN"] = os.environ.get("CHATTWIN_MODEL_TOKEN", "")
    result = subprocess.run([str(python), "-m", module, *arguments], env=environment, check=False)
    raise typer.Exit(result.returncode)


@train_app.command("prepare")
def train_prepare(dataset: Path, output: Path, spec: Path, profile: str = "reference"):
    from chattwin.training.spec import prepare_spec

    if profile not in {"reference", "rtx4090-dry-run"}:
        raise typer.BadParameter("profile must be reference or rtx4090-dry-run")
    prepared = prepare_spec(
        dataset, output, profile="rtx4090-dry-run" if profile == "rtx4090-dry-run" else "reference"
    )
    spec.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with spec.open("x") as handle:
        spec.chmod(0o600)
        handle.write(prepared.model_dump_json(indent=2))
    typer.echo(f"Training spec created: {spec}; hardware still UNVERIFIED")


@train_app.command("doctor")
def train_doctor():
    """Inspect the isolated worker and visible GPUs without loading or downloading a model."""
    from chattwin.jobs.environment import inspect_environment

    typer.echo(inspect_environment().model_dump_json(indent=2))


@train_app.command("run")
def train_run(spec: Path):
    training_process("chattwin.training.worker", ["train", "--spec", str(spec.resolve())])


@train_app.command("cancel")
def train_cancel(spec: Path):
    from chattwin.training.spec import TrainingSpec

    configuration = TrainingSpec.model_validate_json(spec.read_text())
    if configuration.cancel_path is None:
        raise typer.BadParameter("Spec has no cancel_path")
    configuration.cancel_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    configuration.cancel_path.touch(mode=0o600)
    typer.echo("Cancellation requested; inspect status.json for completion")


@model_app.command("serve")
def model_serve(artifact: Path, port: int = 8766):
    training_process(
        "chattwin.training.serve",
        ["--artifact", str(artifact.resolve()), "--port", str(port)],
        model_server=True,
    )
