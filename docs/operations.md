# 本地备份、恢复与回滚边界

当前实现可以创建一致的 SQLite 快照，附带快照引用的冻结数据集，并恢复到新的私有数据目录。支持 schema `0001` 与 `0002`；旧 `0001` 备份恢复后可由正常迁移升级到 `0002`，已有回归验证。恢复后所有绑定归档、会话暂停、模型部署撤销，旧队列不会自动发送。已完成两个固定源码版本之间的真实本地回滚演练，采用旧代码和升级前备份恢复到空目录。它仍是 **T27 的部分交付**：尚不包括私人模型权重备份、任意跨版本兼容或数据库强制降级。

## 实际包含内容

| 内容 | 处理方式 |
|---|---|
| SQLite | 使用 Python `sqlite3.Connection.backup` 取得一致快照，包含已提交的 WAL 数据；不是直接复制正在写入的 `.sqlite3` 文件 |
| 历史消息 | 规范正文、来源定位、用途、身份映射等数据库内容完整保留 |
| 个性化数据 | 数据库中的画像、记忆、关系和版本保留 |
| 数据集 | 只复制数据库快照引用的 `datasets/{id}/manifest.json`、train/validation/test JSONL；验证数据库 manifest、文件 manifest、内容 hash 一致 |
| 模型登记 | 保留数据库中的登记元数据；登记 payload 的 `artifact_path` 或 `path` 位于私有根目录内时，附带其 `manifest.json` 到 `model_manifests/{id}/` |
| 运行记录 | 数据库中的 outbox、控制版本、通知记录、jobs、审计与用量保留 |
| 备份清单 | `backup-manifest.json` 记录 schema、文件 SHA-256/size、表记录数、排除项及模型文件缺失情况 |

以下内容**不包含**：`owner-token`、环境变量密钥、QQ 登录会话、桥配置、原始导出文件、临时 uploads、锁文件、未登记文件、未引用数据集、基础模型权重、adapter 二进制、优化器 checkpoint 和外部训练目录。原始文件的来源路径可能仍作为出处保存在数据库中，但不能据此认为原始文件已备份。

备份含私人聊天、记忆和训练数据，是未加密的本地目录；它必须位于 Git 工作区外。本功能不上传或公开备份。模型 manifest 的存在不等于权重存在，恢复报告始终明确 `model_weights_restored=false`。

来源删除或身份重映射已撤销的数据集不再复制正文，即使撤销记录仍在数据库而磁盘目录已删除。备份清单明确记录 `revoked_datasets`，恢复保留 revoked 状态，不复活文件。已撤销模型也只保留数据库元数据。备份与数据删除共用 `data-management.lock`，避免数据库快照与文件 quarantine 交错。

## 管理页 API 与脱敏诊断

所有操作使用本人认证。创建和打包在后台线程执行，不占用接管事件循环；恢复仍只通过离线 CLI/函数调用，不能在线覆盖正在运行的数据目录。

| API | 返回 |
|---|---|
| GET `/api/v1/diagnostics` | schema/app 版本、操作系统类别、表计数、会话/outbox/job/deployment 状态计数、数据库大小、备份数量、外键检查；不含聊天、账号 ID、路径或密钥 |
| GET `/api/v1/backups` | `[{id, created_at, bytes}]`；清单校验失败会明确报错 |
| POST `/api/v1/backups`，正文 `{}` | 201 `{id, report}`；report 包含 schema、计数、文件数、大小、排除项和已撤销数据集省略数 |
| GET `/api/v1/backups/{id}/download` | 重新校验完整备份后返回私人 ZIP 下载；临时 ZIP 下载后删除 |

管理页的备份存于 live data 目录之外、与其同级的 `<DATA_DIR名称>.backups`。ID 必须是规范 UUID，API 不接受任意文件路径；拒绝符号链接和路径穿越。下载 ZIP 是完整私人备份，区别于仅含汇总计数的 diagnostics。诊断只对固定状态枚举计数，异常状态文本归并为 `other`，不会把任意数据库文本带进诊断报告。

## 调用方式

可通过以下 Python 应用接口调用，均不需要 QQ 或模型密钥：

```python
from pathlib import Path
from chattwin.storage import Store
from chattwin.ops import create_backup, inspect_backup, restore_backup

store = Store(Path("/private/chattwin/data"))
report = create_backup(store, Path("/private/chattwin/backups/snapshot-001"))
store.close()

verified = inspect_backup(Path("/private/chattwin/backups/snapshot-001"))
restored = restore_backup(
    Path("/private/chattwin/backups/snapshot-001"),
    Path("/private/chattwin/restored-data"),
)
```

备份目标必须不存在，不能在 live data 目录或 Git checkout 之内。恢复目标必须不存在或为空；已有数据库、sender lock、文件或正在运行实例的目录一律拒绝覆盖。两个恢复操作使用目标目录旁的独占 maintenance lock 防止竞争。复制到私有临时目录并校验后才原子发布；失败会清理未发布的暂存目录。

