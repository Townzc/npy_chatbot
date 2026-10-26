# ChatTwin 开源个人 AI 机器人：完整开发计划 v2

**方案版本：2.0 · 日期：2026-10-26 · 状态：可交给 Codex 实施的规格与任务计划，尚未实现或实机验收。**

ChatTwin 是本计划的工作名称，仓库名、包名及商标可用性尚未核查。本文替代上一版仅面向单个 QQ 私聊的计划；这次确定的目标是可供其他人自行部署的开源产品。文中的版本、里程碑和验收数字都是开发目标，不代表已具备的能力。

## 0. 结论与本次确定的决策

项目可以推进。定义为：

> 用户在自己的电脑上导入已经取得的 QQ、微信等聊天记录，确认“哪些发言是我”，建立自己的风格、记忆和可选微调模型；先在网页中试聊，再接入消息渠道。在个人 QQ 原有私聊中，开启 AI 时发“对方已切换为ai模式”，本人接管时先停止 AI，再发“本人已接管”。

本次确定以下方向，Codex 不必重新讨论这些基础选择：

1. **开源核心独立实现，默认采用 Apache-2.0。** 依赖及模型各自保留许可证；不把有额外限制的桥接程序、导出程序或私人数据重新打包成 Apache 软件。
2. **本地单用户、多个人档案、多个明确选定的私聊。** “大家都能用”指每人部署自己的实例；v1 不建设多租户 SaaS、账号交易平台或公共模型市场。
3. **数据源和消息渠道分开。** 导入微信记录不要求同时接管微信个人号；同一档案可在网页试聊或绑定 QQ。
4. **先做好可用的端到端产品。** v0.1 导入和网页试聊，v0.2 QQ 原会话与模式通知，v0.3 真正 LoRA 训练和模型切换，v1.0 完成安装、评测、恢复及开源发布。
5. **微调是一项正式能力。** v1 必须交付一个真实可执行的训练后端；不能以“导出训练 JSON”或“拼接提示词”冒充完成训练。用户无需微调也可以使用产品。
6. **你提出的两句通知作为默认文本原样使用。** 由程序发送，不由模型改写；每次有效模式切换只创建一条通知记录。
7. **核心不依赖具体 QQ/微信导出器存活。** 首批实现 QCE JSON、ChatLab JSON/JSONL、通用 CSV 映射和项目自己的规范格式。
8. **首发实时渠道为本地网页及 QQ OneBot 适配。** QQ 个人号桥需单独核实许可和实机兼容；微信 ClawBot 可作为后续独立机器人渠道，微信原本人号好友窗口代答需另行验证。
9. **Mac 是你的运行主机优先目标。** GPU 训练可在另一个 Linux/CUDA 环境完成。Mac 上安装核心不强制安装 PyTorch/CUDA。
10. **任何外部依赖受阻，只阻断相应能力。** Codex 继续完成不依赖该条件的实现和测试，并如实标注未验证项，不能把模拟器测试写成真实 QQ 测试。

## 1. 产品范围与最终使用体验

### 1.1 v1.0 用户完整流程

1. 安装本地服务，打开管理页；没有聊天数据也能先加载项目自带的虚构示例。
2. 创建一个“我的 AI”档案，配置模型接口或本地模型端点。
3. 导入 QQ/微信记录文件，预览发送者、时间、内容与会话，确认本人身份及要使用的数据范围。
4. 得到导入报告：可读日期、消息数、跳过条目、未知类型、重复项和无法判断的缺口。
5. 生成并编辑风格画像，选择可用风格示例，确认共同记忆。
6. 在网页试聊，比较基础模型、风格增强、记忆增强的差异。
7. 有训练条件时构建数据集、运行 LoRA、查看训练结果、对照评测，并选择是否启用该模型。
8. 配置自己的 QQ 桥接端，选择一个私聊，看到原账号与目标好友的稳定标识。
9. 点击“开启 AI”：对话收到“对方已切换为ai模式”；成功后机器人开始处理这一轮新消息。
10. 点击“本人接管”：本地立即停止新的 AI 发送，对话收到“本人已接管”；已经提交给平台的消息在界面单独提示。
11. 在手机上查看状态、接管、审核记忆和处理异常。
12. 更新或卸载时能备份、恢复、回滚、导出自己的数据，并知道哪些本地及远端副本仍存在。

### 1.2 支持矩阵：发布时必须这样分列

| 能力 | v0.1 | v0.2 | v0.3 | v1.0 |
|---|---|---|---|---|
| QCE JSON 导入 | 支持固定样本版本 | 增量完善 | 同前 | 有兼容报告 |
| 微信记录导入 | 支持已转换的 ChatLab/CSV | 同前 | 同前 | 至少一份版本明确的真实脱敏导出验证 |
| 项目规范 JSONL 与导出 | 支持 | 支持 | 支持 | 稳定 schema v1 |
| 网页试聊、风格与记忆 | 可用闭环 | 改进 | 可比较微调模型 | 有评测和管理功能 |
| QQ 现有个人号原私聊 | 接入探针可提前做 | 受控可用，需实机通过 | 同前 | 固定环境完成灰度运行 |
| 两条模式通知与手动接管 | 模拟器通过 | 真实 QQ 通过 | 回归通过 | 故障与恢复验证 |
| 真正 LoRA 微调 | 预留数据契约 | 数据集已可构建 | 至少一个后端完整可运行 | 训练、加载、评测、回滚可复现 |
| 手机控制页 | 基础响应式 | 接管可用 | 训练结果可查看 | 远程控制路径实测 |
| 微信 ClawBot 独立对话 | 不包含 | 不包含 | 不包含 | 后续 v1.1 候选 |
| 微信个人号原好友窗口代答 | 不承诺 | 不承诺 | 独立调研 | 不作为 v1 已支持能力 |
| 图片理解、语音、表情包发送 | 保留类型，不理解内容 | 同前 | 同前 | v1.1 以后独立验收 |
| 手机数据库/官方备份包直接提取 | 不包含 | 不包含 | 不包含 | 外部前提，不能宣称全量自动提取 |

“微信记录导入”指能处理用户已经取得且符合支持格式的记录。不能用该名称暗示直接读取任意版本的 iPhone 微信数据库。当前用户的 iPhone QQ 漫游为 7 天，旧记录可用范围仍需实际核查；这不阻止先用可取得的数据完成产品。

### 1.3 首个稳定版本的界限

v1 处理明确选择的**文字私聊**。导入群聊时可保留并浏览，但默认不用于训练和关系记忆；若加入群聊训练，必须另做说话人及回复归属验收。

v1 支持一个本地实例里的多个档案，但默认一次只绑定一个个人 QQ 账号。不同会话可分别开关；同一渠道账号的同一会话只能绑定一个活动档案。用户导入的历史、生成的模型、浏览器控制账号不与其他部署共享。

首版不做自动主动搭讪、自动加好友、群发、支付操作、网页操作、执行聊天中给出的代码、任意工具调用、商业托管平台和插件市场。未知附件保留占位与来源，不能装作已经理解。

## 2. 已定技术方案与扩展边界

