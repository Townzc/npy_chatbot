# contracts.md

本文件是完整计划的按主题阅读副本。规范以 [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 为准；来源见 [sources.md](sources.md)。修改计划时使用随包脚本重新生成这些副本。

## 5. 数据模型、隔离与接口契约

### 5.1 身份与范围

| 对象 | 含义 | 关键限制 |
|---|---|---|
| Persona | 一个用户自己创建的个人 AI 档案；保存 target_identity_id 和 identity_mapping_version | 目标身份可映射到多个已确认的来源 participant，不把不同档案混成全局提示词 |
| SourceAccount | 历史导出所属平台账号 | 导出者不一定是用户选择的训练目标 |
| Participant | 历史中的人物 | 按平台/来源账号的稳定 ID 区分，名称仅展示 |
| Relationship | 本人与特定联系人的关系空间 | 跨 QQ/微信关联需明确确认；不按同名自动关联 |
| Conversation | 一个历史或实时会话 | 私聊/群聊分别标识 |
| ChannelAccount | 一个实时消息登录身份 | 与历史 SourceAccount 的绑定需检查 |
| Binding | Persona + Relationship + ChannelAccount + Conversation | 不可变绑定，所有发送从此取得收件人；同一实时会话只有一个活动绑定 |

作用域至少包含 persona_id、relationship_id；实时上下文再包含 channel_account_id、conversation_id。跨平台共同记忆只有在明确绑定同一关系后才可共享。global 范围只放用户主动确认适用于所有联系人的偏好或表达习惯，不能自动升级关系私事为全局事实。

Binding 的账号、联系人、会话和档案不允许原地改写。重新绑定时先停止旧 session、失效旧候选，归档旧绑定并创建新的 binding_id；旧 outbox 保留旧目标快照，绝不能按新绑定地址重发。新绑定默认 HUMAN。

owner 明确定义为当前 Persona 经确认的目标身份，不等同导出者、群主或昵称“我”。原始 sender_id 是来源事实；sender_role 和 use_policy 是特定 Persona 下的 MessageUse 映射，带 identity_mapping_version，不得全局修改同一消息的角色。群聊保留独立 conversation scope，relationship_id 可为空；v1 仅保存/预览，禁止自动进入双人关系记忆、风格或训练，不按群内发送者拆成私聊。

同一 LoRA 若学入多个联系人的私密事实，RAG 的过滤不能保证权重不复述。因此默认训练**关系专用 adapter**，通用风格数据需独立脱敏审查。强隔离关系必须用各自数据集/产物；共享风格模型仍要做跨关系泄漏评测。

### 5.2 规范消息字段

所有平台账号 ID 和消息 ID 使用字符串。内部记录 ID 用 UUID。时间存 UTC ISO 8601，保留原始时间值与解析时区。

| 字段 | 类型与规则 |
|---|---|
| schema_version | 固定主版本，如 "1.0" |
| id | 内部消息 ID |
| source | platform、importer/version、source_account_id、source_message_id、import_batch_id、file_sha256、record_index |
| conversation_id / relationship_id | 会话必需；已映射私聊有关系引用，未映射及群聊的关系可为空 |
| sender_id / sender_role | sender_id 是来源人物；角色 owner、partner、other、system 属于用途映射，不覆盖原始人物 |
| origin | human、ai、mode_notice、platform_system、unknown |
| occurred_at / ingested_at | 消息发生及进入本系统的时间；不能互相替代 |
| sequence | 源文件顺序，解决相同时间戳排序 |
| content | type、text、attachments、reply_to、unsupported_type |
| use_context / use_policy | Persona、关系、identity_mapping_version、派生 sender_role 及上下文/风格/训练标记；规范导出携带该映射，底层原始消息保持独立 |
| provenance | 解析警告、修改记录、来源定位及原始引用 |

历史导出常常没有 human/ai 的可靠标记。默认 origin=unknown，用户可基于时间范围确认本人真实发言；未确认的 unknown 不自动成为训练标签。系统上线后的 AI、通知与人工发言分别记录，防止不断学习自己的旧生成内容。

缺失消息 ID 时保证“同文件＋行号”的导入幂等；跨文件可能重复另列待审，不能仅按“同一秒＋同样文字”删除真实连发。媒体不存在时明确 missing，引用目标缺失时保留 unresolved，不补造正文。

### 5.3 核心数据表

| 表组 | 关键内容 |
|---|---|
| personas、source_accounts、participants、identity_links、message_uses | 目标身份、账号映射、确认记录、用途及版本 |
| relationships、conversations、bindings | 使用范围、活动关系和目标会话 |
| import_batches、source_files、messages、attachments | 原始来源及规范数据 |
| style_profiles、style_examples、memory_items、memory_sources | 个性化与可追溯记忆 |
| dataset_versions、dataset_examples、split_assignments | 冻结数据集、来源及划分 |
| training_jobs、model_artifacts、model_deployments | 作业、底座、adapter 与部署版本 |
| mode_sessions、mode_transitions、inbound_events、outbox | 控制、入站幂等、发送状态 |
| jobs、eval_runs、audit_events、usage_records | 后台任务、评测、诊断与用量 |

数据库必须有外键、作用域索引和业务唯一键。生成规范消息和用途映射后，在允许范围内共享底层原始文件引用，避免重复拷贝；删除时做引用计数及影响预览。

### 5.4 四个扩展接口

~~~python
class Importer:
    def detect(self, file_header, metadata) -> Detection: ...
    def inspect(self, source) -> ImportPreview: ...
    def parse(self, source, mapping) -> Iterator[NormalizedMessage]: ...

class ChannelAdapter:
    def capabilities(self) -> ChannelCapabilities: ...
    async def receive(self) -> AsyncIterator[ChannelEvent]: ...
    async def send_text(self, request: SendRequest) -> SendReceipt: ...
    async def reconcile(self, pending: PendingSend) -> ReconcileResult: ...

class ModelProvider:
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def health(self) -> ModelHealth: ...

class TrainingBackend:
    def validate(self, spec: TrainingSpec) -> PreflightReport: ...
    def run(self, spec: TrainingSpec, workdir) -> TrainingResult: ...
    def cancel(self, job_id) -> CancelResult: ...
~~~

这是接口规格示意，交付代码需要完整类型、异常与具体实现。reconcile 不可实现时返回 unsupported，不能假造发送成功。

ChannelCapabilities 必须包含 receive_private、send_text、self_echo、history_lookup、stable_message_id、idempotent_send、recipient_identity_kind 及实测版本。OneBot API 的请求 echo 只是请求响应关联，不能据此宣称平台发送幂等。

Candidate 保存 binding_id、control_epoch、context_seq、persona_version、memory_version、model_deployment_id、input_message_ids、text 和过期时间，不接受模型提供 target_user_id。

## 12. 管理界面、API 与命令行

### 12.1 页面与用户可完成的任务

| 页面 | 必需能力 |
|---|---|
| 首次配置 | 选择私有数据目录、创建本人访问凭证、模型连接测试、加载虚构示例 |
| 档案与身份 | 创建档案、确认本人、多平台账号/关系映射 |
| 数据导入 | 文件、格式预览、人物/字段映射、用途选择、导入报告 |
| 风格与记忆 | 编辑风格、查看出处、确认/纠正/删除记忆 |
| 网页试聊 | 基础/个性化/微调对照、显示当前档案与模型、查看所用记忆 |
| 数据集与训练 | 样本预览、split 报告、训练预检/启动/取消、训练包、产物与评测 |
| 渠道与会话 | 账号核验、好友绑定、模式状态、两条通知、接管、错误恢复 |
| 设置与维护 | 用量预算、私有访问、备份恢复、诊断、版本及兼容矩阵 |

QQ 接管按钮在移动端固定可见。开启结果不能只弹“成功”：明确显示通知确认与当前模式。数据扫描、模型下载和训练进度不能阻塞控制页。

### 12.2 REST v1 资源

| 路径组 | 主要用途 |
|---|---|
| /api/v1/personas、/relationships、/identities | 档案与关系配置 |
| /api/v1/imports/inspect、/imports、/imports/{id} | 预览、创建、查看/取消导入 |
| /api/v1/datasets、/datasets/{id}/preview | 构建快照、查看 split/样本 |
| /api/v1/styles、/memories | 查看、确认、编辑和删除 |
| /api/v1/training-jobs、/training-jobs/{id}/cancel | 预检、启动、取消和状态 |
| /api/v1/model-artifacts、/model-deployments | 登记产物、测试和切换 |
| /api/v1/channels、/bindings | 渠道连接、身份与会话绑定 |
| /api/v1/conversations/{id}/mode | 开启 AI / 本人接管；携带 command_id、expected_control_epoch |
| /api/v1/conversations/{id}/status | 模式、通知、阻断原因和当前版本 |
| /api/v1/sandbox/messages、/eval-runs | 网页试聊和评测 |
| /api/v1/jobs、/health、/usage、/backups | 后台任务、健康、用量和备份 |

创建长任务返回 202 和 job_id。开启 AI 等增加发送权限的操作严格检查 expected_control_epoch，冲突返回 409。本人接管属于停止操作：在账号与会话授权仍有效的前提下，旧页面的 epoch 不得阻止停止；服务端按最新状态接管并返回实际版本。非法输入返回有字段定位的错误；接口不可用明确返回对应错误码。启用 AI 的 HTTP 接受不等于已经通知成功，前端订阅或查询 transition 状态。

前后端类型由后端契约生成，不分别手写两套互不一致的 Message。服务端事件流使用已认证的 SSE 或 WebSocket；不得把 token 放入公开日志或分享 URL。

### 12.3 CLI 目标

以下命令名为待实现契约，当前文档包不含可运行程序：

~~~text
chattwin demo
chattwin doctor
chattwin serve
chattwin import inspect FILE
chattwin import run FILE --mapping MAPPING
chattwin dataset build --persona ID --scope ID
chattwin train run --spec SPEC
chattwin train cancel JOB_ID
chattwin model serve --artifact ARTIFACT
chattwin eval run --suite SUITE
chattwin backup create
chattwin backup restore BACKUP
~~~

无真实账号、无模型密钥的开发者，应能运行 demo 和默认测试；真实渠道/模型测试必须单独标识，不隐藏触发付费或发送。
