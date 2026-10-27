# 数据线实现与验证（2026-10-26）

代码：`src/chattwin/importers/`、`datasets/`、`personalization/`、`memory/`。

数据服务从 `chattwin.importers import DataService`，构造参数 `Store`。服务不依赖 ChannelAdapter，原始消息 sender/source/origin 与 Persona 用途映射分离。

## 已有本地能力

- QCE 单文件 JSON：按 v6.3.2 固定公开源码定义独立解析导出核心 0.1.0 schema；合成验证及固定环境的真实 578 条导出→身份→导入→网页数据集通过。见 [固定来源与兼容边界](qce-compatibility.md)。
- ChatLab **v0.0.2** JSON/JSONL：秒级时间、null、未知类型占位、引用、逐行错误、稳定 ID。依据 [上游格式文档](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/standard/chatlab-format.md)，独立实现；随包虚构 fixture 通过，不代表特定真实导出软件兼容已验证。
- UTF-8/BOM CSV：列映射、ISO/秒/毫秒时间、显式时区；DST 歧义拒绝。保留同秒同文连发，缺 ID 仅做同文件行号幂等。
- Canonical JSONL v1 导入和带 manifest 导出；拒绝错误主版本；忽略输入文件自带的本人/训练权限，需重新确认。
- 预览最多 20 条；报告总数、类型、日期、错误、缺引用、稳定 ID 覆盖率、去重等。文件最大 64 MiB；JSONL 单行最大 1 MiB。CSV/JSONL 按行解析，JSON 文档整体加载。写入在单一事务中发布，错误回滚，不留下可用半批次。
- 原始 sender_id/来源账号稳定；关系与 Persona 先校验再查询。导出者不自动等于训练目标；同名不合并。每个 Persona 明确选择 owner sender；`confirm_human` 仅给该目标的 human/unknown 发言建立用途级确认，不覆盖原始消息。AI/通知不能凭此变成人类标签。
- 群聊保存、预览，不进入私聊关系、风格、记忆或训练。已存在用途映射冲突时拒绝，不静默改关系或重解释目标身份。
- 数据集按会话与时间间隔分段，将跨片段引用和近重复片段聚类，然后按时间划分完整片段，两个边界各留一簇隔离。其余约 80% 簇分给训练，余量均分给验证/最终测试，五簇起保证三个分区均有簇；这不保证过滤后一定有有效样本。少于五簇时仅训练集，或过滤后验证/测试为空时，均明确低可信、无有效独立评测。窗口仅在划分之后创建；连续本人短句合并，只有当前已确认 human 本人回复为 target。已冻结的非训练来源永不提升为训练；生产 tokenizer loss mask 由训练 worker 实现。
- 冻结 train/validation/test JSONL 与 manifest；文件哈希、源码版本、消息/批次来源、切分、关系、脱敏配置完整记录。未来构建不能把已冻结的 held-out 消息提升为训练数据。
- 风格草稿版本化、有来源和均长统计；范围内记忆可创建、确认、纠正、删除。只检索已确认、未删除、未过期条目；过滤 held-out 和回放时间之后的来源。

## 服务接口

```python
service.create_persona(name, target_identity_id=None)  # Persona dict
service.create_relationship(persona_id, name)        # relationship dict
service.inspect(path, format="auto", mapping=None)   # report
service.import_file(path, persona_id, relationship_id, owner_sender_id,
                    source_account_id, format="auto", mapping=None,
                    confirm_human=False, skip_errors=False)  # report
service.list_messages(persona_id, relationship_id, limit=200, before=None)
service.export_canonical(persona_id, relationship_id, destination)
service.build_style(persona_id, relationship_id, before=None)
service.add_memory(persona_id, relationship_id, text, source_message_ids,
                   confirmed=False)
service.update_memory(id, persona_id, relationship_id, text=None,
                      confirmed=None, deleted=False)
service.retrieve_memories(persona_id, relationship_id, query, before=None)
service.build_dataset(persona_id, relationship_id, gap_seconds=1800, redact=True)
```

`format`：`auto`、`qce`、`chatlab`、`csv`/`csv_mapping`、`canonical`/`canonical_jsonl`。

CSV 默认列：sender_id、occurred_at、text、conversation，message_id/sender_name 可选。映射：

```json
{"fields":{"sender":"sender_id","time":"occurred_at","text":"text","conversation":"conversation","message_id":"message_id","name":"sender_name"},"timezone":"UTC","time_unit":"iso","platform":"wechat","conversation_kind":"private"}
```