| 决策 | 默认方案 | 实施要求 |
|---|---|---|
| 代码组织 | 一个 monorepo，Python 模块化单体 + Web 前端 + 独立训练 worker | 不提前拆成大量网络微服务 |
| 后端 | Python 3.12、FastAPI、Pydantic | 锁定兼容依赖；导出 OpenAPI 和 JSON Schema |
| 存储 | SQLite、SQLAlchemy、Alembic；大文件在私有数据目录 | 事务、索引、迁移和恢复都在 v1 范围 |
| 前端 | React + TypeScript + Vite；构建后由后端提供静态文件 | 核心安装后不要求用户常驻 Node 开发服务器 |
| Python 环境 | uv 管理与锁文件 | 核心、开发、训练依赖分组；GPU 依赖隔离 |
| 长任务 | SQLite jobs 表 + 有限后台 worker | 有状态、心跳、取消、重启恢复；无需 Redis/Celery |
| 初始检索 | 带范围过滤的结构化查询 + 中文关键词检索 | 先证明正确性；向量检索后接同一接口 |
| 模型推理 | MockProvider + 一种实际 HTTP 模型 API + 本地训练模型服务 | API 兼容格式不代表所有供应商行为相同，分别检测能力 |
| 微调 | Transformers + PEFT LoRA 独立 worker | 首个支持环境为验证过的 Linux/CUDA；其他硬件标状态 |
| 参考底座 | Qwen/Qwen3-4B-Instruct-2507 作为首个验证候选 | 固定实际 revision、tokenizer 与模板；不宣称是当前最佳模型 [S13] |
| QQ | 自写 OneBot v11 客户端，外接用户配置的桥 | 首先实现一种 WS 连接方向；额外方向后加 |
| 软件许可证 | 自写核心默认 Apache-2.0 | 不复制后再删除他人许可；发布前生成依赖清单 [S14] |
| 默认监听 | 127.0.0.1 | 手机访问启用认证、私有网络或受控 TLS 入口 |
| 遥测 | 默认无外发遥测 | 用户可主动导出脱敏诊断包 |

**v1 不建设通用插件运行平台。** 仅为 Importer、ChannelAdapter、ModelProvider、TrainingBackend 定义稳定边界；内置实现用注册表管理。任意用户上传的 Python、Shell、序列化对象或模型自定义代码不得自动执行。

## 3. GitHub 项目与开源复用策略

资料核查于 2026-10-26。上游可能继续变化，实际实现记录固定 commit/tag 和许可证摘要。

| 项目 | 已核实事实 | 本项目采用方式 |
|---|---|---|
| QQ Chat Exporter / QCE | JSON 等导出；GPL-3.0；Mac 原生 arm64 路线为预览 [S2] | 独立解析其导出文件，不内置整个导出器 |
| ChatLab | 有 v0.0.2 JSON/JSONL 交换格式；仓库 LICENSE 为 AGPL-3.0 [S3][S4] | 独立实现格式互通；内部增加训练与来源字段 |
| WeFlow | 列 ChatLab 等导出；当前 CC BY-NC-SA 4.0；原生数据组件需用户另行配置 [S5] | 接收已导出的 ChatLab 文件；原生 JSON 等有样本再兼容 |
| WeClone | 画像、预处理、真实 SFT 和推理；AGPL-3.0；当前 README 数据源表未列任意 QQ/微信 JSON 直导 [S6] | 研究流程；兼容转换为可选插件，核心自行实现 |
| NapCatQQ | QQ 接入；自定义 Limited Redistribution License，含非商业及修改分发限制 [S7] | 可选外部运行时候选；不打包、不自动安装，先核实适用授权 |
| NapCat Mac Installer | 提供 Mac 安装路径；安装器自身许可与 NapCat 本体不同 [S8] | 记录安装路径与已测组合，不转化为兼容保证 |
| Tencent/openclaw-weixin | MIT；公开 Bot 协议，区分 Bot ID 与扫码用户 ID [S9] | v1.1 独立微信机器人渠道候选，不等于接管原好友私聊 |
| AstrBot / MaiBot | 已有机器人框架及个性化能力；分别 AGPL-3.0、GPL-3.0 [S10] | 可做效果/接入对照；本项目不同时运行第二套自动回复器 |
| sjzar/chatlog | 官方仓库现为代码移除通知 [S11] | 不作为现行安装依赖 |
| LC044/WeChatMsg | 当前文档表示不再更新，仓库主要保留说明 [S12] | 可考虑已有文件兼容，不作为现版通用提取器 |

**开源发布边界：**发布自己的源码、格式解析器、协议适配器、训练代码、合成示例、测试和文档。真实聊天记录、账号会话、密钥、私人 LoRA 权重及受限第三方二进制不随仓库发布。使用独立进程有助于替换组件，但不自动消除上游许可证要求。

ChatLab 的根许可证和部分中文说明存在用语不一致，因此本方案只采用独立格式互通；若以后直接复用代码，先澄清适用条款。微信 ClawBot 官方产品流程是在独立对话页聊天，不能用它证明“用户本人原有好友窗口代答”已经可行。[S4][S9]

## 4. 总体架构与模块边界

### 4.1 结构

~~~mermaid
flowchart TD
    I["记录导入器"] --> D["规范数据与身份映射"]
    D --> P["风格、记忆与数据集"]
    P --> T["可选训练 worker"]
    T --> R["模型与版本注册"]
    P --> C["对话引擎"]
    R --> C
    A["网页或 QQ 适配器"] --> K["会话控制器"]
    K --> C
    C --> O["唯一发送队列"]
    K --> O
    O --> A
    U["本人管理页"] --> K
    U --> P
~~~ 

导入器读取文件，对话适配器处理实时事件。两者只在规范数据层汇合。模型产生候选内容；接收人、模式和发送权限始终由确定性代码决定。

### 4.2 模块职责、接口和完成条件

| ID / 模块 | 负责内容与主要接口 | 首个具体实现 | 完成证明 |
|---|---|---|---|
| A / domain | Message、Persona、Scope、Job、Candidate、ModeTransition、SendReceipt 契约 | Pydantic 模型、schema v1、错误码 | 序列化和字段兼容测试 |
| B / storage | 事务、迁移、记录查询、私有文件索引、repository | SQLite + Alembic + 文件哈希 | 升级、重复运行、备份恢复通过 |
| C / importers | detect、inspect、parse、preview；不训练、不发送 | QCE、ChatLab JSON/JSONL、CSV、规范 JSONL | 同文件重复导入幂等；坏行有报告 |
| D / identity | 导出者、本人、多平台账号、联系人与关系映射 | UI 人物确认 + 稳定 ID 映射 | 同名不同人不合并；跨平台手工关联 |
| E / datasets | 过滤、脱敏、会话切分、标签、数据集快照与 split | owner-only SFT 样本构建 | 他人发言不作为目标；数据泄漏检查通过 |
| F / personalization | 风格统计、示例选择、人设草稿及版本 | 长度/语气统计 + 可编辑画像 | 每条示例有来源；不掺入隐藏测试集 |
| G / memory | 候选、确认、范围、有效期、检索、纠正、删除 | SQLite 范围过滤 + 中文关键词 | A 联系人的私事不进入 B 上下文 |
| H / training | 训练预检、作业、日志、取消、产物登记 | Transformers + PEFT LoRA worker | 真实参数更新、保存、重新加载、推理成功 |
| I / models | 统一生成接口、能力检测、计费记录、版本切换 | mock、HTTP API、本地 LoRA 服务 | 超时/取消可处理；可恢复上一模型 |
| J / conversation | 去重、合并短消息、上下文、检索、生成与候选校验 | 一个可回放的文本对话流水线 | 新消息/接管使旧候选失效 |
| K / control | 本人/AI 模式、切换通知、权限、阻断条件、epoch | 确定性状态机 | 两句通知、异常、重启竞争全部测试 |
| L / channels | 接收标准事件、发送文本、回执、能力与健康 | WebSandbox、FakeChannel、OneBot v11 | 同一测试套件适配每个渠道 |
| M / outbox | 全部外发入口、单写者、认领、排序、结果不确定处理 | SQLite outbox + 账号进程锁 | 不重复认领；未知结果不盲重发 |
| N / api-web | 本人认证、导入向导、试聊、模式开关、训练与状态 UI | FastAPI + 响应式 React | 手机完成导入预览和接管关键路径 |
| O / evaluation | 场景回放、质量比较、隐私探测、训练验收报告 | pytest + 本地 eval CLI/UI | 报告可复现且区分模拟/真实 |
| P / operations | doctor、健康、启动、脱敏诊断、备份、恢复、发布 | CLI + OS 启动指南 | 新环境安装与一次回滚演练 |

