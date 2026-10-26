# LoRA 训练与独立推理

已实现可执行的 Transformers + PEFT LoRA worker：真实反向传播、参数更新、safetensors 保存、新进程重新加载，以及带独立认证和关系范围校验的推理端点。核心安装不依赖 PyTorch。**当前实测证据是 CPU tiny 模型执行链；Qwen 4B Linux/CUDA 训练和聊天质量验收尚未通过。**

## 当前交付边界

| 能力 | 实现与证据 | 限制 |
|---|---|---|
| 独立训练环境 | `training/pyproject.toml`、`training/uv.lock`，本机真实安装 | Linux/CUDA 组合未实测 |
| 数据与配置预检 | Pydantic TrainingSpec、固定 commit/template/dataset/lock hash、scope 检查 | 数据足够不等于训练质量合格 |
| 目标标签 | 完整 template 与 generation prefix 的 token 前缀证明；历史本人、对方、system、padding 均为 `-100` | 不满足 token 前缀条件的模板拒绝；超长样本跳过并报告，不截断目标 |
| LoRA worker | AdamW、梯度累积、fp32 tiny；bf16/fp16 CUDA 分支 | 只有 tiny fp32 本机实测；不含 QLoRA、多卡、MLX |
| 取消与中断 | flag 或 SIGTERM/SIGINT；停止后记录 cancelled；训练中取消保存 adapter checkpoint；无活进程的 running 输出标 interrupted | 不实现优化器 checkpoint 恢复；必须创建新作业目录，不能原地悄悄重训 |
| 模型产物 | scope、底座、tokenizer/template、dataset、依赖、源码 hash、文件 hash、训练报告 | 默认 deployment_status=unreviewed，不自动启用或上传 |
| 新进程加载 | 成功保存后退出内存模型，由独立 Python 进程加载 base+adapter，比较 logits 与生成结果 | 对照 prompt 来自训练样本，仅检查加载和参数生效，不是保留测试集质量评测 |
| 推理服务 | Bearer token、固定 adapter、scope 校验、请求预算、单次生成锁 | 请求中断后已经开始的推理可能继续到 token 上限；生产 GPU 吞吐未测 |
| 部署切换与 B0–B3 | 产物可供端点调用 | 完整注册、切换/回滚工作流、独立质量/隐私评测及 T24 仍待验收 |

## 无模型密钥的真实 tiny smoke

在仓库根目录运行：

```sh
uv sync --project training --locked
uv run --project training --locked python -m chattwin.training.smoke
uv run --project training --locked pytest -q tests/test_training_contracts.py tests/test_training_runtime.py
```

smoke 生成随机初始化的单层 tiny Qwen3 和简单 tokenizer，使用明确虚构的英文对话在 CPU 做 LoRA。输出默认放在系统临时目录，并打印绝对路径；也可以用 `--output /绝对路径/仓库外目录` 指定位置。不会下载预训练权重。随机底座生成内容不代表 QQ/微信聊天效果。

2026-10-26 本机验证：

- Apple M5 Pro / macOS 26.6.2 / Python 3.12.14。
- torch 2.9.1、transformers 4.57.6、peft 0.18.1、accelerate 1.12.0、safetensors 0.7.0。
- 224 个可训练 LoRA 参数，8 次 optimizer steps；loss 从 3.0407379 到 2.7997925；最大参数变化 0.1608262。
- 训练 PID 79084，重新加载 PID 79089；同 prompt 基座与 adapter 最大 logit 差 0.4429532。
- 12 项训练测试通过，包括 DataService 导入合成 ChatLab → 数据集 → 真实 tiny LoRA，及推理认证/范围拒绝。
- `uv run mypy src/chattwin/training` 和针对训练模块的 Ruff 检查通过。

这证明实际更新与加载，不证明个人风格提升，也不替代 T24 的 Qwen 4B 训练或 B0–B3 对照。

## 固定 Qwen tokenizer 验证

```sh
uv run --project training --locked python -m chattwin.training.worker tokenizer-check
```

