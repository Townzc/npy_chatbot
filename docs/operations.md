# 本地备份、恢复与回滚边界

当前实现可以创建一致的 SQLite 快照，附带快照引用的冻结数据集，并恢复到新的私有数据目录。恢复后所有绑定归档、会话暂停，旧队列不会自动发送。它是 **T27 的部分交付**：尚不包括私人模型权重备份、跨 schema 升降级或完整发行版回滚。

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

`inspect_backup` 校验清单 hash、每个文件 hash/size、允许的相对路径、无未声明文件、SQLite integrity/foreign keys、固定 migration `0001`、表名/列名、记录数及数据集 manifest。拒绝路径穿越、数据库 trigger/view、未知 schema 和缺失引用。SHA-256 用于发现损坏，清单没有数字签名，不能作为来源认证。

恢复发布前，在新快照内部执行以下更改：

- 所有 Binding 归档；所有 mode session 设为 PAUSED，并增加 control_epoch。
- planned/claimed outbox 取消；submitting 改为 unknown；已确认与已有 unknown 记录保留。
- queued/validating/running jobs 改为 interrupted，不自动重启工作进程。
- session 的模型部署回到 mock-v1；模型登记标为 unavailable/restore_requires_verification。
- 写入恢复审计记录，明确未恢复认证 token 和模型权重。

已向真实平台提交的消息不会因数据库恢复而撤回，unknown 仍需要核对。恢复不会自动发送“本人已接管”，也不会重新放行 AI。

首次启动恢复目录时重新生成 owner token，然后查看导入数据、范围和待核对发送。真实账号需要重新核验、重新创建绑定，并明确开启；私人模型需单独恢复权重、验证 manifest 和范围后重新登记。原运行目录和原备份保持不变，便于人工比较。

## 验证证据

2026-10-26，`uv run pytest -q tests/test_ops.py`：**7 passed**。覆盖真实 WAL 数据快照与数据集恢复、快照后数据变更不污染备份、owner token/uploads 排除、活动状态恢复暂停、未提交取消/已提交未知、校验损坏、路径穿越、符号链接、maintenance lock、非空目录拒绝、未知 schema 拒绝、模型 manifest 与二进制排除。

`uv run ruff check src/chattwin/ops tests/test_ops.py` 和 `uv run mypy src/chattwin/ops` 通过。测试使用虚构 ChatLab 数据和 FakeChannel 控制状态；没有连接或发送真实 QQ 消息。

## 尚未验收

只支持本项目 migration `0001` 的同 schema 恢复。较新数据库由旧代码恢复时拒绝，不执行破坏性 downgrade。完整代码发行版回滚、迁移故障演练、实际私人 adapter/base 权重备份与恢复、手机离网控制、新机器安装和至少 7 天真实试运行仍需后续验证。该功能不应被宣称为完整 T27 或 v1.0 完成。

实现依据：[Python SQLite backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)。