**依赖约束：**

- domain 不导入 FastAPI、QQ、模型 SDK 或 UI。
- importers 和 training 不依赖 channels；数据可以完全离线处理。
- conversation 不能直接调用渠道发送，只能创建 Candidate。
- control 创建模式通知；outbox 是调用 ChannelAdapter.send_text 的唯一位置。
- API/UI 调用应用服务，不直接拼接 QQ 请求或写表规避状态机。
- training worker 不持有 QQ/微信凭证，模型服务不持有控制页管理员凭证。
- 外部来信不能变成控制 API 权限，也不能改变收件人或模型配置。

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

## 6. 导入模块与数据质量

### 6.1 首批支持的具体路径

| importer | 格式与入口 | 版本策略 |
|---|---|---|
| canonical_jsonl | 项目 schema v1，逐行消息加 manifest | 主版本不兼容拒绝，迁移显式执行 |
| qce_json | QCE 固定版本导出文件 | 以真实脱敏 fixture 建立映射；不能猜 JSON 字段 |
| chatlab | ChatLab v0.0.2 JSON 和 JSONL | 两种结构分别测试；未知字段保存或报告 |
| csv_mapping | 用户映射 sender、time、text、conversation、可选 message_id | 保存映射模板和时区；先预览再正式写入 |

ChatLab 文档有发送者、秒级时间戳、消息类型和可选原始 ID；JSONL 由 header/member/message 行构成。内部另补来源、训练身份和隔离字段。[S3]

具体转换要求：

- ChatLab timestamp 按秒解析；exportedAt 只作导出时间；不能把群主角色当作“训练本人”。
- 私聊缺少稳定会话 ID 时，由已确认的来源账号与参与者映射生成内部会话，不用展示名称作键。
- meta.platform 若为 im 或未知值，保留原值并在预览中确认，不擅自归类为微信。
- CSV 昵称变化、日期歧义、秒/毫秒、空内容、BOM、换行和编码错误要有测试。
- JSONL 可逐行报告错误；默认严谨模式不静默丢行。允许用户显式选择跳过，并将数量写入报告。
- 原生 WeFlow JSON、历史 WeChatMsg CSV、chatlog 导出均需具体版本样本后再声明兼容。
- 大文件采用流式解析/分页写入；v1 基准包含 10 万条合成消息，报告耗时与峰值内存，不承诺未经测量的固定性能。
- 不在导入时自动访问附件 URL、下载远端文件或执行文本中的内容。

### 6.2 标准导入作业

文件校验与哈希 → 格式识别 → 预览 → 本人及联系人映射 → 范围选择 → 流式解析到暂存 → 校验报告 → 事务发布批次 → 后续索引任务。

未知格式显示缺失字段与通用模板，不把错误伪装为空数据。取消或中断后不留下对外可用的半批次；临时文件可清理，重新运行能识别重复。

### 6.3 导入报告必须包含

源文件名与哈希、格式及 importer 版本、选择的账号/人物、起止日期、消息总数与各类型数、有效文本数、候选训练目标数、跳过/坏行数、稳定 ID 覆盖率、未解析引用、重复判断、未知时间段及抽样核对结果。

“成功解析所有提供的行”不等于“聊天历史完整”。iPhone、漫游、换设备和历史清理造成的缺失要分开说明。数据不足时可以先做风格与网页试聊，不强行训练或编造缺失对话。

## 7. 个性化、记忆与数据集

### 7.1 三类信息分别管理

- **风格：**句长、称呼、口头语、标点、emoji、接话节奏、不同关系的语气。统计结果和用户编辑的规则都有版本。
- **关系记忆：**有出处的事件、偏好、约定和人物信息，带关系范围、时间、确认状态和有效期。
- **最近上下文：**当前会话近期消息，只在对应绑定内使用，不能充当长期事实自动扩散。

自动提取的画像和记忆先作为候选，可逐条审核；用户可一次审核一批，但能看见出处。对不确定日期、玩笑、否定、引用和相互矛盾的信息保留状态，不直接改写成确定事实。

### 7.2 统一检索流程

先按档案和关系授权过滤 → 排除删除、过期及不确定条目 → 按关键词/时间相关度检索 → token 预算裁剪 → 组装带来源的上下文。

若以后加入 embedding，必须在同样的权限范围内检索；不能先全库找相似结果，再仅依靠提示词要求保密。缓存键包含 persona、relationship、模型、记忆及风格版本。

删除记忆要处理数据库、全文/向量索引、摘要及缓存。删除训练来源还应标记所有依赖数据集和 adapter 的状态；已训练权重不自动遗忘，需重新训练或停用相关产物。

### 7.3 SFT 样本构建规则

1. 按会话、时间间隔和回复关系构建片段；先保留多轮关系，不把两条相邻消息机械配成问答。
2. 只有“身份匹配当前 Persona 的 target_identity_id、origin=human 已确认、use_policy 允许训练”同时成立的发言才能成为目标；对方只作为上下文。导出者身份不直接决定标签。
3. 连续本人短句可在同一个目标回复内用换行保留；保存原始消息列表以便追溯。
4. 排除模式通知、平台事件、未知发言来源、未理解媒体、机器人自动回复和用户排除项。
5. 联系方式、账号、地址等按用户选定规则脱敏；脱敏结果要可预览，不能声称算法保证清除全部隐私。
6. 先对完整会话片段做去重/近重复聚类和 split，再生成滑窗样本。训练/验证/测试之间不能因重叠窗口重复相同对话。
7. 推荐按时间分段并在边界留隔离区；数据过少时显示低可信评测，不静默退回逐条随机切分。
8. 训练输入可以包含历史本人发言，但 loss 仅计算当前目标本人回复的 token；系统、对方、历史上下文和 padding label 均屏蔽。
9. tokenizer、chat template 和目标 token 边界要有专门测试；不通过字符串简单匹配来猜目标起点。
10. 目标被截断、target token 为零、全部未知类型时跳过并报告，不把无效样本送入训练。

