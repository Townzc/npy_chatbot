# AutoDL 与 QQ 官方备份澄清 — 2026-10-26

本批推进 T02/T03/T09 的外部接入准备。用户确认 GPU 将租用 AutoDL，而非已有可连接双卡；已有文件来自 QQ 官方“备份聊天记录到电脑”。当前不把这两项来源澄清记为 GPU 或真实数据验收成功。

## 交付

- [AutoDL 步骤](../autodl.md)：单张 4090、单卡主存额度、数据盘缓存/venv、驱动/runtime 区别、固定依赖、纯虚构 Qwen 训练与关机留存。
- `scripts/check_gpu_host.py`：安装依赖前只读容量检查，无第三方依赖。报告物理 GPU 显存/驱动、磁盘余量、物理主存和可见容器限额；不下载、训练或读取聊天/凭证。
- [QQ 步骤](../qq-setup-research.md)：按电脑可见、仅手机可见、只剩备份三种情况处理；QCE 单 JSON 导出与官方备份容器分开，未声称存在已验证的直接转换方案。
- README、任务状态和前批准备记录同步更正。

## 验证

`uv run pytest -q tests/test_gpu_host_check.py`：3 passed。覆盖 cgroup v2 子级/父级最小额度、v1 无限哨兵、缺失内存信息、GPU 单位/坏值、NVIDIA 和路径查询失败。此处 NVIDIA CSV 是解析契约数据，不是真机结果。

实际在本机运行 `uv run python scripts/check_gpu_host.py --storage /private/tmp`：Darwin/arm64，无 NVIDIA 查询，退出码 2；明确返回 `REFERENCE_HOST_REQUIRES_LINUX_X86_64`、`NVIDIA_QUERY_FAILED`，`training_verified=false`、`cuda_runtime_verified=false`、`model_downloaded=false`。没有伪造 Linux 或 GPU 成功。

Ruff check / format 通过；本批未改训练 worker、API 或前端，未重复运行无关训练和网页测试。前批核心 137 passed / 1 skipped 与独立训练 16 passed 的证据仍分别保留。

## 限制与下一批

主存/磁盘建议是规划余量，不是已测最低要求。容器可隐藏上级 cgroup，脚本不能代替租用控制台额度；安装环境可用也不能证明 Qwen 24GB 能完成反向传播。AutoDL 实际安装、驱动兼容、显存峰值、训练耗时和费用仍未验证。

等待 SSH 后执行 Qwen 小步训练、参数变化和新进程重载，再验证认证推理；等待电脑历史可见范围与 QCE 导出后完成本地真实格式核对。QQ 桥/手机实测、足量数据与 B0–B3 人工质量、7 天试运行仍按原门槛执行。没有租机、充值、上传真实聊天、修改账号或发送私聊。
