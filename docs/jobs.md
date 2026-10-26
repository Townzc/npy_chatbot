# 持久化训练任务与私有训练包

训练任务已接入 SQLite `jobs` 表和独立子进程：队列、状态、心跳、取消、重启中断、单 worker 锁和真实训练产物均有可执行路径。核心服务不加载 PyTorch，不在对话模型中运行训练。长文件校验、环境探针与导出在后台线程执行，训练本身在独立 Python 环境执行，不占用控制页的接管流程。

## 任务生命周期

`queued → validating → running → succeeded / failed / cancelled / interrupted`。

- `JobManager.startup()` 获取实例 job-worker 锁。重启前遗留的 queued/validating/running 全部标 interrupted，不自动恢复训练。
- 同时最多一个训练子进程。子进程额外持有 execution lease，因此即使 API 父进程异常退出，旧子进程未结束时也不会启动第二个训练执行。
- API 提交只接受冻结 dataset ID、Persona、关系和受限超参数；输出目录、取消标记与 spec 路径由系统产生，用户不能提交 shell、任意输出路径或 QQ 凭证。
- 默认只从本机缓存读取固定 Qwen 底座。没有训练依赖、Linux/CUDA 或 bf16 能力时，任务明确失败，未开始模型下载/训练。
- `allow_model_download=true` 是明确选择允许公开底座下载；它不会自动租 GPU，也不会上传数据。默认 false。
- 运行中取消通过私有 flag 和进程组 SIGTERM；5 秒仍未退出则终止进程组。取消状态不能作为成功产物使用。关闭服务时正在运行的任务标 interrupted。
- `succeeded` 要求 worker 成功退出、status.json 为 succeeded、产物文件 hash 和 scope 通过；worker 本身还要求实际参数更新、保存和新进程加载。

任务登记、实际启动、成功产物登记以及训练包装配，与来源删除共用 `data-management.lock`。INSERT 事务和启动/完成事务再次检查 dataset 状态/hash，避免“预检时有效、登记时已撤销”的竞态。来源撤销后的任务详情明确 `artifact_ready=false`，已有模型权重仍不等于已遗忘。

`supports_reference_training` 仅表示探针检查满足尝试 Linux/CUDA 训练的前提，不是该 GPU 已通过显存/质量验收。当前真实证据仍是 tiny CPU 模型；Qwen 4B 正式训练与 T24 尚未通过。

## 应用集成

```python
from chattwin.jobs import JobManager
from chattwin.api.job_routes import job_router

manager = JobManager(store)
# FastAPI lifespan 启动时：await manager.startup()
# 关闭 store 前：await manager.close()
app.include_router(job_router(
    store, lambda: app.state.coordinator, authenticate, manager=manager
))
```

应用沿用本人 Bearer 认证。JobManager 不持有 QQ token、管理页凭证或供应商 API key。子进程环境通过显式白名单生成，禁用隐式 Hugging Face token 与遥测。

## API

| 方法与路径 | 行为 |
|---|---|
| GET `/api/v1/training-environment` | 只读探针：训练 Python/依赖版本、CUDA/bf16、阻塞项和固定参考模型；不加载模型 |
| POST `/api/v1/training-jobs` | 校验已登记冻结数据集，202 返回 JobView |
| GET `/api/v1/training-jobs` | 最近最多 200 个训练任务；可同时指定 persona_id 与 relationship_id |
| GET `/api/v1/training-jobs/{id}` | 当前状态、step、loss、progress、心跳、取消与产物 readiness |
| POST `/api/v1/training-jobs/{id}/cancel` | 幂等请求取消；终态任务保持原状态 |
| GET `/api/v1/jobs`、`/api/v1/jobs/{id}` | 对应任务列表/状态别名 |
| GET `/api/v1/jobs/{id}/logs` | 最多 100 条结构化事件；不返回原始 stdout/stderr 或聊天内容 |
| POST `/api/v1/training-bundles` | 用同一请求结构下载一个私有 ZIP；无 GPU/训练依赖也可导出 |

训练提交与训练包请求示例：

```json
{
  "dataset_id": "FROZEN_DATASET_ID",
  "persona_id": "PERSONA_ID",
  "relationship_id": "RELATIONSHIP_ID",
  "precision": "bfloat16",
  "rank": 8,
  "alpha": 16,
  "dropout": 0.05,
  "max_sequence_length": 1024,
  "batch_size": 1,
  "gradient_accumulation": 4,
  "learning_rate": 0.0002,
  "epochs": 1,
  "max_steps": 100,
  "seed": 42,
  "allow_model_download": false
}
```