### 7.4 数据集快照

每个版本包含 train/validation/test 文件、manifest、源批次与消息 ID、过滤及脱敏配置、split 分配、模板版本、生成代码 commit、计数和哈希。冻结后不原地修改；纠错创建新版本。

私有数据集不会自动推送 Hugging Face、GitHub、公共监控服务或开发 agent 的云端上下文。示例仓库只提供明确虚构的数据。

## 8. 真正训练、模型产物与部署

### 8.1 两条用户路径

| 路径 | 操作 | 对用户的准确描述 |
|---|---|---|
| 快速个性化 | 选择基础模型，使用风格示例和范围内记忆 | 个性化配置，不改变模型权重 |
| LoRA 微调 | 从冻结数据集训练 adapter，再评测和部署 | 发生实际参数更新；结果可能优于或劣于基础方案 |

微调是可选使用方式，但其实现是 v1 的必交付功能。没有 GPU 时，用户仍可使用快速路径；训练页面显示可导出的训练包和运行要求，不显示虚假的“训练完成”。

### 8.2 首个训练后端

实现一个自有 Transformers + PEFT LoRA backend。PEFT 提供参数高效微调及 adapter 加载能力；具体依赖版本和设备组合由 M0/M4 锁定验证。[S15]

参考底座先验证 Qwen/Qwen3-4B-Instruct-2507，其模型卡声明 Apache-2.0 并提供 Transformers 使用方式。[S13] 这是明确的验证起点，不保证对每个人最佳，也不预设用户 Mac 能完成训练。显存需求通过 dry run 测量，报告模型精度、序列长度、batch、梯度累积和峰值；不把参数量直接换算成保证可运行的显存数。

首版支持 bf16/fp16 等经过验证的 LoRA 配置；QLoRA、多卡、MLX、全参数微调和自动超参搜索后续另加。训练环境在用户自己的机器或明确选择的 GPU 环境，项目不默认租卡或访问已有科研资源。

### 8.3 TrainingSpec 必需字段

dataset_version/hash、persona_id、relationship_scope、base_model_id/revision、tokenizer_revision、chat_template_hash、backend/version、precision、LoRA target_modules/rank/alpha/dropout、max_sequence_length、batch/accumulation、learning_rate、epochs/max_steps、seed、输出路径、取消标识及依赖锁文件摘要。

命令由受信代码根据经过校验的结构化配置生成，不能将上传文件内容拼接进 shell。默认不启用模型 trust_remote_code；确需支持某个自定义架构时，单独审查和固定版本。

### 8.4 作业状态与训练包

queued → validating → running → succeeded / failed / cancelled / interrupted。

- 每个作业有独立目录、进度、脱敏日志、心跳和错误摘要。
- 重启发现 running 且无 worker 的任务标 interrupted；不自动启动第二个进程。
- 取消应停止子进程并回收资源，保留可识别的中间 checkpoint。
- 恢复训练验证数据集、底座、配置和 checkpoint 相容，失败时不能悄悄从头覆盖。
- 不要求第一版提供 GPU 云调度。Mac 可导出训练包，用户在受支持 GPU 环境运行同一个 worker，再导入产物。
- 远程训练包包含所选私有训练数据；UI 在导出前显示具体包含内容。它不包含 QQ 凭证。
- 默认不自动上传训练包或权重。

### 8.5 模型产物与服务

产物至少包含 adapter 权重、PEFT 配置、ModelManifest、训练报告和评测引用。Manifest 记录底座 revision、tokenizer/template、数据集哈希、关系范围、许可说明、依赖与代码版本。

实现一个训练模型的推理入口，能用固定底座重新加载 adapter 并由 ModelProvider 调用。可与训练机同机部署，Mac 通过受认证的模型端点请求；不能仅给一个权重路径就认为完成上线。

发布顺序：产物校验 → 加载测试 → 离线评测 → 网页试聊 → 绑定部署版本 → 明确启用。失败回到上一 ModelDeployment。切换部署版本使旧 Candidate 失效。上下文、关系范围与 adapter 范围不相容时拒绝绑定。

**完成训练的证明：**真实参数发生更新；保存后新进程加载成功；用相同 prompt 做基座/adapter 对照；报告运行环境、数据版本、loss 与输出。仅 loss 下降不是聊天质量通过的依据。

## 9. 对话引擎与消息渠道

### 9.1 接收流水线

接收事件 → 验证账号/绑定及联系人范围 → 去重 → 分类来源 → 更新上下文 → 判断模式 → 合并短消息 → 检索风格/记忆 → 调模型 → 校验 Candidate → outbox 最终发送检查。

未选中的联系人不进入本项目的正文持久化、模型和检索。QQ 客户端可能仍接收其他会话，不能把应用过滤描述为平台客户端完全不可见。

初始建议 3 秒无新内容后处理，最大合并窗口 8 秒；参数可调。首版每批生成一条文本，限流和长度上限独立于提示词。新消息只更新 context_seq 并作废旧 AI 候选，不作废正在发送的模式通知。

### 9.2 QQ 实现边界

OneBotAdapter 先实现正向 WebSocket：核心连接用户已启动的桥接端，复用连接接收事件、调用 API 并关联请求响应。若实际选择反向连接，须形成 ADR、替换相关契约测试；不要首期双方向重复建设。

在连接后验证实际登录身份，再启用 Binding。会话使用稳定 ID，不以昵称搜索结果直接发送。普通文字按文本消息段发送，禁止把模型输出解释成 CQ 代码或平台命令。

NapCat 当前文档列出私聊和自身发言事件，但不支持其他客户端在线状态变化；iPhone 人工发言是否及时上报需要实机验证。[S16] 所以基础接管始终通过手动控制；不能把“手机亮屏/打开 QQ”当作已验证控制能力。

### 9.3 人工消息识别

自己发出的 AI 与通知都先登记 outbox，收到平台 echo 后做关联。覆盖 echo 先到、API 回执后到、相同文本连发、断连重放及消息 ID 缺失。

仅靠内容相同或“消息来自我的账号”不能准确判断来源。不能关联的自身消息先停止 AI；只有证据足够确认来自本人时，才按本人接管事件处理并发送接管通知。歧义状态显示“来源待确认”，不能误报真人上线。

## 10. 模式切换与两条固定通知

### 10.1 用户界面

主控制只呈现“开启 AI”和“本人接管”。当前状态用完整文字显示：本人模式、正在通知、AI 模式、正在接管、AI 已停止但通知待确认、故障暂停。开发用 shadow/draft 放在测试设置，不要求普通用户理解四套运行模式。

默认文本严格为：

- 开启通知：**对方已切换为ai模式**
- 本人接管通知：**本人已接管**

发送来源是原账号，发送目标是当前绑定的原私聊。通知 origin=mode_notice，记录 transition_id；不进入风格、训练标签或事实记忆。开源版可允许用户在设置中改文案，但变更有版本，并在启用前预览；首个验收使用上述原句。

### 10.2 内部状态

HUMAN、ENABLING、AI_ACTIVE、PAUSED。接管通知是否待发送是 transition/outbox 状态，不要求 AI 继续活动等待通知。

