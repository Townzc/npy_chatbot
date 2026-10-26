# ADR 0001 — 本地单体、可验证演示和外部能力边界

采纳 DEVELOPMENT_PLAN.md v2。Python 3.12/FastAPI/Pydantic、SQLite/SQLAlchemy/Alembic、React/TS/Vite。核心不安装 GPU 依赖；训练独立环境。私有数据默认位于源码树外，现有 chat_record 仅为用户输入，永不进入 Git。

原始 sender_id 不变；本人身份是 Persona 下明确确认的映射。关系专用检索、数据集及 adapter。模型只能生成 Candidate，唯一 outbox 发送器决定地址与模式。正向 OneBot WebSocket；不捆绑或安装 NapCat。上游证据见 preflight.md。

无外部条件也先完成真实本地闭环，FakeChannel/MockProvider 始终标注合成演示。QQ 实机、生产底座 GPU LoRA、7 日试运行分别验收，不能由 mock/tiny 代替。

用户的草稿优先偏好适用于开发会话：不替用户向真实联系人发送消息。实现产品的自动回复能力不代表获得账号实测授权。此轮不 push、不创建 release。

首个实现采用明确模块所有权在共享工作目录并行；集成负责人独占 schema、迁移、锁文件和状态机。工程完成后统一验证。这是对计划 worktree 建议的执行调整，避免新仓库无基线时交叉修改。
