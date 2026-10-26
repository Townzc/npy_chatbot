# 数据管理与不确定发送恢复：实现及验收

本文件补充 T11/T12/T14/T18/T25，证据均为本地虚构数据和协议测试。没有读取真实聊天正文、登录 QQ、真实外发或替用户删除私人数据。

## 风格和记忆

`DataService.build_style` 现在只计算只读草稿统计，试聊不再每次写入风格版本。`save_style` 需最新 `expected_version`，每次保存新版本，只有明确 `confirmed=true` 的版本成为 approved。旧 approved 被标记 superseded，未确认草稿不替换现行指导。示例必须来自当前关系、经本人来源确认的 human 发言，且不在任何冻结 held-out/embargo 集中。`get_approved_style` 重新检查来源和回放时间；不会将失效的指导悄悄替换为旧版本。

记忆 PATCH 支持纠正文本、确认、到期时间与 `expected_version`。纠正默认重新进入未确认状态，保留本地版本历史；来源被撤销时清除文本和修正历史、标记 revoked，不能通过重新确认复活。历史回放同时要求来源时间和记忆创建/编辑时间早于 cutoff。所有时间必须带时区，消息查询先转换 UTC。

## 身份映射和规范 sidecar

身份页显示稳定账号、sender ID、昵称、当前角色及计数。手工重映射需 `expected_mapping_version`；原始消息 sender_id 不变，仅更新该 Persona 的 MessageUse。新的本人 human 来源确认是独立开关，不继承原目标的训练权限。映射版本递增，并撤销受影响关系的风格、记忆、数据集、模型产物及部署；会话暂停，需要重新验证数据和模型。

规范导出生成 `FILE.jsonl.manifest.json`，包含文件 SHA-256、记录数、Persona/关系及每个 conversation 的显式 kind。CLI 自动读取该固定相邻文件；HTTP 可在 mapping JSON 里提供 `manifest` 对象，不接受任意 manifest 文件路径。验证 hash、count、源记录 scope、kind 及所选目标 scope；不默认把未知或群聊变成私聊。第一版保守要求 scope 相同，跨实例重新绑定 manifest 的工作流未实现。裸规范 JSONL 仍可导入，但缺 kind 时没有私聊用途，除非用户显式提供已知 private 映射。

通用 CSV 同样默认 unknown；仅显式 `mapping.conversation_kind=private` 才可进入关系上下文、风格与训练。上传时选择一个关系不会自动证明原导出是私聊。

## 来源删除

先 GET deletion-impact，返回消息使用、共享原始记录、风格、记忆、数据集、模型、部署、活动作业、评测和关系影响；DELETE 必须提交该结果的 `impact_hash`。任何新增依赖使旧预览失效，返回 409，需要重新预览。

原始记录可被多个导入/Persona 引用。每个导入保存完整 message_ids 成员集合；删除一份导入只移除失去来源引用的 MessageUse，另一份明确来源仍在时保留原始记录，并重新关联存储批次。没有其他来源时删除原始消息。旧版本缺重复导入成员关系时拒绝推断删除，需先补齐可追踪来源。

数据库删除和派生状态撤销在同一 SQLite 事务中执行。数据集和评测文件先原子移动到私有 quarantine；事务审计记录作为唯一提交决定：回滚则恢复，提交则清理隔离文件。崩溃后的启动恢复按该审计决定处理；清理失败保留日志和隔离文件以便重试，报告 `quarantine_cleanup_pending`，不谎称已安全擦除。

评测 `evaluations/{id}/manifest.json` 记录案例、答案、检索及风格的全部 source_message_ids。删除来源时清除相交来源且范围一致的整个评测目录，返回 `revoked_evaluation_ids`；纯手工且无导入来源依赖的案例保留。身份重映射撤销整个受影响范围的评测。模型调用与评测写入共享来源锁，预载案例的来源被删除后也不能重新落盘。已有外部评分 CSV 副本不在自动清理范围。

风格示例/规则、记忆文本/修正历史清空；数据集与产物标记 revoked；对应部署状态列和 payload 一致撤销；会话模型恢复默认标识并暂停，未发送 AI/开启通知取消。返回 `cancel_job_ids` 由后台作业管理器取消。原始导出文件、用户下载的训练包、已有备份、平台已接收消息及旧模型权重不会被本操作撤回。模型权重不自动遗忘，需删除或重新训练后重新登记。

导入及所有依赖来源的写入（风格、记忆、数据集、评测）和规范导出与来源删除、身份重映射使用同一私有进程锁。导入不能用另一个 owner sender_id 绕过既有账号映射，需先走显式 remap。作业注册、启动和训练包导出也共享该锁。验证与注册事务复核，避免先读源、删除后再写入派生数据的“删后复活”。数据库事务期间更新的是确定的依赖集合，文件移动有恢复日志。外部下载副本不在本地原子性保证中。