~~~mermaid
stateDiagram-v2
    [*] --> HUMAN
    HUMAN --> ENABLING: 本人开启
    PAUSED --> ENABLING: 本人重新开启
    ENABLING --> AI_ACTIVE: 通知已确认且版本仍有效
    ENABLING --> HUMAN: 本人取消或接管
    ENABLING --> PAUSED: 通知失败或结果未知
    AI_ACTIVE --> HUMAN: 本人接管
    AI_ACTIVE --> PAUSED: 故障或对方停用
    PAUSED --> HUMAN: 本人接管
~~~

“通知已确认”指平台接口明确成功，或通过可靠查询确认了相应消息；不等于对方已阅读。若没有确认能力，只能保持待确认，不能靠超时猜成功。

### 10.3 开启 AI 的严格顺序

1. 接收本人认证操作，校验 Binding、渠道健康、模型配置和未解决发送。上一轮必要通知尚处于 planned/submitting/unknown 时，不得用新 epoch 静默丢弃；先完成或可靠解决原 transition，再创建新托管会话。
2. 在数据库事务中记录 command_id、transition_id，增加 control_epoch，设 ENABLING，并创建唯一 enable_notice outbox。
3. 通知走同一账号发送器。发送前重新校验 transition 仍有效；新入站消息只缓冲，不提前回复。
4. 通知确认后，用 control_epoch 条件更新为 AI_ACTIVE；接管或取消已经改变版本则不能激活。
5. 只处理本次开启后收到、仍然新鲜的消息。不把旧未读、导入历史或故障前积压自动补发。
6. 明确失败则 PAUSED；结果未知则 PAUSED + 待核对。不得自动发送第二条开机通知来试运气。

### 10.4 本人接管的严格顺序

1. 在同一数据库事务中完成 command_id 去重、HUMAN 状态、control_epoch 递增、未提交候选/队列取消，以及接管 transition 和唯一 takeover_notice 的创建。事务记录停止意图并阻断新候选；发送协调器完成停止屏障后 API 才报告“AI 已停止”。记录通知意图不等于已经发送，停止确认不依赖通知成功。
2. 取消生成任务，释放等待中的合并窗口。
3. outbox 随后处理已创建的 takeover_notice，发送“本人已接管”；重复请求返回原 transition 和通知状态，不新增也不丢弃待发送记录。
4. 通知失败或未知，仍保持 HUMAN，显示“AI 已停止；通知未确认”，不能恢复 AI。
5. 已经向平台提交的请求可能仍显示在聊天中，无法保证撤回；UI 给出对应请求状态。同一 Binding 若有先前发送结果 unknown，通知链保持待核对；超时分类不证明前一消息不会迟到。可靠确认或排除前一请求后才继续，不能宣称本地队列足以保证平台最终显示顺序。
6. 正处于 ENABLING 时接管：尚未提交的开启通知取消；若开启通知已提交，先停止本地 AI，开启通知未可靠解决前不自动发送相冲突的接管通知。无法核对就显示待确认，旧开启回执永远不能重新激活 AI。该会话待核对不无条件阻断其他会话。

重复点“开启”且已经 AI_ACTIVE，不再通知；重复点接管且已经 HUMAN，不创建新通知，但返回原待发送/待确认通知。新的真正托管会话有新的 session_id。所有 UI 重试使用同一个 command_id 保证幂等。若已可靠识别本人手动发出完全相同的接管句，则关联该人工消息为告知证据，避免再发一遍；对方或引用内容出现相同文本不构成授权控制命令。

### 10.5 故障和对方要求停用

网络断开、预算耗尽、模型失败阈值、无法辨认自身消息、发送结果不确定等进入 PAUSED。好友可用明确配置的停止词关闭当前会话；来信不能开启模式或修改配置。

**故障暂停、预约到期和好友停止不能发送“本人已接管”。** 该句只用于本人实际执行接管，或已验证的本人发言触发。v1 先做好手动开关；定时托管放到 v1.1，届时使用独立的结束文案与时区规则。

重启默认 HUMAN/PAUSED，不能自动恢复 AI_ACTIVE，也不能补发旧候选。启用前需要处理上次 unknown 发送，防止跨托管会话污染。

## 11. Outbox、并发与发送一致性

### 11.1 唯一出口

AI 回复、模式通知及经本人确认的草稿，全部通过 outbox。通知可以越过 HUMAN 状态的普通 AI 阻断，但必须符合其 transition 和 Binding，不能由“通知类型”获得任意发送权限。

同一渠道账号只允许一个实际发送进程：OS 进程锁 + 数据库唯一约束/事务认领；单机实例固定一个数据目录。测试、开发、旧版本实例不得拿到线上账号的第二份活动发送能力。跨主机共享账号同时部署不受 v1 支持，不能用单机锁宣称已解决分布式单写者。

### 11.2 状态与记录

planned → submitting → confirmed / rejected / unknown；planned → cancelled。

保存 outbox_id、binding_id、kind、session_id/transition_id、control_epoch、context_seq（AI 候选需要）、输入事件 ID、内容摘要、平台 ID、创建及提交时间、重试/核对记录。

在真正调用外部发送前落盘 submitting；崩溃恢复时 submitting 转待核对，不直接重试。unknown 优先查询平台历史或等待可靠 echo，无法确认时交给本人处理。

### 11.3 最终发送检查

发送检查按类型分开，避免通知等待 AI_ACTIVE 而永久无法开启：

- 公共检查：实际账号与不可变 Binding 一致、发送进程持锁、唯一认领、目标有效、未重复提交、渠道限流有效、该会话没有阻断发送顺序的 unknown。
- ai_reply：要求 AI_ACTIVE、开启通知已确认，control_epoch/context_seq/模型/风格/记忆版本匹配，候选新鲜且生成预算有效。
- enable_notice：要求 ENABLING 和对应 transition/epoch 有效；不要求 AI_ACTIVE、context_seq 或模型生成预算。
- takeover_notice：要求本人接管 transition 对应 HUMAN 且仍有效；不要求模型可用或生成预算。通知保留渠道限流。

最终有效性检查、写入 submitting、实际向适配器发起传输，必须与模式切换由同一发送协调器排序。不能认领后脱离协调器再异步发起；纯数据库 submitting 不算已经对外发起。适配器须定义可验证的开始传输边界，暂停 barrier 先处理所有尚未越过该边界的发送；验收明确注入“认领后、发起前接管”。

长时间等待回执不占用接管锁；只有已经发起传输的请求列为在途。系统保证接管确认后不再发起此前尚未发起的 AI 请求，不承诺平台对已发起请求即时撤销或端到端 exactly-once。

### 11.4 必测竞争场景

开启通知慢回执时接管、接管时模型返回、认领后发起传输前接管、旧手机页面接管、通知 echo 先于 API 回执、新消息到达而通知还在等待、两个控制端同时开关、生成期间更换档案/联系人绑定、进程提交后崩溃、重启重放、两个进程争用账号、API 超时但对方实际上收到、迟到旧回执、模型切换与发送交错。

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

## 13. 数据隐私、应用安全与运行维护

