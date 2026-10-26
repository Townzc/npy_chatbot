# ChatTwin · Codex 开发计划包 v2

**这是规格与开工材料，不是已经实现的软件。** 日期：2026-10-26。

目标：从 QQ/微信已导出的聊天记录建立个人 AI，提供网页试聊、真实可选 LoRA 微调，并首先实现 QQ 原有个人私聊中的 AI/本人切换。

## 给使用者

1. 将本目录放进准备开发的空目录，或作为已有仓库的规格材料。
2. 让 Codex 阅读 [CODEX_START.md](CODEX_START.md)。
3. 核对每个里程碑的实现和证据；没有真实账号/GPU测试时，不把相应能力标成完成。
4. 所有随包聊天示例均为虚构，不能被当作真实导出兼容证据或聊天效果评测数据。

## 阅读顺序

- [完整开发计划](DEVELOPMENT_PLAN.md)：权威规格，20 个章节。
- [AGENTS.md](AGENTS.md)：执行规则。
- [模块架构](docs/architecture.md)、[数据契约](docs/contracts.md)。
- [导入与训练](docs/data-and-training.md)、[状态与通知](docs/runtime-and-modes.md)。
- [30 项任务](docs/tasks.md)、[阶段计划](docs/roadmap.md)。
- [验收场景](docs/acceptance-checklist.md)、[评测方案](docs/evaluation.md)。
- [开源与运行](docs/open-source-and-ops.md)、[一手来源](docs/sources.md)。
- [示例说明](examples/README.md)。

## 明确的默认行为

开启时固定发送“对方已切换为ai模式”，确认后才放行 AI。
本人接管先停止 AI，再固定发送“本人已接管”。
正常开关不需要额外的对方确认或逐条回复批准。
生成模型不直接发送消息，不决定收件人。

## 包内与实际项目的区别

包内提供计划、任务、虚构 JSON/JSONL/CSV 示例和文档同步脚本；没有 QQ 凭证、真实聊天、模型权重或第三方桥程序。
计划中的 CLI/API/页面名称是待实现契约。
T01–T30 全部初始为 TODO；运行软件需由 Codex 实施后产生。

## 后续更新

DEVELOPMENT_PLAN.md 是规格唯一来源。docs 中的阅读副本由 scripts/sync_plan_docs.py 生成。
进入实现后，在工作仓库记录任务状态和 ADR；不能只更新副本却遗留主规格。
