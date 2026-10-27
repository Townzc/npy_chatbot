# 实施状态 — 2026-10-26（第二批）

以 DEVELOPMENT_PLAN.md 与原始计划包为规格。DONE 只表示括号内已验收范围；PARTIAL 表示已有功能但仍有验收缺口；BLOCKED 只用于具体外部条件。没有将工程协议测试、tiny 训练或窄屏浏览器当成真实 QQ、Qwen 质量或手机实测。

| 任务 | 状态 | 本地交付与证据 | 剩余限制/输入 |
|---|---|---|---|
| T01 范围/ADR | DONE | ADR、模块边界、上游许可记录 | 用户后续授权源码推送；未授权发布 release/模型或代发私聊 |
| T02 doctor/QQ探针 | PARTIAL；实机 BLOCKED | doctor、只读身份/版本/status探针、preflight | 无可连接桥、账号/指定会话配置；未真实发送 |
| T03 训练预检 | DONE（预检） | 固定 Qwen revision/template/依赖、实际 tokenizer；逐卡显存API/CLI、4090单卡2步配置、安装前主存/cgroup/磁盘/驱动检查 | 用户拟租AutoDL，首轮1张4090；待SSH及实际显存dry run |
| T04 工程/CI | DONE（本地）；CI BLOCKED | 两套Python锁、前端锁、lint/type/test/build/wheel | GitHub OAuth缺workflow权限；CI保留为ci/模板，未远程运行 |
| T05 领域契约 | PARTIAL | 消息/控制/产物/部署/作业/短会话/预算OpenAPI和生成TS | 未承诺所有附件类型；保持不支持类型显式表示 |
| T06 存储迁移 | DONE（当前） | 冻结0001、增量0002部署表；旧备份升级测试 | 新版向旧版不破坏性降级 |
| T07 无密钥demo | DONE | CLI及真实浏览器→API→SQLite→FakeChannel | 明确虚构；没有个人模型效果声明 |
| T08 本人认证/API | DONE（本地工程） | Bearer/Host/严格同源、上传限制、短会话/退出/到期/重启失效 | 手机严格session配置待真实TLS设备验收 |
| T09 QCE | PARTIAL；真实导出待启动确认 | 按v6.3.2固定源码独立实现单JSON；7测试及网页→数据集通过；备份只读识别；官方Mac包本地校验通过、配置草案已准备 | 用户确认当前Mac的QQ可见所需历史；待确认QQ副本沙箱变化及共享数据库再启动；.bak为ZIP内4个MSG0未解密；尚无真实导出；分块JSONL不支持 |
| T10 ChatLab | DONE（格式工程） | v0.0.2 JSON/JSONL、秒级时间/null/未知/引用/重复 | 用户实际导出兼容仍需样本 |
| T11 CSV/规范JSONL | DONE（格式工程） | CSV映射/时区/10万条；sidecar哈希/行数/范围/会话类型；回读 | CSV默认unknown，明确私聊才训练；QCE不混同 |
| T12 身份/关系 | DONE（本地工程） | 稳定ID映射、检查/显式重映射、同名不合并、跨关系隔离 | 真实跨平台导出兼容仍待数据 |
| T13 数据集 | DONE（合成工程） | 完整片段split、去重、目标mask、冻结hash、预览、撤销 | 小数据0验证/测试明确低可信，不能作质量验收 |
| T14 风格/记忆 | DONE（本地工程） | 草稿/批准不可变版本、记忆编辑纠正/失效/出处、heldout与时间过滤 | 画像质量需本人认可；删除不等于权重遗忘 |
| T15 HTTP/引擎 | DONE（本地工程） | 真HTTP路径、多轮已确认上下文、取消、月预留账目、B0–B3快速试聊 | 正式同pin对照走evaluation；无供应商付费实测，USD为配置价估算 |
| T16 导入试聊UI | DONE（已支持格式） | 新档案→预览→确认类型/身份→导入→画像/记忆→试聊浏览器通过 | QCE专项完整v0.1格式门槛未过 |
| T17 模式通知 | DONE（工程）；实机 BLOCKED | 精确通知、命令幂等、旧页面接管、迟到回执、重启/失败竞态回归 | QQ原会话通知顺序仍待实机 |
| T18 唯一outbox | DONE（工程）；实机 BLOCKED | 最终发送屏障、账号锁、unknown只读/人工审计、不重发、冲突重开unknown | 人工证据为本人声明；真实平台核对能力未验证 |
| T19 OneBot | PARTIAL；实机 BLOCKED | 真WS客户端、身份核验、选定私聊过滤、防回放/合并、文本段、回执 | 无真实桥；自身echo先到会保守暂停；手机本人发言识别未验收 |
| T20 移动接管UI | DONE（浏览器工程） | 390×844无横溢、固定接管、通知/unknown状态 | 真手机蜂窝网与QQ未测；不宣称v0.2已验收 |
| T21 LoRA worker | PARTIAL | 真AdamW/PEFT更新/保存/新进程重载；源码/数据/依赖pin；取消/中断；非重入梯度检查点与峰值显存报告 | 16项训练/硬件契约测试；仍需正式Qwen Linux/CUDA训练；无多卡或优化器续训 |
| T22 产物/推理 | DONE（本地工程） | artifact校验/网页真实登记、认证base+adapter推理、scope/模型hash、部署切换/回滚；输出按剩余序列预算限长，空回复明确拒绝 | tiny文本探针仍为空，网页有效LoRA试聊成功路径未过；Qwen部署与质量未验收 |
| T23 训练管理 | DONE（本地工程） | SQLite持久队列/心跳/取消/锁/日志、网页、GPU预检、独立训练包 | 真tiny作业和wheel导出已测；Mac正式任务明确CUDA失败 |
| T24 正式训练评测 | PARTIAL；GPU/数据 BLOCKED | 真HTTP B0–B3 runner、版本验证、未来/heldout隔离、blind/score工具 | 缺Qwen CUDA训练、足量确认数据和独立人工质量评分；不发v0.3 |
| T25 数据/诊断 | DONE（本地工程） | 删除影响hash确认、训练/模型/部署/评测撤销、文件清理回滚、预算、脱敏诊断 | 已发HTTP不能撤回；删除等待源租约完成，接管不等网络；旧备份/权重需另处理 |
| T26 安装/手机 | PARTIAL | 隔离wheel安装实测、短会话、launchd生成+plutil通过、私网TLS操作文档 | 未安装登录项；休眠/唤醒/真手机离网未测 |
| T27 备份/恢复/回滚 | DONE（本地工程） | 一致快照、UI下载、0001→0002升级、独立旧应用+升级前备份实际回滚、撤销源不复活、模型指针回滚 | 权重/原文件/凭证排除；实际私人模型重部署仍需环境 |
| T28 独立验收 | PARTIAL；试运行 BLOCKED | 多代理独立审查与竞态修复；125核心测试、13训练测试、浏览器证据 | 未满100完整人工质量场景、真实≥7天和手机/QQ组合 |
| T29 发布准备 | PARTIAL | README/贡献/许可证/隐私扫描、225组件锁清单SBOM、合成样例与证据 | 各组件完整许可/漏洞复审、Linux安装矩阵及T28仍缺 |
| T30 RC审查 | PARTIAL；v1 BLOCKED | release-readiness明确每项支持声明/限制 | 只推送源码；不创建release、不称T01–T30全部完成 |