## HTTP 接口

所有路由要求本人认证：

- `GET /api/v1/styles?persona_id=&relationship_id=` → draft、approved、history、version。
- `PUT /api/v1/styles` → Scope、rules、example_message_ids、confirmed、expected_version。
- `PATCH /api/v1/memories/{id}` → Scope、可选 text/confirmed/expires_at/expected_version。
- `GET /api/v1/identities?persona_id=` → 映射版本、links、participants。
- `PUT /api/v1/identities/remap` → persona_id、source_account_id、owner_sender_id、confirm_human、expected_mapping_version。
- `GET /api/v1/imports?persona_id=&relationship_id=` → 当前范围导入报告。
- `GET /api/v1/imports/{id}/deletion-impact?persona_id=&relationship_id=` → 影响与 impact_hash。
- `DELETE /api/v1/imports/{id}?persona_id=&relationship_id=`，body `{impact_hash}` → 撤销/删除报告。
- `GET /api/v1/datasets?persona_id=&relationship_id=` → 冻结版本（包括 revoked 状态）。
- `GET /api/v1/datasets/{id}/preview?persona_id=&relationship_id=` → 验证文件哈希后，每个 split 最多 5 个样本；revoked 拒绝。

`data_router(store, get_coordinator, authenticate)` 由主 API 装配。所有写操作在 `scope_update` 屏障中执行；HTTP 客户端断开时必须等待底层线程完成并执行撤销回调，之后才能降低屏障。更新期间新建的 Binding 继承更新计数，不能趁窗口开启 AI。`on_sources_revoked(result)` 回调用于取消作业。

## unknown 发送恢复

`control_router(store, get_coordinator, authenticate)` 仅操作当前发送器实际账号的活动 Binding。归档 Binding 目前不能在线核对，需要后续独立恢复流程；不会自动跨账号解除阻塞。

1. `GET /api/v1/outbox/unresolved?binding_id=` 查看 unknown、发送类型、正文、已知平台 ID 和核对历史。
2. `POST /api/v1/outbox/{id}/reconcile`，body `{binding_id}`，仅尝试渠道只读核对。OneBot 当前没有按本地请求 ID 可靠查询的标准实现，因此可能继续 unknown；不会伪造确认。
3. 本人在原平台核对后，`POST /api/v1/outbox/{id}/resolve`，body 包含 binding_id、outcome（sent/not_sent）、可选 platform_message_id、6–2000 字证据说明及 expected_control_epoch。not_sent 不能同时给出一个已发送平台消息 ID。

人工观察明确记录 source=owner_attested，不冒称通过平台 API 验证。相同观察重试只形成一条审计结论。sent 标记 confirmed，not_sent 标记 rejected；两者都不重试旧请求，也不恢复 AI。旧 enable 的确认不能激活新 epoch；AI unknown 确认后仍需本人重新开启。迟到回执或只读查询若与人工观察矛盾，会重新进入 unknown 并停止新托管。读取平台证据时不持接管锁，等待核对不会阻止本人接管。

## 验证证据

`tests/test_data_management.py` 20 项通过，覆盖确认风格与草稿区别、乐观版本、记忆纠正/到期、sidecar hash/count/scope/kind、完整来源删除传播、跨 Persona 共享来源保留、失效删除预览、文件移动后数据库失败回滚、崩溃恢复、人工身份重映射、认证 API/样本预览、嵌套 scope 更新期间线程新建 Binding、训练注册与删除并发、三类派生数据写入与删除并发、评测副本清理与回滚、预载案例不可删后复活、导入与重映射并发。

`tests/test_reconciliation.py` 10 项通过：不确定开启通知和 AI 回复、sent/not_sent、显式重新开启、重复观察幂等、只读查询、迟到冲突、跨绑定/账号/归档拒绝、过期页面、submitting 不可猜测为未发送、慢查询时仍可接管、认证与证据校验。

独立运行路径回归验证：HTTP 请求持有来源租约时删除等待；本人接管不等待该租约；请求完成后来源撤销，旧候选拒绝，不能重新建立记忆或发送 AI 回复。数据写操作最多等待 45 秒，繁忙时返回 DATA_BUSY，可稍后重新预览并重试。

这些结果不等于真实 QQ 核对成功、训练质量达标或完整数据合规擦除。运行目录的恢复只覆盖本项目持有的文件；原始容器的提取与 QCE 真实格式仍是外部输入阻塞。
