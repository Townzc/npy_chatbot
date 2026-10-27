# ChatTwin

本地个人 AI 工作台。导入已经导出的聊天记录，明确确认本人身份，建立关系内的风格与记忆，在网页试聊，或通过独立 worker 训练 LoRA。

**当前是可运行的开发版，不是完整 QQ v1。** 无账号、无模型密钥即可运行虚构 demo；已实现真实 LoRA 训练代码并完成 CPU tiny 参数更新及新进程重载。真实 QQ 原会话、正式 Qwen CUDA 训练、手机离网控制及 7 天试运行仍未验收。逐项状态见 [docs/tasks.md](docs/tasks.md)，首批证据见 [docs/evidence/milestone-2026-10-26.md](docs/evidence/milestone-2026-10-26.md)，管理闭环见 [第二批报告](docs/evidence/management-milestone-2026-10-26.md)。

## 快速开始

环境：Python 3.12、uv；构建网页时需要 Node.js 22+、pnpm 10。核心不依赖 PyTorch/CUDA。当前已在 macOS arm64 实测；CI 模板在 `ci/github-actions.template.yml`；当前 GitHub 凭证缺 `workflow` 权限，工作流尚未启用或远程执行，不能据此宣称其他系统已验证。

```sh
cd /Users/zhicetang/Desktop/npy_chatbot
uv sync --locked --group dev
uv run chattwin demo
sh scripts/build_web.sh
uv run chattwin serve
```

