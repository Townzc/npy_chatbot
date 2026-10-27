# AutoDL：单张 4090 的首次 Qwen 验收

2026-10-26：用户澄清 GPU 需要在 AutoDL 租用，目前没有已连接的服务器。首轮申请 **1 张标准 RTX 4090 24GB**，验证包内虚构数据的 Qwen 4B 真 LoRA；不先租两张。当前 worker 单卡执行，24GB 是否足够由实际峰值决定，尚未完成 AutoDL 实测。

## 租用配置

| 项目 | 首轮选择 |
|---|---|
| 计费 | 按量计费，先做小步验收；价格以选择主机时的控制台为准 |
| GPU | 1 × RTX 4090 24GB |
| CPU / 主存 | 建议至少 8 核，可先选单卡分配 32GB 主存做小步试跑，64GB 留更多余量；不是 GPU 显存 |
| 磁盘 | 数据盘至少 60GiB **可用**；可选 100GB 容量留余量 |
| 系统 | Linux x86_64，优先 Ubuntu 22.04/24.04 官方基础 PyTorch 镜像 |
| 驱动 | 优先平台标示可支持 CUDA 12.8 或更高的主机；安装后核对 `nvidia-smi` |
| Python / 框架 | 用项目独立环境安装 Python 3.12、torch 2.9.1 等锁定依赖；镜像自带版本无需恰好一致 |

2026-10-27 澄清：**无需 A800；24GB 是 GPU 显存，32/64GB 是主机 RAM**。32GB 可以作为首轮小步试跑的选项，64GB 是较宽松的余量建议；两者都没有在本项目实机测出最低要求。若内存不足，保留失败证据后再决定调整。AutoDL 的 CPU/内存按每张 GPU 分配，因此要看单卡实际分配额度，不默认加租第二张。[资源分配与目录](https://www.autodl.com/docs/env/)

当前 Linux x86_64 训练锁含 CUDA runtime 12.8.90。优先选 NVIDIA 570.124.06 或更新驱动，这是 CUDA 12.8 Update 1 对应版本；较老驱动可能存在有限的 minor compatibility，但本项目未验收，不能仅凭 CUDA 12.x 字样判定通过。`nvidia-smi` 顶部 CUDA Version 表示驱动能力，`train doctor` 的 `cuda_runtime` 才是该 PyTorch 环境实际运行库版本。无需在实例中另装主机驱动。[NVIDIA 12.8.1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-toolkit-release-notes/index.html) · [AutoDL CUDA 说明](https://www.autodl.com/docs/cuda/)

## 连接和源码

提供 SSH 别名或主机/用户名/端口即可，密码与私钥只配置在本机。先由本人用控制台的 SSH 指令完成登录或公钥配置，再供实施会话连接。[AutoDL SSH](https://www.autodl.com/docs/ssh/)

服务器只需要已经提交的源码和随包虚构样例。可以克隆已授权可访问的 GitHub 仓库；私有仓库也可在 Mac 用 `git archive HEAD` 打包源码后通过 SSH 上传，避免给云主机配置 GitHub 私钥。不要用整个本机工作目录同步，因为其中有被 Git 忽略的 `chat_record`。源码版本/hash 和锁文件须保留，训练过程中不改源码。

## 数据盘环境

AutoDL 默认系统盘约 30GB，数据盘路径为 `/root/autodl-tmp`。代码和两个 `.venv` 放在数据盘的 `npy_chatbot` 目录；缓存及运行产物放在同盘独立目录。核心与训练均直接运行 Python，不需要 Docker。[目录说明](https://www.autodl.com/docs/env/)

以下在服务器执行，假设源码已位于 `/root/autodl-tmp/npy_chatbot`：

```sh
cd /root/autodl-tmp/npy_chatbot
python3 scripts/check_gpu_host.py --storage /root/autodl-tmp
```

此脚本只有标准库依赖，不安装包、不下载模型、不启动训练、不输出环境变量或设备 UUID。读取磁盘余量、Linux 内存和可见 cgroup v1/v2 限额、NVIDIA 物理卡容量/空闲量/驱动。可见父级限额取最小值，但容器外隐藏限额仍以租用控制台为准；不能用宿主机 `MemTotal` 冒充容器额度。退出码 2 表示平台、存储或 NVIDIA 查询失败；退出 0 也不表示模型能装入显存。

检查通过后准备目录与依赖：

```sh
umask 077
mkdir -p /root/autodl-tmp/chattwin-cache /root/autodl-tmp/chattwin-private /root/autodl-tmp/chattwin-tmp
export XDG_CACHE_HOME=/root/autodl-tmp/chattwin-cache
export UV_CACHE_DIR=/root/autodl-tmp/chattwin-cache/uv
export UV_PYTHON_INSTALL_DIR=/root/autodl-tmp/chattwin-cache/python
export HF_HOME=/root/autodl-tmp/chattwin-cache/huggingface
export TMPDIR=/root/autodl-tmp/chattwin-tmp
export PATH="$HOME/.local/bin:$PATH"
python3 -m pip install --user 'uv==0.12.17'
uv python install 3.12
uv sync --locked --no-dev
uv sync --project training --locked --no-dev
CUDA_VISIBLE_DEVICES=0 uv run --no-sync chattwin train doctor
```

缓存变量来自 [uv 配置](https://docs.astral.sh/uv/reference/environment/)。这不改镜像的 PyTorch；虚拟环境沿用仓库与 `training` 的各自路径。记录实际 Python/uv/框架版本。重新开 SSH 会话要重新设置这些变量，推理和新进程重载也要使用同一 `HF_HOME`。

不要在 CUDA 不可用、BF16 不支持、依赖不符或网络下载失败时继续声称验收通过。公开模型下载失败先记录具体网络问题；不改为随机 tiny 底座，不关闭 TLS 校验，不上传凭证。选定 GPU 的 PyTorch 可用性由 doctor 检查，首个 forward/backward 仍是下一步真实验证。

## 真实小步训练与产物

```sh
uv run --no-sync python scripts/prepare_gpu_smoke.py --root /root/autodl-tmp/chattwin-private/qwen-4090-001
CUDA_VISIBLE_DEVICES=0 uv run --no-sync chattwin train run /root/autodl-tmp/chattwin-private/qwen-4090-001/spec.json
```

该目录必须是新的；失败后也保留证据，下一次用 `002` 等新目录。规格为固定 Qwen revision、BF16、序列 512、batch 1、LoRA rank 8、梯度检查点、最多 2 steps。小数据执行成功不代表质量通过；成功条件见 [gpu-4090.md](gpu-4090.md)。

训练结果保存在 `qwen-4090-001/job`：检查实际 optimizer steps、非零权重变化、adapter 摘要、新进程重载 PID 和 logits 差，以及 CUDA 峰值。与此同时采集 `nvidia-smi` 以覆盖模型重载和驱动占用。然后验证同一卡上的认证模型服务；无需为短期验证常驻第二张卡。

下载需要保留的运行报告与产物到本机私有目录，再在 AutoDL 控制台关机。按量计费关机结束算力计费；包年包月在租期内持续计时。不要把关闭浏览器或退出 SSH 当成关机。按官方当前规则，连续关机 15 天会释放实例，因此不能只靠云端保存唯一副本。[计费规则](https://www.autodl.com/docs/price/) · [数据保留](https://www.autodl.com/docs/instance_data/)

当前状态：本地只读检查与解析测试通过；AutoDL 安装、CUDA 训练、实际显存、耗时和费用均 **UNVERIFIED**。等待 SSH 后执行，不自动充值、租机、扩容或开通其他服务。