只从公开模型下载 tokenizer 文件并缓存到 Hugging Face 缓存目录，不下载权重。已验证 revision `cdbee75f17c01a7cc42f958dc650907174af0554` 和 template SHA-256 `64f85b198065d0fba2a81f37e10ed68161ce2c19a754c7100e67e0ca2ee9c326`。重复内容的虚构多轮样例得到 51 tokens，其中 43 个上下文 tokens 被屏蔽，只保留当前本人回复的 8 tokens（含结束标记）。

## 准备真正的 Qwen 训练

先在应用中完成身份与关系确认，明确标记本人 human 来源，构建冻结数据集。其目录包含 `manifest.json` 和 train/validation/test JSONL。worker 仅从 train 文件训练，校验三个文件的 hash，不重新打乱 split。

在用户自行选择的 Linux/CUDA 主机复制源码和该私有数据集后，安装独立训练环境。训练数据和产物必须在 Git 工作区外；不需要 QQ token、管理页 token 或模型 API key。

```sh
uv sync --project training --locked
uv run --project training --locked python -m chattwin.training.worker prepare \
  --dataset /private/chattwin/datasets/DATASET_ID \
  --output /private/chattwin/training/JOB_ID \
  --spec /private/chattwin/training-spec.json
```

`prepare` 从数据集取版本、hash 和 scope，写出固定 Qwen 底座的 TrainingSpec；它只确认数据契约，返回 `hardware=UNVERIFIED`。查看并调整结构化 JSON 中的序列长度、batch、累积、rank、精度、学习率、epochs/max_steps，保留固定版本。CPU 仅允许 `synthetic_smoke=true` 的本地 tiny 路径；生产候选要求 CUDA，不自动回退到 CPU。

```sh
uv run --project training --locked python -m chattwin.training.worker train \
  --spec /private/chattwin/training-spec.json
```

输出包括：

```text
JOB_ID/
  training_spec.json
  status.json
  adapter/adapter_model.safetensors
  adapter/adapter_config.json
  tokenizer/
  manifest.json
  training_report.json
  reload_comparison.json
```

`status.json` 有状态、step、心跳、进程 ID、loss 或错误摘要。成功必须观察到非零有限参数更新、保存完整产物、新进程加载和非零 logits 差。取消通过创建 spec 中 `cancel_path` 文件或向该 worker 发 SIGTERM/SIGINT；前者在模型加载期间需等加载返回才检查。训练中断不会自动重启第二个 worker。

同一输出目录由文件锁保护。已存在作业拒绝覆盖；如果发现遗留 running/validating 状态且获得锁，将状态记为 interrupted，要求新的输出目录。取消 checkpoint 仅保存 adapter，尚不支持精确恢复优化器和随机状态。

正式训练前应在目标硬件做小步数 dry run，记录 precision、sequence length、batch、accumulation、显卡驱动与 CUDA，以及报告中的峰值分配显存。当前没有显存容量保证。CUDA 或 bf16 不可用、dataset/template/lock hash 不匹配时失败，不伪装为成功。

两张 4090 的准备步骤见 [gpu-4090.md](gpu-4090.md)：新增单卡 2 步预设、可选非重入梯度检查点、每卡显存预检、分配/保留峰值报告以及纯虚构数据准备脚本。当前仍不实现多卡训练；两张卡可以分别用于训练和独立推理。`uv run chattwin train doctor` 不下载模型。CLI 与管理作业都尊重 `CHATTWIN_TRAINING_PYTHON` 和 `CUDA_VISIBLE_DEVICES`。

## 私有 adapter 推理端点

仅加载 status 为 succeeded、manifest 文件 hash 完整且 scope 匹配的产物。由用户给模型服务单独配置至少 32 字符随机 token，不与 QQ 或控制页凭证共用。环境变量名为 `CHATTWIN_MODEL_TOKEN`；不把值提交到 Git 或写入命令历史示例。

```sh
uv run --project training --locked python -m chattwin.training.serve \
  --artifact /private/chattwin/training/JOB_ID \
  --port 8766
```

默认只监听 `127.0.0.1`。`GET /health` 与 `POST /v1/chat/completions` 均需 `Authorization: Bearer …`。生成请求示例（ID 替换为产物的实际 scope）：

```json
{
  "model": "chattwin-adapter",
  "messages": [{"role": "user", "content": "这是一条网页试聊消息"}],
  "max_tokens": 128,
  "metadata": {"persona_id": "PERSONA_ID", "relationship_id": "RELATIONSHIP_ID"},
  "stream": false,
  "temperature": 0
}
```