本地原始数据、数据库、索引、训练集和模型使用独立数据目录，不放在源码仓库内。API 模型会收到被选择的上下文；界面准确显示“使用远端模型”，不能仅因服务部署在 Mac 就宣称数据完全不离开本机。

- 控制接口需要本人认证；凭证不进入前端静态包、日志或 Git。
- 启用手机访问时验证 origin、CSRF、会话过期、WebSocket/SSE 鉴权及操作限流。
- OneBot 的 WS/token、模型 API key 与控制页登录凭证分开保存。
- 日志默认不含私聊正文；调试正文日志限时、可关闭，并提示其位置。
- 导入 HTML/Markdown 当文本处理，UI 禁止未经清理的 HTML 注入。
- 限制上传体积、单行长度、对象深度、附件路径；不自动展开未知压缩包或读取任意绝对路径。
- 备份使用 SQLite 一致性备份流程，连同配置/manifest/必要文件；不能只复制一个仍在写入的 db 文件。
- 备份可包含私密数据，默认仅本地；恢复前预览版本和目标，先停发送器。
- 删除提供影响预览：原始文件、派生数据、索引、数据集、模型和备份分别列出。已有远端模型请求及用户另存文件不声称自动撤回。
- 健康检查包含桥、模型、数据库、磁盘、作业和账号；故障恢复后不自动重启托管。
- Mac 常驻需记录登录会话、休眠、断网、唤醒与电源状态的实测，不能把“屏幕关闭”视为“机器一直可用”。
- Windows/Linux 的核心兼容通过 CI 与安装演练后再列为 supported；QQ 渠道及 GPU 训练分别列环境矩阵。

本项目不增加企业审批平台。对日常实现、测试和修复，Codex 按既定任务直接推进；真实账号操作和实际消息测试沿用用户在实施会话中的具体授权，不从示例文档推导任意外发权限。

## 14. 评测方案与发布验收

### 14.1 三种证据必须分开

1. **工程测试：**控制、导入、隔离、训练及故障机制是否正确。
2. **对话评测：**像不像本人、事实是否有依据、上下文是否自然。
3. **实机验证：**目标 QQ/手机/电脑组合是否真的收发、共存和接管。

mock 通道通过只能证明业务逻辑；tiny 模型训练通过只能证明训练链路；一次正常对话成功不能证明故障停止可靠。

### 14.2 必过测试组

| 组 | 关键案例 | 发布门槛 |
|---|---|---|
| 导入与身份 | 同名不同人、时间单位、坏行、重复导入、真实重复短句、缺失引用 | 无静默错人/错时；完整错误报告 |
| 范围隔离 | 档案 A/B、联系人 A/B、跨平台未绑定、缓存与全文/向量检索 | 对照数据不越界 |
| 样本与训练 | owner labels、target mask、窗口 split、通知/AI 排除、模型范围 | 自动检查通过 |
| 模式与通知 | 第 10/11 节所有转换和竞争 | 所有控制不变量通过；两句原文匹配 |
| 发送 | 唯一发送器、重放、未知结果、超时后崩溃、旧回执 | 不盲重发、不从暂停恢复托管 |
| 模型服务 | 请求取消、限额、格式错误、加载失败、版本切换回滚 | 可恢复且无旧候选误发 |
| 训练闭环 | tiny smoke + 一次真实底座 LoRA + 新进程加载推理 | 有可复现报告与产物，不接受仅接口占位 |
| UI/认证 | 未登录、CSRF、手机接管、注入正文、训练时仍可接管 | 关键路径通过 |
| 备份与升级 | migration、损坏备份拒绝、恢复、旧版回滚 | 至少一次恢复与回滚演练 |
| 开源安装 | 新环境示例运行、无 GPU 核心安装、依赖与许可清单 | 文档与发行包相符 |

优先约 40 个控制/故障案例，再加入数据和训练必要测试；数量服务于风险覆盖，不写只重复实现的无价值单测。

### 14.3 个性化比较

- B0：基础模型 + 最小人设。
- B1：B0 + 本人风格示例。
- B2：B1 + 范围内记忆。
- B3：LoRA + 与 B2 相同的记忆及上下文。

开发集用于调整，验证集用于选配置，独立最终测试集用于验收。B0–B3 的提示词示例、RAG、摘要和画像也受 split 与回放时间限制，不能把测试答案或未来事件作为“记忆”提前给模型。

最终建议至少 100 个完整场景：35 风格、20 多轮、20 已知/未知事实、10 跨关系隐私、10 本人才能作答/承诺、5 未支持输入与注入。数据不足时报告评测置信度限制，不凑伪造真实样本。

建议目标：风格主观均分 ≥4/5；日常适用场景 ≥90% 被本人评为可发送；定向事实和隔离测试无观察到的严重编造/泄漏。微调不自动晋升默认：B3 若事实、隔离或本人认可度退步，保留 B2。观测样本零缺陷不等于未来零风险。

### 14.4 实机与性能

- 对本人的 Mac + iPhone + QQ 固定版本，验证指定好友原窗口收发。
- 检查开启通知先于 AI、接管立即阻断未提交发送、两端人工发言、自身 echo、断网重连、休眠恢复和重启。
- 手机离开家中 Wi-Fi 后完成一次认证接管，记录连接方式。
- 正常网络、选定模型下建议 P95 从最后一条合并入站到发送接口确认 ≤20 秒；包含合并等待，接口确认不等于已读。记录模型、样本数和异常排除规则。
- 至少 7 天有实际场景覆盖的试运行；流量不足需补定向场景或延长，不能只挂机七天。
- QQ 原会话未验收通过时，发布可称“核心/网页版”，不能标记完整 QQ v1 已完成。

## 15. 开源仓库、开发方法与协作规则

### 15.1 仓库目录规划

| 路径 | 内容 |
|---|---|
| README.md / README.en.md | 产品范围、支持矩阵、快速开始与截图 |
| AGENTS.md / REVIEW.md | coding agent 执行规则与独立评审要点 |
| pyproject.toml / uv.lock | Python 分组依赖与可复现环境 |
| apps/web/ | React 前端及生成的 API 类型 |
| src/chattwin/domain/ | 领域模型与契约 |
| src/chattwin/storage/ | repository、事务和文件索引 |
| src/chattwin/importers/、identity/、datasets/ | 记录导入和训练数据 |
| src/chattwin/personalization/、memory/ | 风格与记忆 |
| src/chattwin/models/、conversation/ | 推理与对话 |
| src/chattwin/control/、outbox/、channels/ | 状态机和实时收发 |
| src/chattwin/api/、cli/、ops/ | 接口、命令与运行工具 |
| training/ | 独立 worker、环境锁定与模型服务 |
| migrations/ | 数据库迁移 |
| schemas/ | 从领域模型生成的规范 schema |
| tests/unit/、integration/、contract/、e2e/ | 分层自动测试 |
| tests/fixtures/synthetic/ | 明确虚构的公开样例 |
| evals/ | 场景规范、匿名评分及报告生成 |
| docs/、docs/adr/、docs/runbooks/ | 规格、决策、安装、数据、训练与恢复 |
| .github/workflows/、ISSUE_TEMPLATE/ | CI、兼容反馈、缺陷与贡献流程 |
| LICENSE / THIRD_PARTY_NOTICES.md / SECURITY.md / CONTRIBUTING.md | 许可、依赖、安全反馈与贡献要求 |