打开 [本地工作台](http://127.0.0.1:8765)，另开终端运行 `uv run chattwin token`，将输出的本人凭证填入登录页。点击“开始虚构数据演示”，再点击“开启 AI”。脚本会优先使用 PATH 中的 Node/pnpm，本机缺少时可使用 Codex 自带运行时。

1. 开启时先创建固定通知 **对方已切换为ai模式**，收到通道确认后才允许回复。
2. 网页试聊使用显式标注的 MockProvider；它是工程演示，不是训练后的个人模型。
3. 本人接管先完成停止屏障，再发送 **本人已接管**；通知失败不会恢复 AI。
4. 演示消息只进入本地 FakeChannel，不会发送至 QQ。

默认数据目录：`~/Library/Application Support/ChatTwin`。可通过 `CHATTWIN_DATA_DIR` 指定独立私有目录，程序拒绝将运行数据放入 Git 工作树。`chat_record/` 是现有用户输入，已整体忽略；本轮未复制正文或尝试上传它。

## 导入自己的数据

在网页新建档案与关系，进入“导入与身份”，选择文件和来源账号稳定 ID。先预览，再从真实 sender_id 中选择本人；只有主动确认的本人 human 来源可作训练目标。昵称和导出者都不决定身份。

| 格式 | 当前边界 |
|---|---|
| ChatLab v0.0.2 JSON/JSONL | 合成格式、秒级时间、null、未知类型、引用及重复测试通过；实际导出兼容待具体样本 |
| 通用 CSV | 字段映射、时区、秒/毫秒、BOM/换行；10 万条合成导入已测 |
| ChatTwin JSONL v1 | 导入/导出回读与 sidecar hash/数量/范围核验；未声明会话类型按 unknown 排除训练 |
| QCE 单文件 JSON | 参考 v6.3.2 的导出核心 0.1.0 schema；解析/身份/数据集与网页合成验证通过，真实导出及分块 JSONL 未验收；见[兼容边界](docs/qce-compatibility.md) |
| QQ .bak / 数据库容器 | 只读识别 MSG0、QQ_NT DB、普通 SQLite/ZIP；不支持自动解密、提取或假装导入 |

本机 `chat_record` 有 8 个无扩展名文件，约 140 MiB；后续头部检查识别出其中 4 个为 MSG0，另外 4 个仍未识别。用户又提供了一份电脑 QQ“导出聊天记录”生成的 `.bak`：外层 ZIP 内有 4 个 MSG0 数据库，归档 CRC 通过，聊天内容仍未解密。用户最新确认导出时电脑 QQ 能看到所需旧记录，接下来从保存记录的电脑导出可读 JSON；仍需确认具体是哪台电脑。没有把文件名、账号或正文写入 Git。见 [备份与可读导出的边界](docs/qq-setup-research.md)。

可用 `uv run chattwin import probe /absolute/path/to/export.bak` 只读诊断文件类型。命令不显示文件名、密钥或正文，不解包、不创建聊天数据库；识别成功也不表示已导入。见 [本次检查证据与限制](docs/evidence/qq-bak-inspection-2026-10-27.md)。

网页上传上限为 20 MiB；大文件使用 CLI。成功解析提供的条目不代表历史完整。群聊和未知会话类型可保留预览，默认不进入双人关系的风格、记忆或训练。详见 [数据实现说明](docs/data-implementation.md)。

## 连接实际模型

默认 MockProvider 不发网络请求。要使用已选择的模型服务，在启动服务的环境中设置 `CHATTWIN_MODEL_URL`（例如本地端点的 `/v1`）、`CHATTWIN_MODEL_NAME`、`CHATTWIN_MODEL_KEY`；可设 `CHATTWIN_MODEL_MAX_CALLS` 限制每次进程生命周期的请求次数。网页可设置持久月度调用/token 上限及可选费用估算；未知消耗保留预留，重启不清零。详见 [模型与预算](docs/models-and-budget.md)。

HTTP 请求带当前 persona/relationship metadata；不同服务可能拒绝扩展字段，兼容性须单独验证。使用远端模型时，本轮选定的上下文和记忆会发往该端点。网页显示“使用远端模型”，不会宣称完全本地。

## 真正 LoRA

```sh
uv sync --project training --locked
uv run --project training --locked python -m chattwin.training.smoke
```

这会创建随机 tiny 底座，真实执行反向传播、LoRA 参数更新、保存与新进程重载对照，输出在仓库外。tiny 没有个人风格质量结论。

正式训练固定 `Qwen/Qwen3-4B-Instruct-2507` revision、tokenizer/template 和数据集 hash；需用户提供 Linux/CUDA 环境。完整步骤、产物认证推理、取消及依赖隔离见 [docs/training.md](docs/training.md)。不自动租用 GPU、上传训练数据或发布模型。

用户计划在 AutoDL 租卡，首轮只需按 [AutoDL 单卡步骤](docs/autodl.md) 准备 1 张 4090：已有 2 步试运行预设、梯度检查点、显存报告和安装前只读容量检查。尚未取得 SSH，不能声称已通过 4090 验收。没有桥或可读导出时，按 [QQ 接入与导出步骤](docs/qq-setup-research.md) 准备环境。

CLI 同时提供 `chattwin train prepare/run/cancel` 和 `chattwin model serve`；`train cancel` 的参数是 TrainingSpec 路径。网页已有持久作业队列、预检/进度/日志/取消、私有训练包下载、产物登记和模型版本测试/切换/回滚。训练包已从隔离 wheel 安装中导出，解包后真实 tiny LoRA 更新与新进程加载通过。详见 [jobs.md](docs/jobs.md) 与 [evaluation.md](docs/evaluation.md)。

## QQ 原私聊

已有自写 OneBot v11 正向 WS 适配器、选定私聊接收循环、账号核验、纯文本消息段、唯一发送器和断连暂停。协议测试使用本地测试服务，**不是 QQ 实机测试**。

本机 QQ 7.0.2 已存在，但没有已连接的桥。已在仓库外下载官方 QCE v6.3.2 Mac 包并核验 SHA-256，包内 NapCat 为 4.18.28；尚未启动 QQ 副本或登录。项目不捆绑或再分发这些上游程序。启动会改变 QQ 副本的沙箱保护并共享真实数据库，QCE HTTP 默认监听所有网卡；准备状态和边界见 [本机 QCE 准备](docs/evidence/qce-preparation-2026-10-27.md)。

只读探针：

```sh
uv run chattwin qq probe --url ws://127.0.0.1:6700 --account ACCOUNT_ID
```

用户自行配置桥及分离凭证后，可以在自己的终端运行明确选定会话的 `chattwin qq serve --url ... --account ... --recipient ... --persona ... --scope ... --allow-send`。它会在本人点击开启后真实发送通知和自动回复，必须先阅读 [QQ 实测步骤](docs/qq-validation.md)。本开发会话未运行真实发送，也未改变用户“外部消息由本人发送”的偏好。

未可靠识别的自身回声只会暂停，不冒称“本人已接管”。自身 echo 先于 API 回执、手机人工发言、未知结果核对仍需实机验收；网页已有只读渠道核对和人工证据登记，不盲重发或自动恢复。无法核对的 unknown 不盲目重发。重启不恢复托管。

## 验证与维护

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src/chattwin
uv run chattwin doctor
uv run --project training --locked pytest -q tests/test_training_contracts.py tests/test_training_runtime.py
```

备份命令：`chattwin backup create DESTINATION`、`backup inspect BACKUP`、`backup restore BACKUP EMPTY_DESTINATION`。备份包含一致数据库和引用数据集；不含凭证、原始上传或模型权重。恢复后归档绑定、停止 AI，需重新确认。详见 [operations.md](docs/operations.md)。

已有画像确认、记忆纠正、身份重映射、来源删除传播、预算/诊断和模型作业管理。浏览器使用短期登录；私网/常驻配置见 [手机与主机](docs/access-and-hosting.md)。仍待真实 QQ/QCE 导出、Qwen CUDA 和人工质量评测、手机离网/休眠组合、7 天试运行及跨平台发布审查。锁文件清单见 [SBOM](docs/sbom.cdx.json)，它不替代逐项许可和漏洞审查。具体顺序与验收记录统一维护于 [任务状态](docs/tasks.md)。

新核心 Apache-2.0；上游组件各自保留许可。按用户后续明确指令，源码已推送 GitHub；没有创建 release，没有上传真实聊天、数据库、密钥或私人模型。