认证失败返回 401，其他关系返回 403，其他部署名称返回 400，超 token 预算返回 413，并发生成返回 429。该进程不连接 QQ，也不持有发送器；HTTPProvider 只获得文本候选。训练 child 使用环境变量白名单，避免继承渠道、管理页和供应商密钥；默认禁用 Hugging Face 遥测和隐式 token。

删除训练源不会令 adapter 自动遗忘；停用相应产物并重新训练前，不能把数据删除描述成模型遗忘。所有产物保持私人文件，本项目不自动上传权重、训练包或评测输出。

## 剩余验收

T21/T22 的 executable worker 与 tiny 证明已具备，但 Linux/CUDA 生产路径仍 UNVERIFIED。T24 需要真实 Qwen 4B 固定底座训练、独立新进程加载、保留测试集及人工场景的 B0–B3 对照、跨关系泄漏评测、网页模型切换/回滚证据。当前 tiny 输出没有质量结论，不应标为完整 v0.3。

上游基础接口：[PEFT 保存/加载](https://github.com/huggingface/peft/blob/v0.18.1/src/peft/peft_model.py) · [固定 Qwen 模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/cdbee75f17c01a7cc42f958dc650907174af0554/README.md)。实现独立编写，未复制上游代码。

### 已安装 wheel 的冻结资源

训练 spec、worker 与 tiny smoke 通过 `chattwin.runtime_paths.training_lock_path()` 找到发行版自带的 `training/uv.lock`；源码 checkout、pip 安装 wheel、下载的精简训练包都使用相同规则。wheel 内含许可证、主项目与训练项目配置/锁文件，不含模型权重、聊天或凭证。管理应用的独立训练解释器可以通过 `CHATTWIN_TRAINING_PYTHON` 指定绝对路径；该环境需安装完整相同版本 ChatTwin 和锁定训练依赖，详见 `docs/jobs.md`。

2026-10-26 在仓库外新环境安装实际构建 wheel 后，API 下载的精简包重新同步锁文件并执行真实 tiny smoke：8 个 optimizer steps、224 trainable parameters、最大参数更新 0.1608261764；训练 PID 88378、新进程加载 PID 88483、最大 logits 差 0.4429531693。该产物仍为 `tiny_cpu_smoke`，不计入正式 Qwen T24 验收。

### 训练源码指纹与旧 spec

`TrainingSpec.code_version` 现在必须为 `source:<64位SHA-256>`。`prepare_spec` 和 `create_smoke_spec` 自动计算实际训练包全部 `.py` 模块，加上 `runtime_paths.py` 资源解析器的文件哈希；再对“包内相对路径 → 文件 SHA-256”的排序规范 JSON 求 SHA-256。结果与绝对安装位置、Git 是否存在无关，包含 helper 的变化，排除不参与独立训练包的 jobs/UI 等应用代码。Git commit 不能替代这个检查，因为工作区可能尚未提交。

worker 在读取数据或加载模型前核对源码，保存 manifest 前再次核对，新进程比较时也核对；源码发生漂移即失败，不产生可注册的成功训练证据。`ModelManifest.code_version`、`training_code_hash` 与 spec 必须相互一致。导出训练包在压缩之前对复制后的源码重新计算指纹，并写入 `bundle-manifest.json.training_code_version`；复制时发生漂移会拒绝导出。

旧 `code_version: working-tree`、缺少 code_version 或其他无内容 pin 的 spec 不再可执行，也不会自动补写当前版本伪造旧证据。请使用当前代码重新 `prepare` 后创建新的训练作业；旧无 pin 的产物需重新训练、验证、注册才能满足这版可复现要求。原始文件不会被此升级删除。已有合法 `source:` pin 的历史产物仍记录训练时的源码身份；重新执行训练/compare 必须使用匹配的训练源码。

针对性验证：核心训练契约/作业/资源测试 16 项通过；隔离训练环境的契约与真实训练运行时测试 13 项通过。新增回归证明源码漂移在读数据/加载模型前失败、旧 working-tree 被明确拒绝、源码和解压训练包指纹一致、改动导出的 helper 会改变指纹。
