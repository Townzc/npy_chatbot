# open-source-and-ops.md

本文件是完整计划的按主题阅读副本。规范以 [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 为准；来源见 [sources.md](sources.md)。修改计划时使用随包脚本重新生成这些副本。

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