输入路径及其父目录、数据集路径和备份内容都拒绝符号链接。macOS `/tmp`、`/var` 等系统别名也可能触发这一检查；使用其实际绝对路径，例如 `/private/tmp`。复制每一级目录与最终文件时使用 `O_NOFOLLOW`，只接受普通文件，不遍历符号链接。

## 校验与恢复后的控制状态

`inspect_backup` 校验清单 hash、每个文件 hash/size、允许的相对路径、无未声明文件、SQLite integrity/foreign keys、实际 migration revision、表名/列名、记录数及数据集 manifest。`0001` 使用 frozen schema_v1 校验，`0002` 在其基础上校验 model_deployments 表；实际版本必须与备份清单一致。拒绝路径穿越、数据库 trigger/view、未知 schema 和有效数据集缺失引用。SHA-256 用于发现损坏，清单没有数字签名，不能作为来源认证。

恢复发布前，在新快照内部执行以下更改：

- 所有 Binding 归档；所有 mode session 设为 PAUSED，并增加 control_epoch。
- planned/claimed outbox 取消；submitting 改为 unknown；已确认与已有 unknown 记录保留。
- queued/validating/running jobs 改为 interrupted，不自动重启工作进程。
- session 的模型部署回到 mock-v1；模型登记标为 unavailable/restore_requires_verification。
- schema `0002` 的所有 model_deployments 撤销，数据库列与 payload 同步为 revoked，不能通过旧端点自动恢复服务。
- 写入恢复审计记录，明确未恢复认证 token 和模型权重。

已向真实平台提交的消息不会因数据库恢复而撤回，unknown 仍需要核对。恢复不会自动发送“本人已接管”，也不会重新放行 AI。

首次启动恢复目录时重新生成 owner token，然后查看导入数据、范围和待核对发送。真实账号需要重新核验、重新创建绑定，并明确开启；私人模型需单独恢复权重、验证 manifest 和范围后重新登记。原运行目录和原备份保持不变，便于人工比较。

## 验证证据

2026-10-26，`uv run pytest -q tests/test_ops.py`：**12 passed**。覆盖真实 WAL 数据快照与数据集恢复、快照后数据变更不污染备份、owner token/uploads 排除、活动状态恢复暂停、未提交取消/已提交未知、校验损坏、路径穿越、符号链接、maintenance lock、非空目录拒绝、未知 schema 拒绝、模型 manifest 与二进制排除；新增 `0002` 部署撤销、旧 `0001` 恢复再升级、revoked 数据集不复活、诊断脱敏和受认证下载。

`uv run ruff check src/chattwin/ops tests/test_ops.py` 和 `uv run mypy src/chattwin/ops` 通过。测试使用虚构 ChatLab 数据和 FakeChannel 控制状态；没有连接或发送真实 QQ 消息。

## 按代码版本与独立备份回滚

2026-10-26 已实测 `0e3f5e9`（schema 0001）→ `7602922`（schema 0002）→ 使用 `0e3f5e9` 从升级前备份恢复到另一个空目录。两版均由 `git archive` 导出到私有临时位置并各自 `uv sync --locked --no-dev`，当前工作区未切换。恢复后旧 API 可读取 4 条原合成消息；所有会话 PAUSED、binding 归档，显式排空队列也未启动发送。完整 commit、归档与数据 hash、接口状态、限制见 [应用回滚演练证据](evidence/application-rollback-2026-10-26.md)。

实际操作顺序：

1. 在升级前记录代码完整 commit，停止写入进程，用对应版本创建并 `inspect_backup` 校验备份；另行保管未包含的模型权重与配置。
2. 保留旧代码及其锁文件，升级在独立数据副本上验证。只有全部进程停止后才能直接复制工作目录；活动数据库使用 SQLite backup API。
3. 需要回滚时，停止新版应用；用旧代码的独立解释器，从**升级前旧 schema 备份**恢复到新的空目录。不要让旧应用打开新版数据库，不改 alembic_version，也不强制 downgrade。
4. 以恢复目录启动旧应用，重新生成本人认证，核对消息、用途、数据集哈希和控制状态。确认所有会话暂停、绑定归档，planned 已取消、submitting 仍需按 unknown 核对，再决定下一步。
5. 保留原数据、升级后数据和原备份。升级后新增内容不会自动合并回旧 schema；真实渠道与模型需要重新验证和明确启用。

上述演练仅使用合成数据与 FakeChannel，没有账号、GPU、真实发送或生产数据恢复。

## 尚未验收

目前只识别本项目 migration `0001` / `0002`。较新未知数据库拒绝恢复，不执行破坏性 downgrade。其他代码版本组合、中途迁移故障演练、实际私人 adapter/base 权重备份与恢复、手机离网控制、新机器安装和至少 7 天真实试运行仍需后续验证。该功能不应被宣称为完整 T27 或 v1.0 完成。

实现依据：[Python SQLite backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)。
