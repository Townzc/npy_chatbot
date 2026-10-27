# M0 环境、QQ 与训练预检

采样日期：2026-10-26（America/Los_Angeles）。本报告只包含本机软件/硬件元数据和公开上游资料；未读取聊天正文、QQ 凭证或账号 ID，未连接真实 OneBot 会话，未发消息，未下载模型权重或运行训练。

后续状态更新：2026-10-27 用户授权并扫码后，官方 QCE v6.3.2 / NapCat 4.18.28 已实际运行，选定私聊578条导入和真实OneBot只读身份/版本/在线/健康核验通过，临时WS已关闭；未发送消息。见 [最新实机证据](evidence/real-qq-export-and-probe-2026-10-27.md)。这不覆盖下文另一安装器的版本矩阵；下文保留首次采样结果，不代表当前仍在等待扫码。

## 状态与证据级别

| 任务 | 本次完成 | 状态与未验证项 |
|---|---|---|
| T02 环境 doctor 与 QQ 探针 | 硬件、运行时、QQ 安装版本、标准桥目录与常见端口检查；协议/许可核查 | 本地预检完成；真实 QQ 原会话 **BLOCKED / UNVERIFIED**。未发现可连接的标准桥安装，没有受控账号/会话配置 |
| T03 模型/训练预检 | 固定模型 revision、tokenizer revision、模板 hash、依赖候选；确认本机硬件 | 预检完成；Linux/CUDA 训练、显存 dry run、真实底座训练 **UNVERIFIED**。本机不是计划首个 Linux/CUDA 支持环境 |

协议模拟、CPU tiny smoke、真实本地训练和真实 QQ 是不同证据类别。本报告不能替代 T19、T21 或 T24 的验收。

## 本机读取结果

| 项目 | 实际结果 |
|---|---|
| 系统 | macOS 26.6.2，arm64 |
| 芯片 | Apple M5 Pro |
| 内存 | 25,769,803,776 bytes（24 GiB） |
| QQ | `/Applications/QQ.app`，7.0.2，build 53644，bundle `com.tencent.qq` |
| QQ 进程 | 检测到 QQ 与 QQ Helper 可执行文件；没有据此推断账号身份或登录状态 |
| uv | 0.12.17 |
| Python | Python 3.12.14 可用；系统 `python3` 为 3.9.6，项目须明确使用 3.12 |
| Node / npm | 本次 shell PATH 未找到；可使用 Codex bundled workspace runtime，项目安装说明需单独列 Node 开发要求 |
| NVIDIA / CUDA | `nvidia-smi` 不在 PATH；Apple Silicon 不能作为 Linux/CUDA 训练验收环境 |
| PyTorch | 系统 Python 未安装 torch；未扫描其他私人 Python 环境 |
| NapCat 标准路径 | `~/Library/Containers/com.tencent.qq/Data/Documents/napcat` 不存在；QQ.app 包中没有名称含 napcat 的文件 |
| 常见本地桥端口 | `127.0.0.1:6700`、`:3001`、`:6099` TCP connect 均返回 61（connection refused） |

目录与端口检查只说明上述位置没有可见服务，不证明整台机器没有其他路径、端口或远程桥。未读取 QQ 用户数据库和配置文件。

复查硬件与应用版本的命令：

```sh
sw_vers
uname -m
sysctl -n machdep.cpu.brand_string
sysctl -n hw.memsize
uv --version
python3.12 --version
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' /Applications/QQ.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' /Applications/QQ.app/Contents/Info.plist
```

## QQ 协议和上游许可