最终本地检查：`uv run pytest -q` 125 passed / 1 skipped（未安装可选torch的核心环境跳过runtime训练）；独立training环境13 passed；Ruff、mypy、生产构建通过。详见[第二批报告](evidence/management-milestone-2026-10-26.md)及[浏览器证据](evidence/web-management-2026-10-26.md)。

4090/QQ 接入准备增量：核心 129 passed / 1 skipped，独立训练与硬件契约 16 passed；Ruff 81文件、mypy 60源文件、生产构建及网页预设→实际下载训练包通过。见 [本批证据](evidence/gpu-and-qq-preparation-2026-10-26.md)、[GPU 步骤](gpu-4090.md)、[QQ/QCE 调研与步骤](qq-setup-research.md)。已知GPU资源不等于已连接或完成T24，QCE上游发布包也不等于已验收用户导出。

QCE增量：新增7项QCE和1项系统角色回归后，核心137 passed / 1 skipped；Ruff83文件、mypy61源文件、生产构建通过。网页上传虚构fixture→预览8条/3文本→选择同名稳定UID→2条本人目标→1个连续回复训练窗口通过。发现并修复系统行误标“对方”，导入/重映射现均保持“系统”。详见 [QCE实现与证据](qce-compatibility.md)。真实QQ、真实导出、4090/Qwen与人工质量门槛未因此通过。

AutoDL增量：用户澄清将租卡，首轮1张4090；新增安装前只读主存/cgroup/磁盘/驱动检查，3项契约测试通过，本机无NVIDIA时正确失败。8个文件已确认QQ官方电脑备份，仍需核对电脑可见历史与可读导出。见 [接入证据](evidence/autodl-preparation-2026-10-26.md) 和 [AutoDL操作步骤](autodl.md)；未租机、未连接GPU、未上传真实聊天。

2026-10-27：无需A800，24GB为4090显存；主机RAM可先选32GB小步试跑、64GB为余量建议，最低需求未测。用户确认旧QQ记录仅手机可见；Finder整机备份是否含当前QQ数据库仍待版本与备份核验。模型网页增量完成真实产物登记、tiny证据说明和空回复拒绝，修复短输入因输出上限过大被拒绝；独立训练17项、核心143 passed / 1 skipped、Ruff85文件、mypy61源文件及构建通过。有效Qwen网页试聊仍待GPU，见 [模型网页证据](evidence/model-ui-validation-2026-10-27.md)。

2026-10-27 备份增量：真实电脑QQ导出.bak为ZIP内4个MSG0，归档CRC通过、原件哈希不变；只读类型识别通过不等于已解密聊天。新增`import probe`、归档资源边界、自动/显式格式的422诊断、上传清理和.bak发布防护；21项虚构回归，核心164 passed / 1 skipped，Ruff87文件、mypy62源文件、生产构建与网页诊断通过。见 [本批证据](evidence/qq-bak-inspection-2026-10-27.md)。

2026-10-27 QCE准备增量：用户进一步确认当前Mac的QQ能看到所需旧记录，先前仅手机可见不再作为该范围的当前前提。官方Mac包在仓库外下载、SHA-256与994条目检查通过；本机QQ签名和启动前提核验通过，配置草案未应用。启动器会修改QQ专用副本、移除其沙箱保护并共享真实数据库；HTTP监听所有网卡而不是仅loopback。已就启动变化请求具体确认，未启动/扫码/导出/发送；追加草案关闭默认debug文件日志。见 [本机准备证据](evidence/qce-preparation-2026-10-27.md)。

下一批：用户已确认所需历史在当前Mac，确认启动变化后取得可读单JSON并实测导入与身份/范围；提供Linux/CUDA后先以虚构数据做Qwen显存dry run/真实训练/认证部署，随后足量确认数据与人工B0–B3；提供桥后先只读探针，再由用户自行验证指定原私聊；并行真手机TLS/休眠、实际模型恢复、≥7天试运行和依赖审查。当前内部代码缺口与外部未验收不混写。
