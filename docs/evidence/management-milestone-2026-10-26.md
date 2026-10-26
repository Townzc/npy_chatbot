# 第二批里程碑：管理与真实训练执行链

本轮继续T01–T30依赖中的可本地交付部分。源码仓库已接入GitHub；真实输入`chat_record/`、数据库、凭证、模型和训练集均在Git外。没有调用真实QQ发送、租GPU、上传私人数据或创建release。

## 已实现

- 画像草稿与本人批准的不可变版本、记忆纠正/有效期/出处、身份检查及显式重映射。
- CSV会话类型默认unknown；显式private才训练。规范JSONL sidecar验证hash、数量、schema和范围。
- 来源删除影响确认、数据集/产物/部署/评测副本撤销、隔离目录删除及失败回滚；已存在权重不冒称遗忘。
- SQLite持久训练队列、worker隔离、心跳/取消/中断、无自动恢复、环境预检、训练包下载。
- 模型产物注册、端点身份验证、部署切换与回滚；同一认证推理服务可真正使用base或LoRA。
- 已确认多轮上下文、显式批准风格、关系记忆、月调用/token预算与费用估算，未知消耗保留预留。
- unknown渠道只读核对和本人证据登记；矛盾回执重新unknown、保持停止、不盲重发。
- 短期网页登录、严格手机会话配置、本人接管不受登录失败节流；诊断、备份下载、0001/0002恢复。
- 正式HTTP B0–B3工具、冻结来源/cutoff、同pin校验、blind/score人工评测；12个明确虚构工具案例。
- 源码/wheel/导出包统一训练源码指纹与依赖锁；launchd配置生成器；225组件锁文件SBOM。

## 验证结果

2026-10-26当前源码检查：

| 命令/检查 | 实际结果 |
|---|---|
| `uv run pytest -q` | 124 passed、1 skipped；核心环境无可选torch，训练runtime单独验证 |
| training环境training_contracts/runtime | 13 passed；真实参数更新、新进程重载、base与adapter认证推理、scope拒绝、源码漂移拒绝 |
| `ruff check` / `ruff format --check` | 通过，78文件格式一致 |
| `mypy src/chattwin` | 59源码文件通过 |
| 两套`uv lock --check` | 通过，核心42/训练76解析包 |
| `sh scripts/build_web.sh` | OpenAPI/TS严格检查/Vite通过，42模块，JS279.53kB/gzip86.65kB |
| 新wheel隔离安装 | 代码确来自site-packages，demo→冻结数据集→API训练ZIP下载成功 |
| 导出包独立环境 | 20文件hash验证；独立`uv sync --project training --locked`及真实tiny训练成功 |
| launchd定义 | 实际生成并通过`plutil -lint`；未安装到用户登录服务 |

独立包tiny执行记录：8次optimizer step，最大参数变化0.160826，训练PID88378与加载PID88483不同。源码pin随后加入并再次用独立训练13测试核对；最终源码/wheel训练指纹一致。上述数值只证明执行，不是个人模型质量。

测试仍有一条Starlette/httpx TestClient弃用警告；未掩盖为无警告。工程HTTP故障使用真实loopback请求，发现并修复了空`Authorization: Bearer `在实际网络中无效的问题。

## 独立审查修复

重点修复：数据更新时新建binding绕过屏障；删除后派生画像/记忆/训练任务重新写回；导入与本人重映射抢先提交；发HTTP前已准备的上下文被删除；回执与人工核对矛盾；CSV默认私聊；wheel资源路径依赖源码目录。

来源HTTP租约的竞态测试实际挂起模型请求：删除等待租约，本人接管仍在1秒内完成；之后源撤销，旧候选不向渠道发送。网络已发送的数据不能撤回，文档保持这一边界。

## 浏览器证据与限制

详见[浏览器管理验收](web-management-2026-10-26.md)。登录/导入/类型隔离/记忆/风格/试聊/接管/预算/备份/删除/unknown核对均走实际API和SQLite。真实worker任务正确失败于`CUDA_UNAVAILABLE`，没有下载模型或声称训练成功。所有四个测试binding最终HUMAN。

剩余：QCE真实样本、正式Qwen CUDA/足量确认数据/100完整人工场景、QQ原私聊/手机离网/休眠组合、≥7天运行、应用发行版恢复与依赖审查。详见[任务状态](../tasks.md)和[交付审查](../release-readiness.md)。

GPU候选：Runpod官方页面于2026-10-26列A40 48GB约$0.59/小时；4小时算力约$2.36，另计存储，实际报价可能变动。已建议首轮预算上限$10、仅用虚构数据，等待用户提供或自行租用环境。没有自动采购或上传。[官方价格](https://www.runpod.io/pricing)