选择 **OneBot v11 正向 WebSocket `/`**：一条连接接收事件和请求 API。先做 `get_login_info`、`get_version_info`、`get_status` 读取探针，核对实际登录 ID 与预期 ID；探针不调用发送 API。请求 `echo` 只用于关联请求和响应，不是平台幂等键。[固定协议版本](https://github.com/botuniverse/onebot-11/blob/d4456ee706f9ada9c2dfde56a2bcfc69752600e4/communication/ws.md)

| 上游 | 本次固定的公开 revision | 结论 |
|---|---|---|
| OneBot v11 文档 | `d4456ee706f9ada9c2dfde56a2bcfc69752600e4` | 独立实现协议客户端；只承诺实测过的能力 |
| NapCatQQ | `3420f0b76d7dc0ac92cde1663f21ea27f61e13bb` | 自定义 Limited Redistribution License；包含非商业与再分发/修改限制；不随核心捆绑，也未安装 |
| NapCat Mac Installer | `d2d15e6288a23287dabfc35378fa9b4735e84b2d` | 安装器 MIT 不改变 NapCat 本体许可证；修改 QQ 入口的安装路径尚未在本机执行 |

NapCat LICENSE 原始文件 SHA-256：`2bbc0dba0c62fcde4adfe38ebadad0b7d4e23b06b88d9551904bbe07769dc46f`。其条款并非 Apache/MIT；适用使用授权仍需按用户实际用途澄清。[固定 NapCat LICENSE](https://github.com/NapNeko/NapCatQQ/blob/3420f0b76d7dc0ac92cde1663f21ea27f61e13bb/LICENSE) · [固定安装器 LICENSE](https://github.com/NapNeko/NapCat-Mac-Installer/blob/d2d15e6288a23287dabfc35378fa9b4735e84b2d/LICENSE)

NapCat 的兼容表列出私聊、私聊自身发言事件；其他客户端在线状态变更不支持。因此手机打开 QQ、亮屏不能作为自动接管证据，iPhone 人工发言上报必须实机检查。[官方事件表](https://napneko.github.io/develop/event)

安装器上游给出的已测组合为 macOS 15.7.5 / Apple Silicon / QQ 6.9.96 热更新至 7.0.2-53644 / NapCat 4.18.41。它不等于本机 macOS 26.6.2 已兼容；上游同时运行两个桌面实例的说明要求使用不同账号，也不能证明同一账号手机人工发言识别。[固定安装器说明](https://github.com/NapNeko/NapCat-Mac-Installer/blob/d2d15e6288a23287dabfc35378fa9b4735e84b2d/README.md)

真实 QQ 受控验证所需输入：

1. 用户自行配置且许可适用的桥、固定版本、正向 WS 地址，以及通过私有环境变量提供的 token。
2. 预期登录账号稳定 ID、唯一测试私聊稳定 ID；明确该会话是授权测试目标。不要把这些输入写入 Git。
3. 确认账号没有第二个自动回复进程。先运行只读身份/版本探针，再由用户在选定原私聊产生入站事件。
4. 当前用户有“外部消息只起草，由本人发送”的长期偏好。本次未执行任何发送；真实自动发送测试需要用户明确改变该偏好并指定受控目标，不能把同意文案当作发送授权。
5. 待实机记录：原会话身份一致、两条固定通知顺序、回执与自身事件、手机人工发言、断连恢复、结果 unknown 核对、接管竞态。无可靠核对能力时保持暂停，不盲重发。

## 固定模型输入

参考底座使用 **Qwen/Qwen3-4B-Instruct-2507**；模型卡声明 Apache-2.0、4.0B 参数、Qwen3 架构和非思考模式。固定为 API 本次返回的 revision，不使用浮动 `main`。[官方模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) · [模型元数据 API](https://huggingface.co/api/models/Qwen/Qwen3-4B-Instruct-2507)

| 字段 | 固定值 |
|---|---|
| base_model_id | `Qwen/Qwen3-4B-Instruct-2507` |
| base_model_revision | `cdbee75f17c01a7cc42f958dc650907174af0554` |
| tokenizer_revision | `cdbee75f17c01a7cc42f958dc650907174af0554` |
| architecture | `Qwen3ForCausalLM`；`model_type=qwen3` |
| 原始 config 精度 | `bfloat16`，不代表本机已测 bf16 训练 |
| config.json SHA-256 | `5beea1a4a34c62782bfb2f911c606741a3bab8f92d80a118fa053c28af12e8ba` |
| tokenizer_config.json SHA-256 | `a62ff0a2472a0fa1b8eaabcb57c59b58afa42a22831dc141400b6e0cf2b65ce3` |
| chat_template SHA-256 | `64f85b198065d0fba2a81f37e10ed68161ce2c19a754c7100e67e0ca2ee9c326` |
| generation_config.json SHA-256 | `835fffe355c9438e7a25be099b3fccaa98350b83451f9fd2d99512e74f1ade48` |
| 特殊 token | EOS `<\|im_end\|>`，PAD `<\|endoftext\|>` |

模板 hash 是把 `tokenizer_config.json` 的 `chat_template` 解码为字符串后按 UTF-8 编码计算 SHA-256，文件 hash 则针对下载的原始 bytes。以上仅下载公开 JSON 元数据到内存计算，未下载权重。[固定 config](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/cdbee75f17c01a7cc42f958dc650907174af0554/config.json) · [固定 tokenizer 配置](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/cdbee75f17c01a7cc42f958dc650907174af0554/tokenizer_config.json)

训练候选依赖已通过对应 PyPI 元数据确认发布存在，**尚未声明组合安装/训练兼容**。集成时以独立训练锁文件和实际 dry run 为准：Python 3.12、`torch==2.9.1`、`transformers==4.57.6`、`peft==0.18.1`、`accelerate==1.12.0`、`safetensors==0.7.0`。模型卡要求 Transformers 不早于 4.51.0。[torch](https://pypi.org/project/torch/2.9.1/) · [Transformers](https://pypi.org/project/transformers/4.57.6/) · [PEFT](https://pypi.org/project/peft/0.18.1/) · [Accelerate](https://pypi.org/project/accelerate/1.12.0/) · [Safetensors](https://pypi.org/project/safetensors/0.7.0/)

不按模型参数量推断“需要多少显存”。待选定用户自己的 Linux/CUDA 机器后，用实际 precision、LoRA rank、sequence length、batch、accumulation 做加载/前向/反向 dry run 并记录峰值显存。不得自动租卡、上传聊天或使用未指定的远程资源。

T24 所需证据仍为：冻结数据集和目标标签 mask → 实际参数更新 → 保存 adapter → **新进程**按固定 revision 加载 → 同 prompt 基座/adapter 推理 → B0–B3 对照、环境、loss、输出与隐私范围报告。CPU tiny smoke 只证明执行链，不能替代 Qwen 4B 真实训练及质量验收。