JobView 包含 id、kind、status、scope、dataset_id、创建/更新时间、phase、step、progress、heartbeat、cancel_requested、error_code/error_summary、output_path、artifact_ready 和 loss。loss 可为空；progress 是步骤进度，不是质量评分。error_summary 为固定脱敏说明，完整 worker 错误只保留在私有输出目录。

## 私有文件与训练包

管理任务存于 `DATA_DIR/training-jobs/{job_id}/`：spec.json、取消标记、manager-result.json 和 artifact/。artifact/ 是独立 worker 生成的权重、manifest 和报告。数据库只保存任务元数据与最多 100 条事件。

导出的 ZIP 包含：

- 明确所选关系的完整冻结 train/validation/test JSONL 和原 manifest。
- 独立 worker 源码、项目/训练环境 pyproject 与锁文件、许可证、配置和启动器。
- `bundle-manifest.json`：每个文件的 SHA-256/size、数据集 hash、scope，以及明确的私人数据标识。

不包含登录凭证、QQ 会话、模型 API key、预训练底座或 adapter。API 下载完成后删除服务器临时 ZIP；浏览器下载副本由用户自行保管。这个包含私人聊天训练数据，不能加入公共仓库。

训练包完成导出后是独立快照。后续删除源数据不能召回已经传给浏览器或用户复制出去的副本，必须由用户同时删除这些副本；本项目不把源删除描述为外部副本已经清除。

把包解压到用户自己的 Linux/CUDA 环境、Git 工作区外：

```sh
uv sync --project training --locked
uv run --project training --locked python run_training.py --output /private/path/new-job
```

默认本地缓存加载；确需公开模型下载时，用户显式加 `--allow-model-download`。启动器验证数据集 hash、固定模板/底座/依赖版本并执行真实 worker。无 GPU 时不能通过这一步假装训练完成。

## 本次验证

2026-10-26：`uv run pytest -q tests/test_jobs.py` **8 passed**；Ruff 与 mypy 通过。

测试包括缺依赖诚实失败、队列取消、运行进程停止、单 manager 锁、孤儿 execution lease、重启不恢复、原始进程输出不泄漏、认证和 scope 拒绝、无 GPU 导出。进程睡眠/错误注入测试只验证进程控制协议，不能作为真实训练证据。

另外实际执行了 JobManager → 独立 Python → tiny Qwen3 LoRA 更新 → 保存 → 新进程重新加载；检查参数更新大于零、训练/加载 PID 不同，报告标记 `tiny_cpu_smoke`。

导出包也做了独立安装验证：19 个文件、78,024 bytes，解压后 `uv sync --project training --locked` 成功，并从导出源码运行真实 tiny smoke；最大参数变化 0.1608262，新进程加载成功。包内不包含 Qwen 4B 权重，未运行正式 Qwen 训练。

完整 T23 还需结合前端与模型登记进行整体验收；真实 GPU 基座训练、B0–B3 质量比较、模型切换/回滚和真实用户数据效果仍需单独证据。

## 从 wheel 安装后的训练环境

已安装的 wheel 会携带与此发行版对应的主项目/训练项目 `pyproject.toml`、`uv.lock` 和 LICENSE，位置由 `chattwin.runtime_paths` 统一解析；训练包从已安装的 Python 模块复制 worker，不依赖某个开发者的 Git 目录。导出包也包含该资源解析器，解压后正常使用它自己的冻结锁文件。

源码开发默认使用 `training/.venv/bin/python`。wheel 用户应明确设置 `CHATTWIN_TRAINING_PYTHON=/absolute/path/to/training-env/bin/python`（Windows 为对应 `Scripts/python.exe`），然后启动应用。该解释器环境必须安装**同一版本完整 ChatTwin wheel**和 `training/pyproject.toml` 固定的 PyTorch/Transformers/PEFT 等依赖；只装模型依赖不包含后台作业 runner。路径必须绝对路径，保留 venv 的原始解释器路径，不追随 symlink 改成系统 Python。不会自动安装训练环境或租用 GPU。

独立导出的精简训练包以 `run_training.py` 运行，包含训练模块但不包含完整管理 API/jobs/UI；因此它的环境不能直接充当管理应用的作业解释器，除非另安装完整对应版本 wheel。CUDA/平台兼容要求仍与训练文档一致。

安装路径实证：`uv build --wheel` 后，在仓库外新 venv 安装 wheel，确认模块来自 `site-packages`，经鉴权 API 创建虚构 demo、构建数据集、下载训练包成功；20 个包内文件逐个 SHA-256 核验通过，下载后临时 ZIP 删除。该包再在新环境运行 `uv sync --project training --locked`，真实 tiny CPU LoRA 训练 8 步并由不同 PID 重新加载成功。此证据只证明安装/导出/worker 可运行，不证明 CUDA 或个人聊天质量。