上述 CSV 映射只适用于已确认的私聊；未提供 conversation_kind 时默认为 unknown，不授予关系内用途。预览 `senders` 为 `[{id,name,source_account_id}]`；`preview` 为规范消息。Canonical 源账号必须匹配确认的账号，不能通过输入参数篡改来源。无 provenance.conversation_kind 的规范记录默认 unknown，不授予私聊用途；已知私聊需显式 mapping={"conversation_kind":"private"}，或通过 hash/count/scope/kind 验证的相邻 sidecar。已声明 group 不可通过参数改成 private。自己的规范导出保留 kind。

数据集路径在 Store.root/datasets/UUID；manifest 的 files 键为 train.jsonl 等，值为各文件 SHA256。dataset_hash 是去掉 dataset_hash/path 后 manifest 的规范 JSON（ensure_ascii=False、sort_keys=True、separators=(',', ':')）SHA256。API 返回额外 path，不写入 manifest。样本保存 messages（role/content）、source_message_ids、target_message_ids、target_index（最后一项）、segment_id。

## 证据和限制

`uv run pytest tests/test_data.py -q`：13 passed。覆盖坏行事务回滚、CSV BOM/换行/同秒连发、秒/毫秒/DST、未知媒体/群聊、CSV 与规范格式缺 kind 不授予关系用途、导出者与训练目标不同、规范格式权限不可信、重复导入、关系隔离/记忆删除、冻结哈希和 split 无重叠、测试来源不进风格/记忆。`uv run mypy` 数据模块通过；Ruff 通过。

对用户提供的 chat_record **仅做本地格式元数据检查**：8 个无扩展名文件，合计 146,747,392 bytes；初查未识别为 JSON/CSV/标准 SQLite/ZIP/gzip。2026-10-27 进一步确认 4 个为 MSG0，4 个仍未识别；用户新提供的电脑 QQ 导出 `.bak` 为含 4 个 MSG0 文件的 ZIP，CRC 通过但聊天尚未解密。没有输出账号、昵称或正文，没有复制入 Git。不能把格式识别当作导入成功；需要核对电脑端可见历史并取得版本明确的 QCE/ChatLab/CSV。新增只读 `import probe` 与网页 422 诊断，详见 [实际检查与合成回归](evidence/qq-bak-inspection-2026-10-27.md) 和 [QQ 步骤](qq-setup-research.md)。

T09：固定 QCE v6.3.2 单 JSON 真实导出已通过，其他版本不外推。T10/T11/T12：已有格式工程、显式身份重映射与 sidecar 验证；当前 QQ 本人稳定 UID 确认及真实导入通过，其他来源实际兼容仍需对应样本。10 万条合成 CSV 的预览/导入性能已测，见下文。T13：真实数据暴露并修复最终测试集固定一簇的问题，新增六项回归覆盖最小分区、无效尾部与冻结保留集；真实网页快照 37/14/5，核心全量 176 passed / 1 skipped。tokenizer mask/模型训练验收由训练线维护；短数据不形成有效质量结论。T14/T25：风格版本确认编辑、记忆纠正、来源删除传播到 adapter/部署/评测已实现。原始文件未托管复制；数据库留来源哈希。未知历史缺口无法推断。见 [实机证据](evidence/real-qq-export-and-probe-2026-10-27.md)。

近重复算法为片段文本规范化后 SequenceMatcher 0.9 阈值，复杂度二次；大数据集构建需性能优化和实测。脱敏规则仅处理 email/长数字，不保证清除地址等所有私人信息。已训练权重不自动遗忘。

## 10 万条合成 CSV 性能记录

在当前 Mac/Python 3.12 环境、临时目录（测试结束已清理）生成 100,000 条明确虚构消息：文件 8,377,832 bytes；预览全部记录 0.796 秒；事务导入 100,000 条 16.351 秒；该独立进程峰值 RSS 87,654,400 bytes（macOS resource.ru_maxrss）；SQLite 222,031,872 bytes。无真实数据、模型或外部消息。此证据只覆盖该数据规模与 CSV 导入，不代表近重复数据集算法性能或真实导出兼容。


后续实现补充：已加入显式风格确认/编辑、身份重映射、规范 sidecar 验证和来源删除传播，上述对应早期限制已由 [数据管理实现](data-management.md) 更新。QCE解析器已按固定源码契约补齐，真实导出兼容仍未验证。
