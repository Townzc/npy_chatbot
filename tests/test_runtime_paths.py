"""Installed wheels and extracted training bundles must retain their pinned inputs."""

from pathlib import Path

import pytest

from chattwin.runtime_paths import SOURCE_ASSETS, source_asset, source_root, training_python_path


def test_source_and_installed_resources_are_explicit(tmp_path, monkeypatch):
    from chattwin import runtime_paths

    checkout = source_root()
    assert (checkout / "src/chattwin/runtime_paths.py").is_file()
    assert source_asset("training/uv.lock").is_file()
    with pytest.raises(ValueError, match="unknown"):
        source_asset("../../owner-token")
    installed = tmp_path / "site-packages/chattwin"
    (installed / "resources/source/training").mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "package_root", lambda: installed)
    with pytest.raises(ValueError, match="missing"):
        source_root()
    for relative in SOURCE_ASSETS:
        (installed / "resources/source" / relative).write_bytes((checkout / relative).read_bytes())
    assert source_root() == installed / "resources/source"
    assert (
        source_asset("training/uv.lock").read_bytes()
        == (checkout / "training/uv.lock").read_bytes()
    )


def test_training_interpreter_override_preserves_venv_symlink(tmp_path, monkeypatch):
    target = tmp_path / "venv-python"
    target.symlink_to(Path("/usr/bin/python3"))
    monkeypatch.setenv("CHATTWIN_TRAINING_PYTHON", str(target))
    assert training_python_path() == target
    monkeypatch.setenv("CHATTWIN_TRAINING_PYTHON", "relative/python")
    with pytest.raises(ValueError, match="absolute"):
        training_python_path()


def test_cli_worker_uses_explicit_interpreter_and_preserves_gpu_selection(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from chattwin.cli import app

    output = tmp_path / "invocation.json"
    interpreter = tmp_path / "python"
    interpreter.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\n"
        f"open({str(output)!r}, 'w').write(json.dumps({{'arguments':sys.argv[1:],'environment':dict(os.environ)}}))\n"
    )
    interpreter.chmod(0o700)
    monkeypatch.setenv("CHATTWIN_TRAINING_PYTHON", str(interpreter))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setenv("QQ_ACCESS_TOKEN", "synthetic-private-key")
    result = CliRunner().invoke(app, ["train", "run", str(tmp_path / "spec.json")])
    assert result.exit_code == 0, result.output
    invocation = json.loads(output.read_text())
    assert invocation["arguments"][:3] == ["-m", "chattwin.training.worker", "train"]
    assert invocation["environment"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert "QQ_ACCESS_TOKEN" not in invocation["environment"]
