# 应用代码版本与独立数据恢复回滚演练

状态：**真实本地演练通过，合成数据与 FakeChannel；未连接 QQ 或模型服务。** 完成于 2026-10-26 13:11:42 UTC。演练没有修改当前 checkout、当前数据库、schema 实现或真实聊天目录，没有推送代码。

## 固定输入

| 项目 | 实际使用 |
| --- | --- |
| 旧代码 | `0e3f5e96fd58d5da89435a3a2c2f8a048ce4e1a7`，migration head `0001` |
| 新代码 | `7602922ead6cf1af59a9a1dd9e70d5231559fb7b`，migration head `0002` |
| 来源 | 对两个 commit 分别执行 `git archive --format=tar`，只导出已跟踪源码，在 Git 外私有临时目录解压 |
| 运行环境 | macOS arm64；两份源码各自独立 `.venv`，CPython 3.12.14；均执行 `uv sync --locked --no-dev` |
| 数据 | 仓库内 `canonical_messages.synthetic.jsonl`，1 Persona、1 Relationship、4 条完全虚构聊天 |
| 训练集 | 旧版真实导入/构建，1 个冻结数据集：train 2、validation 0、test 0；不作为模型质量证据 |
| 发送 | 唯一使用 FakeChannel；仅旧版造数阶段确认 1 条合成开启通知，外部发送总数 0 |
| API 验证 | 两个版本各自真实 `create_app` 和完整 lifespan，使用 FastAPI TestClient 进程内 ASGI 请求；未声称浏览器、手机或远程链路验收 |

两版应用的包版本字符串均为 `0.1.0.dev1`，因此本演练用完整 Git commit 和源码归档 hash 区分版本，没有依赖相同的显示版本号。

源码及锁文件证据：

```text
old source tar SHA-256:
e2f70bf23bd60f5f13c9c3d38fb2ee5a417376fd6dfaa989136f25cc16a4a6a3
new source tar SHA-256:
6f3d92cc24931b71069cffb486ba823a6bfde0ab890ae35e0688f337038cf539
both core uv.lock SHA-256:
17aba13e0c7f7ba3687163460b6ba988cd47fa4b2125f7dbfe07981c446565bb
```

演练私有目录标识为 `chattwin-rollback-drill-go843zln`。完整执行脚本 `stages.py`、两套源码/venv、两版数据目录、预升级备份和三阶段 JSON 结果均保留于本机临时目录；本文件只记录合成数据的计数、hash 与状态，不包含认证凭证或真实聊天。

## 实际过程

1. 旧版独立进程创建 `old-data` 并运行真实迁移到 `0001`，用 `seed_demo`/DataService 导入合成消息、建立冻结数据集。通过 Coordinator + FakeChannel 确认开启通知，数据库达到 1 个 `AI_ACTIVE` 会话。随后关闭 Coordinator，明确注入两条**合成故障状态** outbox：1 planned AI 回复、1 submitting AI 回复，用于检查恢复不会重放；没有向外发送这些内容。
2. 旧版 `create_backup` 使用 SQLite backup API 创建 `pre-upgrade-backup`，`inspect_backup` 完整校验通过；备份含 5 个文件（SQLite 与该数据集的 manifest/train/validation/test），认证 token 不在备份中。旧进程退出后，才将停止的 `old-data` 复制为 `upgrade-data`；未直接复制正在写入的 SQLite 文件。
3. 新版独立进程只打开 `upgrade-data`，执行真实 `Store.migrate()`，版本 `0001 → 0002`，新增 model_deployments 表且为空。消息、用途与数据集登记的逐行内容 hash 不变。新版 API 启动后按重启策略暂停 AI、取消 planned、将 submitting 标为 unknown；健康与状态 API 均成功，未启动发送。
4. 再次使用**旧版解释器与旧版模块**，从原 `0001` 备份调用 `restore_backup`，恢复到全新的空目录 `rollback-data`。旧版程序从未打开 `upgrade-data` 执行迁移，未调用 Alembic downgrade、未修改新版数据库版本号。
5. 在恢复目录启动旧版 API；重新生成本地 owner 认证，确认与旧目录凭证不同，但不输出凭证。API 能读取原有 Persona、Relationship 和全部 4 条消息。归档 binding 的生成请求被拒绝，并显式调用 Coordinator.settle 排空队列，FakeChannel transport starts 为 0。最后再次核验原目录、原备份未变，新目录仍为 `0002`。

每阶段实际运行的模块路径分别断言为 `old-code/src/chattwin/__init__.py`、`new-code/src/chattwin/__init__.py`、`old-code/src/chattwin/__init__.py`；没有误用当前工作区或同一个已安装应用。

## 结果

