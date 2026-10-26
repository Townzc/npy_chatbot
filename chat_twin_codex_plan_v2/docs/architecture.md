# architecture.md

本文件是完整计划的按主题阅读副本。规范以 [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 为准；来源见 [sources.md](sources.md)。修改计划时使用随包脚本重新生成这些副本。

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