这是逻辑模块规划；Codex 可以按实际文件规模合并小文件，不得为了凑目录生成空实现。

### 15.2 采用附件 SDLC 的方式

采用用户提供的 AI-Native SDLC Playbook 中的 intent → spec → plan → code/tests → review/release → feedback 工件链。[S1] 具体做法：

- 本计划及已采纳 ADR 是规格基准；每个任务写清目标、依赖、修改模块与验收。
- 对关键接口先落可执行契约测试，再让不同 agent 并行实现。
- 每完成一个可运行闭环就保存验证记录，不把所有模块拼到最后才启动。
- 一个独立 reviewer 检查契约、数据范围和消息竞争。
- CI 使用合成数据，无真实聊天或 QQ 凭证；实际兼容报告在私有环境生成，公开脱敏结论。
- 提示词、模型配置、清洗规则变化与代码一样版本化和回归。
- 用户没要求发布时，不自动推送公共仓库或发布包含隐私的模型。

### 15.3 并行方式

契约和数据库第一版稳定后，可以安排三条实现线：

- 数据线：importers、identity、datasets、memory、training。
- 运行线：channels、control、outbox、conversation、故障回放。
- 产品线：API、前端、安装、文档；只通过约定接口访问另外两条线。

共享 schema、迁移编号、锁文件及核心状态机由一个集成负责人串行修改。每个任务独立分支/worktree；合并前跑契约与集成测试。先实现一条实际可用路径，再扩大格式或渠道。

## 16. 里程碑、工期和成本

扩展为开源产品后，上一版 70–110 小时的个人工具估算不再适用。以下为熟悉 Python、前端和基础训练的一名开发者使用 coding agent 的**人工投入估算**，不含等待授权、平台修复、数据取得及 GPU 排队。

| 阶段 | 内容 | 估计工时 | 交付门槛 |
|---|---|---:|---|
| M0 | 上游许可/版本、Mac/QQ 探针、模型/训练预检、范围锁定 | 8–12 | 兼容矩阵、失败备选和 ADR |
| M1 | 工程骨架、契约、SQLite、认证基础、虚构数据闭环 | 20–32 | 无账号/密钥也能运行 demo |
| M2 | 四类导入、身份、风格、记忆、网页试聊、数据集 | 30–46 | v0.1 数据到个性化试聊 |
| M3 | QQ 适配、状态机、两条通知、outbox、手机接管 | 30–50 | v0.2 原会话与故障控制 |
| M4 | LoRA worker、作业、产物注册、推理和对照评测 | 35–60 | v0.3 训练到实际回复闭环 |
| M5 | 完整管理 UI、安装、数据管理、用量、恢复与安全 | 24–40 | 真实新用户安装可用 |
| M6 | 全链路回归、实机灰度、发布文档及开源整理 | 18–25 | v1.0 发布证据齐全 |

合计 **165–265 小时**，增加约 20% 整合余量后，建议预留 **200–320 小时**。每周 15 小时约 14–22 周；每周 35 小时约 6–10 周。里程碑按成果发布，不必等到 v1 才能自己使用。M0 的接入探针应尽早做，避免完成其他模块后才发现原 QQ 目标无法满足。

至少 7 天的试运行是自然时间，可以与文档和修复并行。新上游功能或额外平台不自动加入上述工期。若只能投入原个人版工期，应先交付 v0.2，不能把尚无训练后端的版本称作完整训练平台。

费用分开记录：模型输入/输出调用、embedding、GPU 训练、模型推理主机、存储。按当时供应商官方单价估算，不在计划里假设永远免费的端点或固定 GPU 成本。API 成本先测每轮实际 token，再设月预算与告警。开源代码可自部署，不代表第三方模型和算力免费。

## 17. 可直接执行的 Codex 任务清单

状态初始均为 TODO。每个任务结束更新状态、提交范围、验证命令/结果、未解决限制；没有真实环境就标 BLOCKED/UNVERIFIED，不能标 DONE。

| ID | 阶段 / 任务 | 依赖 | 交付与验收 |
|---|---|---|---|
| T01 | M0 范围与 ADR | 无 | 将本计划关键决策落文档，记录上游许可和排除项 |
| T02 | M0 环境 doctor 与 QQ 探针 | T01 | 记录 OS/芯片/QQ/桥版本；验证受控会话或明确待实机项 |
| T03 | M0 模型/训练预检 | T01 | 固定参考底座、模板、依赖候选与实际硬件；失败说明 |
| T04 | M1 工程与 CI | T01 | Python/Web 基础、锁文件、lint/type/test、合成数据，无凭证运行 |
| T05 | M1 domain/schema | T04 | 第 5 节模型、错误码、版本；规范样例与契约测试 |
| T06 | M1 存储与迁移 | T05 | 表、作用域索引、事务、文件目录，空库升级通过 |
| T07 | M1 FakeChannel/MockProvider/demo | T05,T06 | 虚构数据→CLI 回复、内存中的基础模式转换契约测试，明确无真实发送 |
| T08 | M1 本人认证与 API 外壳 | T05,T06 | 认证、状态接口、OpenAPI；未登录不可操作 |
| T09 | M2 QCE importer | T05,T06 | 版本明确 fixture、解析/重复/坏行/覆盖报告 |
| T10 | M2 ChatLab importer | T05,T06 | JSON/JSONL、秒级时间、null、未知类型及引用 |
| T11 | M2 CSV 与规范 JSONL | T05,T06 | 字段映射预览、时区、身份选择、可回读导出 |
| T12 | M2 身份与关系绑定 | T05,T06；集成选 T10 或 T11 | 同名不合并、导出者与训练本人区分、隔离测试；QCE 专项待 T09 后补 |
| T13 | M2 数据集构建 | T12 | 过滤、目标身份确认、会话 split、manifest、target mask；包含导出者不是训练目标用例 |
| T14 | M2 风格与记忆 | T12 | 有出处、确认/纠正/删除、关系内检索、版本化 |
| T15 | M2 HTTP 模型与对话引擎 | T07,T14 | 实际 API + 预算、取消、上下文/检索、B0/B1/B2 对照 |
| T16 | M2 导入与试聊 UI | T08,T12,T14,T15 | 用户走完导入→预览→试聊；v0.1 完整格式发布还需 T09–T11 验收 |
| T17 | M3 状态机与通知 | T05,T06,T07 | 精确文案、幂等切换、失败/未知/取消/重启测试 |
| T18 | M3 Outbox 与单写者 | T06,T17 | 事务认领、submitting 恢复、最终 gate、进程争锁 |
| T19 | M3 OneBot 适配 | T02,T05,T18 | 身份检查、事件/echo/回执；fake 协议契约 + 实机证据 |
| T20 | M3 接管与移动 UI | T08,T15,T17,T18,T19 | 本人接管先停、两条通知、当前会话绑定，发布 v0.2 |
| T21 | M4 LoRA worker | T03,T13 | 真实训练、取消/中断、配置验证、独立环境 |
| T22 | M4 模型产物与推理 | T21,T15 | manifest、重新加载、作用域检查、端点、切换回滚 |
| T23 | M4 训练管理 UI/训练包 | T08,T13,T21,T22 | 样本/作业/日志/产物可见；无 GPU 路径准确 |
| T24 | M4 训练与基线评测 | T21,T22,T23 | 一次真实底座训练与 B0–B3 对照；发布 v0.3 |
| T25 | M5 数据管理与诊断 | T14,T18,T23 | 删除传播、用量、脱敏诊断、长任务不阻断接管 |
| T26 | M5 安装与手机访问 | T16,T20,T23 | 新环境核心安装、Mac 常驻、手机离网接管 |
| T27 | M5 备份/恢复/回滚 | T06,T18,T22,T25 | 一致性备份、迁移故障恢复、旧模型/旧版本回滚 |
| T28 | M6 独立验收与试运行 | T24,T25,T26,T27 | 控制测试、100 场景目标、真实 ≥7 天记录 |
| T29 | M6 开源发布准备 | T28 | README/贡献/许可证/SBOM/兼容矩阵/示例，清除私密数据 |
| T30 | M6 发布候选审查 | T29 | 全部支持声明有证据；完成 v1.0 或精确列剩余阻塞 |

