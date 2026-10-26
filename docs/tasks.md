# 实施状态 — 2026-10-26

规格来源：[DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md)，原始计划包保持原样。这里记录实现，不重写规格。DONE 表示所列当前任务门槛有本地证据；PARTIAL 表示有实现但缺部分验收；BLOCKED 表示等待具体外部输入；TODO 仍待实施。工程测试、真实本地训练、真实 QQ 分开计。

| 任务 | 状态 | 实现/验证 | 限制及后续 |
|---|---|---|---|
| T01 范围/ADR | DONE | docs/adr/0001-local-core.md、THIRD_PARTY_NOTICES.md | 无公共发布授权，不捆绑桥 |
| T02 doctor/QQ探针 | PARTIAL / 实机 BLOCKED | CLI doctor、qq probe；docs/preflight.md；test_onebot.py | 无已运行桥/指定实测会话；未真实发送 |
| T03 训练预检 | DONE（预检） | TrainingSpec 固定 Qwen revision/template/lock；tokenizer 实测 | Linux/CUDA 候选组合仍未测，预检不等于训练 |
| T04 工程/CI | DONE（本地） | uv.lock、pnpm-lock、lint/type/test、生产构建、CI配置 | GitHub Actions 尚未推送执行；跨系统未承诺 |
| T05 领域契约 | PARTIAL | domain、schemas、OpenAPI、生成 TS，核心消息/发送契约已测 | 完整 ModelDeployment/来源附件等扩展契约仍需增补 |
| T06 存储迁移 | DONE（首版） | SQLAlchemy/Alembic 0001冻结快照、FK/唯一键/范围索引；重复升级测试 | 后续训练注册等表按新迁移演进，不改0001 |
| T07 无密钥demo | DONE | `uv run chattwin demo`；FakeChannel/MockProvider；模式单测 | 明确为虚构工程演示，无真实模型效果声明 |
| T08 本人认证/API | DONE（本地门槛） | Bearer、Origin/Host、上传限制；test_api.py | 远程会话过期/限流/手机访问由T26补齐 |
| T09 QCE | BLOCKED | 未伪造兼容解析器；chat_record格式元数据检查 | 需要版本明确的真实脱敏QCE导出 |
| T10 ChatLab | DONE（格式工程） | JSON/JSONL秒级时间、null/未知/坏行/引用；test_data.py | 实际导出兼容仍待样本，不宣称任意微信提取 |
| T11 CSV/规范JSONL | PARTIAL | CSV映射/时区/10万条；JSONL回读；unknown/group隔离 | 通用sidecar manifest读入和更多日期歧义仍需补全 |
| T12 身份/关系 | PARTIAL | Persona独立映射、同名不合并、导出者非目标、core scope guard | 完整跨平台关联/重新映射UI未完成 |
| T13 数据集 | DONE（合成工程） | 片段先split、回复/近重复聚类、冻结hash、mask真实tokenizer测试 | 少数据训练集无有效测试集时明确低可信；真实质量待T24 |
| T14 风格/记忆 | PARTIAL | 可追溯风格草稿、确认/删除关系记忆、时间/held-out过滤 | 画像编辑确认UI、记忆纠正UI、完整删除传播未完成 |
| T15 HTTP/引擎 | PARTIAL | 实际HTTP代码、取消/请求预算、B0/B1/B2、范围metadata | 无供应商付费API实测；月费用预算/对话质量待补 |
| T16 导入试聊UI | PARTIAL | 浏览器完成新建→预览→确认导入→记忆→试聊→接管 | 完整v0.1格式发布受T09等限制 |
| T17 模式通知 | PARTIAL | 精确文案、幂等、旧页面接管、迟到失败、重启等回归 | 尚非计划全体40类故障覆盖，实机通知未测 |
| T18 唯一outbox | PARTIAL | 事务意图、transport-start屏障、跨数据目录真实账号锁、unknown不重发 | 人工可靠核对/完整echo恢复仍缺；跨主机不支持 |
| T19 OneBot | PARTIAL / 实机 BLOCKED | 真WS客户端、账号验证、文本段、事件过滤/合并/回执；本地协议测试 | 真实桥未安装，echo先到会保守暂停；不能标QQ可用 |
| T20 移动接管UI | PARTIAL | 窄屏固定接管、通知状态、并发控制，浏览器验证 | 真手机/QQ/离网未验收，无v0.2发布 |
| T21 LoRA worker | PARTIAL | 真实AdamW/PEFT、cancel/interrupted、独立环境；12训练测试 | tiny CPU通过；正式CUDA配置未验证，无优化器断点恢复 |
| T22 产物/推理 | PARTIAL | hash/scope manifest、新进程重载、认证推理端点及403隔离 | 完整注册/版本切换/回滚尚待实现 |
| T23 训练管理 | PARTIAL | 网页数据集报告、训练包准备CLI、job status文件 | 完整异步jobs API/训练管理UI未完成 |
| T24 正式训练评测 | BLOCKED | tiny真实更新和对照有报告，绝不代替本任务 | 需Linux/CUDA、确认的训练数据、Qwen权重、独立B0–B3评测 |
| T25 数据/诊断 | PARTIAL | 私有目录、用量记录、记忆删除、长导入不阻断接管 | 来源删除影响预览、adapter失效链、完整诊断未完成 |
| T26 安装/手机 | PARTIAL | 锁文件、构建/启动脚本、loopback鉴权、核心安装验证 | Mac常驻/休眠、私网TLS、手机离网控制未验证 |
| T27 备份恢复 | PARTIAL | SQLite/WAL一致快照、引用数据集、校验与空目录恢复；7测试 | 权重/原文件/凭证明确排除；旧应用/模型版本回滚待实现 |
| T28 独立验收 | PARTIAL / 试运行 BLOCKED | 独立review修复并保留6项竞态回归 | 100场景人工质量与真实≥7天证据尚无 |
| T29 发布准备 | PARTIAL | README/贡献/许可证/边界/锁文件/合成样例/隐私检查 | SBOM/跨平台安装/完整支持矩阵发布审查待前置任务 |
| T30 RC审查 | TODO | 本状态表明确不能声称v1完成 | 依赖T24–T29，不创建release、不自动推送 |

下一批优先：补齐持久 jobs 与训练UI→模型注册/切换/回滚→来源删除传播；并行拿到可解析真实导出和用户自行配置的QQ桥，建立真实QQ证据；再做Qwen CUDA/B0–B3、手机私网接管、恢复回滚与7日试运行。当前已提供的命令与测试保持可运行，不以空接口占位。