| 检查 | 升级前旧版 | 新版 API 启动后 | 恢复后的旧版 API |
| --- | --- | --- | --- |
| migration revision | 0001 | 0002 | 0001 |
| 人设 / 关系 / 消息 / 用途 | 1 / 1 / 4 / 4 | 1 / 1 / 4 / 4 | 1 / 1 / 4 / 4 |
| 数据集 / binding / session / outbox | 1 / 1 / 1 / 3 | 1 / 1 / 1 / 3 | 1 / 1 / 1 / 3 |
| 会话 | AI_ACTIVE ×1 | PAUSED ×1 | PAUSED ×1 |
| 活动 binding | 1 | 1 | 0（已归档） |
| outbox | confirmed 1、planned 1、submitting 1 | confirmed 1、cancelled 1、unknown 1 | confirmed 1、cancelled 1、unknown 1 |
| SQLite integrity / 外键异常 | ok / 0 | ok / 0 | ok / 0 |
| 健康 / 本人状态 API | 未用于造数 | 200 / 200 | 200 / 200 |

恢复后的旧版额外检查：

- `/api/v1/messages`：200，返回 4 条原合成消息。
- 错误认证调用 `/api/v1/state`：401。
- 向归档 `demo-binding` 请求 `/api/v1/sandbox/messages`：404 `BINDING_NOT_FOUND`。
- 显式执行队列 drain 后，transport starts = **0**；没有自动发送“本人已接管”或任何 AI 回复。
- 恢复前没有 owner-token 文件；首次启动创建新凭证，`owner_token_restored=false`。
- 原 `old-data` 全部采集状态/计数/数据 hash 不变；备份 hash 不变；`upgrade-data` 仍为 schema `0002`。

合成内容一致性证据（升级前、升级后、恢复前后均相同）：

```text
messages rows SHA-256:
6e816df79cec6c9b500f964ca5d3178dc1244c6864b2503771c0c0fa049c793c
message_uses rows SHA-256:
63bd55086e3899487287917ebed688899ca51b43039a74f30faf0c03ebbeebd4
dataset_versions rows SHA-256:
e3de5bafd15c6faf1c78e30bec346606293e87bd56a63b0fcd13dd87a825a45c
frozen dataset hash:
52e7f6872ea004669979af96b037dc4ab940b9aff52f531b66af37935aa2f8a6
pre-upgrade backup manifest hash:
dffc3571864f29ec984f1cde202c163da9b76999876c8fede369bd2ee7e22d7b
```

行 hash 算法为按第一列排序后读取 `SELECT *`，对 `json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 的 UTF-8 求 SHA-256。数据库恢复会有意改变控制状态与追加恢复审计；这些表不应要求整个数据库文件逐字相同。

## 可重复操作骨架

在自己的 Git 外专用目录设置 `ROLLBACK_DRILL`，从项目仓库执行：

```sh
git archive --format=tar --output "$ROLLBACK_DRILL/old-source.tar" 0e3f5e96fd58d5da89435a3a2c2f8a048ce4e1a7
git archive --format=tar --output "$ROLLBACK_DRILL/new-source.tar" 7602922ead6cf1af59a9a1dd9e70d5231559fb7b
mkdir "$ROLLBACK_DRILL/old-code" "$ROLLBACK_DRILL/new-code"
tar -xf "$ROLLBACK_DRILL/old-source.tar" -C "$ROLLBACK_DRILL/old-code"
tar -xf "$ROLLBACK_DRILL/new-source.tar" -C "$ROLLBACK_DRILL/new-code"
uv sync --project "$ROLLBACK_DRILL/old-code" --locked --no-dev
uv sync --project "$ROLLBACK_DRILL/new-code" --locked --no-dev
```

之后按上述阶段，分别使用 `old-code/.venv/bin/python`、`new-code/.venv/bin/python`、`old-code/.venv/bin/python` 调用实际 `create_backup`、`Store.migrate`、`restore_backup` 与 API。清除继承的 `CHATTWIN_*` 模型/QQ配置，专用合成数据路径从命令参数传入；不打印认证值。`restore_backup` 的目标必须不存在或为空。若遇 macOS `/var`/`/tmp` 符号链接，使用其 `/private/...` 规范绝对路径。

## 证明范围与限制

本演练证明这两个**固定源码版本**可通过“旧代码 + 升级前独立备份 + 新空目录”恢复到可读、暂停且不自动重放发送的旧应用。回滚恢复点是升级前备份；升级后新增内容不会自动合并回旧格式，因此保留升级后的目录作为独立证据和后续处理来源。

没有证明任意跨版本兼容、失败迁移中途恢复、私人基础模型/adapter 权重恢复、真实 QQ 原会话行为、手机远程入口或七天试运行。FakeChannel 的 zero-start 证明本地控制器没有启动传输，不能替代真实桥与账号的外部测试。无需 GPU、账号或模型密钥的本地版本回滚项目已形成实际证据；T27 其他边界按 operations 文档继续保留。
