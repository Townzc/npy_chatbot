"""Explicit owner download of one private frozen dataset plus a runnable worker."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from chattwin.runtime_paths import SOURCE_ASSETS, package_root, source_asset, training_code_hash
from chattwin.training.spec import TrainingSpec, validate_dataset

from .manager import JobManager
from .models import TrainingJobRequest

LAUNCHER = '''"""Run the included private dataset with the pinned worker; no uploads."""
import argparse
import json
from pathlib import Path
from chattwin.training.spec import TrainingSpec, prepare_spec
from chattwin.training.worker import train

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--allow-model-download", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent
configuration = json.loads((root / "configuration.json").read_text())
spec = prepare_spec(root / "dataset", args.output.resolve())
spec = TrainingSpec.model_validate(spec.model_dump() | configuration | {
    "local_files_only": not args.allow_model_download,
})
result = train(spec)
print(json.dumps({"status": result["status"], "output": str(spec.output_path)}, ensure_ascii=False))
'''

BUNDLE_README = """# ChatTwin 私有训练包

本文件夹包含所选关系的完整冻结 train/validation/test 数据，含私人聊天内容。
不包含 QQ/控制页/模型 API 凭证，不包含预训练权重，不自动上传任何内容。
提供 worker 源码、Python 依赖锁文件和启动器。只导出训练所需模块，核心完整应用 UI/QQ 运行器不在此包内。

在用户自己的 Linux/CUDA 主机解压到 Git 工作区外，安装 uv 和 Python 3.12 后：

    uv sync --project training --locked
    uv run --project training --locked python run_training.py --output /private/path/new-job

默认仅从本机缓存加载固定模型。确需下载公开底座时，在上面运行命令末尾显式增加
`--allow-model-download`。不会自动租 GPU，CUDA 不可用会失败，不会伪装训练成功。
本包不保证你的 GPU 显存足够。先缩小 steps 做 dry run，记录峰值显存。

训练成功需要真实更新、保存、新进程加载。报告是执行证据，仍需 B0–B3 保留测试集和人工质量评测。
数据修正需导出新版本。删除源聊天不会自动从已有模型权重遗忘。

bundle-manifest.json 记录每个文件的 SHA-256 与字节数；校验用于发现损坏，没有数字签名。
"""


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("bundle inputs must be regular non-symlink files")
    if any(parent.is_symlink() for parent in source.parents):
        raise ValueError("bundle input parent must not be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copyfile(source, destination, follow_symlinks=False)
    destination.chmod(0o600)


def create_training_bundle(manager: JobManager, request: TrainingJobRequest) -> tuple[Path, dict]:
    with manager.data_lock:
        return _create_training_bundle_locked(manager, request)


def _create_training_bundle_locked(
    manager: JobManager, request: TrainingJobRequest
) -> tuple[Path, dict]:
    # No environment probe here: exporting is useful precisely when no GPU is available.
    exports = manager.store.root / "training-bundles"
    exports.mkdir(exist_ok=True, mode=0o700)
    bundle_id = str(uuid4())
    stage = Path(tempfile.mkdtemp(prefix=".building-", dir=exports))
    archive = exports / (bundle_id + ".zip")
    try:
        spec = manager.spec_for_request(request, exports / "not-started")
        dataset = validate_dataset(spec)
        for name in ("manifest.json", "train.jsonl", "validation.jsonl", "test.jsonl"):
            _copy_file(spec.dataset_path / name, stage / "dataset" / name)
        validate_dataset(
            TrainingSpec.model_validate(spec.model_dump() | {"dataset_path": stage / "dataset"})
        )
        for relative in SOURCE_ASSETS:
            _copy_file(source_asset(relative), stage / relative)
        for name in ("__init__.py", "runtime_paths.py"):
            _copy_file(package_root() / name, stage / "src/chattwin" / name)
        training_source = package_root() / "training"
        for source in sorted(training_source.rglob("*.py")):
            _copy_file(
                source, stage / "src/chattwin/training" / source.relative_to(training_source)
            )
        configuration = request.model_dump(
            exclude={"dataset_id", "persona_id", "relationship_id", "allow_model_download"}
        )
        (stage / "configuration.json").write_text(json.dumps(configuration, indent=2))
        (stage / "run_training.py").write_text(LAUNCHER)
        (stage / "README.md").write_text(BUNDLE_README)
        if "source:" + training_code_hash(stage / "src/chattwin") != spec.code_version:
            raise ValueError("training source changed while exporting; prepare a new bundle")
        files = {}
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                content = path.read_bytes()
                files[str(path.relative_to(stage))] = {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                }
        manifest = {
            "schema_version": "1.0",
            "bundle_id": bundle_id,
            "dataset_id": dataset["id"],
            "dataset_hash": dataset["dataset_hash"],
            "training_code_version": spec.code_version,
            "persona_id": spec.persona_id,
            "relationship_id": spec.relationship_id,
            "files": files,
            "contains_private_training_data": True,
            "credentials_included": False,
            "weights_included": False,
            "automatic_upload": False,
        }
        (stage / "bundle-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as writer:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    writer.write(path, str(path.relative_to(stage)))
        archive.chmod(0o600)
        with archive.open("rb") as handle:
            os.fsync(handle.fileno())
        return archive, manifest
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
