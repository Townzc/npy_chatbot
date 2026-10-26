import json
import shutil
from pathlib import Path

import typer

from chattwin.host import write_launch_agent
from chattwin.storage import default_data_dir

app = typer.Typer(help="本机服务配置生成；不自动安装、启动或连接 QQ")


@app.command("launch-agent")
def launch_agent(
    destination: Path,
    executable: Path | None = None,
    data_dir: Path | None = None,
    port: int = 8765,
    allowed_host: str = "",
):
    found = executable or shutil.which("chattwin")
    if not found:
        raise typer.BadParameter("Specify --executable /absolute/path/to/chattwin")
    try:
        result = write_launch_agent(
            destination, Path(found), data_dir or default_data_dir(), port, allowed_host
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