T02 受账号环境阻塞时，T04–T18 及数据/训练线仍可推进。T09 缺 QCE 样本不阻止通过 ChatLab/CSV/规范格式推进身份、数据集、风格与训练；仅 QCE 支持声明及完整 v0.1 格式验收等待 T09。T21 缺 GPU 时先完成 worker 和 tiny smoke，但 T24 不得提前通过。外部许可未明确时不捆绑对应程序、不把该渠道标正式支持。

## 18. 给 Codex 的开工指令与完成标准

### 18.1 开工指令

将配套文档包放进准备开发的空目录或目标仓库后，把下面任务交给 Codex：

~~~text
请把本目录的 ChatTwin 开发计划落地为可运行开源项目。

先读 README.md、AGENTS.md、DEVELOPMENT_PLAN.md 和 docs/tasks.md。
以计划 v2 的产品范围、模式通知、数据隔离和训练验收为基准。
按 T01–T30 的依赖执行；从 M0/M1 开始形成可运行闭环，再推进后续里程碑。
不要只生成空接口、目录或 TODO 就宣布完成。
先完成无 QQ 凭证也可运行的虚构数据 demo、核心契约和测试；
同时尽早验证 QQ 原会话接入可行性，缺实机时保留明确待验证项。
用户入口保持简单：开启 AI 发送“对方已切换为ai模式”；
本人接管先阻断 AI，再发送“本人已接管”。
导入微信记录与微信实时渠道分别实现和声明。
v1 必须有可执行 LoRA worker、产物重新加载、真实推理和对照评测。
不要把真实聊天、密钥或私有权重加入 Git，不自动发布公共仓库。
遇到账号/GPU/许可阻塞，完成其他可做任务，给出具体所需输入和验证步骤。
每个里程碑报告：已实现、验证证据、剩余限制、下一批任务。
~~~

这段指令不授权向任意真实联系人发消息；实际测试会话与既有授权在开发会话中确定。常规实现和本地测试不需要反复请求确认。

### 18.2 首个可 review 提交

必须包含工程启动方式、领域契约、第一版迁移、合成 fixture、MockProvider/FakeChannel、最小 demo、状态机关键测试和任务状态；不是只提交一份 README。

后续提交保持可运行，每个任务关联代码与验证；重大偏离写 ADR。维护统一契约时相应更新测试、前端生成类型和文档，不能让 Codex 在不同模块各自发明字段。

### 18.3 v1 完成交付清单

- 可自部署的源码、依赖锁定和明确许可证。
- QQ/微信已导出记录的支持格式、样例与导入报告。
- 身份映射、风格与记忆管理、网页试聊。
- 可执行 LoRA 数据/训练/产物/服务闭环及对照报告。
- 现有 QQ 原私聊接入、两条通知、可靠接管和故障暂停。
- 手机控制、用量及诊断、备份恢复、升级回滚。
- 新用户安装指南、训练指南、渠道指南、贡献及故障反馈模板。
- 公开合成测试、私有实机验证的脱敏结论、实际支持矩阵和已知限制。
- 至少 7 天有效试运行与问题回归记录。

本计划交付的是上述工作的完整设计和执行拆分；当前未安装 QQ 桥、未读取真实私聊、未训练模型、未向任何人发送消息，也未创建或发布 GitHub 仓库。

## 19. 参考资料与证据边界

上游事实以 2026-10-26 的官方仓库/文档为依据。架构、顺序、工期和验收阈值是本计划的设计建议。

- **[S1]** 用户提供的 *The AI-Native SDLC Playbook*，Louis Claxton，54 页；重点 p7–9 工件依赖、p11–17 intent/spec、p19–29 实施、p31–35 测试/eval、p37–46 发布、p48–51 维护。依据前一轮全文审阅。
- **[S2]** [QCE 仓库](https://github.com/shuakami/qq-chat-exporter)；[导出说明](https://shuakami.github.io/qq-chat-exporter/docs/guide.html)。
- **[S3]** [ChatLab v0.0.2 交换格式](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/standard/chatlab-format.md)。
- **[S4]** [ChatLab LICENSE](https://github.com/ChatLab/ChatLab/blob/main/LICENSE)；[导出使用边界](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/usage/how-to-export.md)。
- **[S5]** [WeFlow](https://github.com/hicccc77/WeFlow)；[第三方组件说明](https://github.com/hicccc77/WeFlow/blob/main/docs/third-party-components.md)；[LICENSE](https://github.com/hicccc77/WeFlow/blob/main/LICENSE)。
- **[S6]** [WeClone](https://github.com/xming521/WeClone)；[训练入口](https://github.com/xming521/WeClone/blob/master/weclone/train/train_sft.py)。
- **[S7]** [NapCatQQ](https://github.com/NapNeko/NapCatQQ)；[当前 LICENSE](https://github.com/NapNeko/NapCatQQ/blob/main/LICENSE)。
- **[S8]** [NapCat Mac Installer](https://github.com/NapNeko/NapCat-Mac-Installer)。
- **[S9]** [Tencent/openclaw-weixin](https://github.com/Tencent/openclaw-weixin)；[协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)；[腾讯云微信 ClawBot 对话流程](https://cloud.tencent.com/document/product/1291/129132)。
- **[S10]** [AstrBot](https://github.com/AstrBotDevs/AstrBot)；[MaiBot](https://github.com/Mai-with-u/MaiBot)。
- **[S11]** [chatlog 项目移除通知](https://github.com/sjzar/chatlog)。
- **[S12]** [WeChatMsg 当前说明](https://github.com/LC044/WeChatMsg)。
- **[S13]** [Qwen3-4B-Instruct-2507 官方模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)。
- **[S14]** [Apache License 2.0 正文](https://www.apache.org/licenses/LICENSE-2.0)。
- **[S15]** [Hugging Face PEFT](https://huggingface.co/docs/peft/main/en/index)；实现时切换到已锁定的稳定版本文档。
- **[S16]** [NapCat 事件兼容表](https://napneko.github.io/develop/event)。

本计划引用资料用于核实能力、接口和限制；没有复制上游实现代码。历史示例与计划中的类型名称不构成任何第三方程序的再许可。

