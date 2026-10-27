# T29 锁定依赖检查与模型加载加固 — 2026-10-27

本批只向 OSV、PyPI、npm 查询公开包名/版本，不发送运行目录、聊天、账号或凭证。检查范围为三个锁文件的全部 225 个组件，包含开发依赖和条件平台依赖；不代表它们都随核心 wheel 发布。结果与锁文件 SHA-256 一起保存于 [机器可读报告](dependency-audit-2026-10-27.json)。

## 检查与修复结果

首次 OSV 查询有 5 个包命中公告；更新后为 3 个，仍有未解决项，T29/T30 不标发布通过。

| 包 | 本次处理 | 核验结果与范围 |
|---|---|---|
| Vite 7.1.12 | 更新并锁定 7.3.7，同步前端传递依赖与 SBOM | 更新后 OSV 无命中；生产构建通过，42 模块、JS 280.06 kB / gzip 87.13 kB。实际工作台由 FastAPI 提供静态文件，不运行公开 Vite dev server |
| filelock 3.32.7 | 最低要求升到 4.2.1，核心和训练锁实际解析为 4.2.4 | 更新后 OSV 无命中；核心及独立 tiny 训练回归通过。原公告主要涉及 ReadWriteLock/SoftFileLock 路径，项目直接使用 FileLock；不把未走该路径当作整包免审 |
| transformers 4.57.6 | 保留已验证训练 pin，增加模型配置加载前检查；记录主要版本迁移需求 | OSV 仍命中，不能声称依赖漏洞已清零；具体入口与边界如下 |
| torch 2.9.1 | 记录 `lstm_cell` / `jit.script` 内存问题与 2.10.0/2.13.0 修复版本 | 本项目没有直接调用这些入口；训练栈升级仍需整体验证，不能以源码搜索证明所有传递调用安全 |
| accelerate 1.12.0 | 记录分片 checkpoint 路径遍历/阻塞问题 | OSV 记录未给出 fixed 版本；项目当前不直接调用涉事的 checkpoint dispatch helpers，仍保留待解决状态 |

版本与修复依据：[Vite 官方公告](https://github.com/vitejs/vite/security/advisories/GHSA-rq7h-c2jc-7f22)、[filelock 官方公告](https://github.com/tox-dev/filelock/security/advisories/GHSA-v4x8-3wr5-3wq8)、[Transformers 配置修复](https://github.com/huggingface/transformers/commit/a7f8e7ff37d87d1a1a0c8cf607971c607741452f)、[模板路径修复](https://github.com/huggingface/transformers/commit/eaaaf8494dd5386634ae37d1d122212fdc315be5)、[Accelerate 上游问题](https://github.com/huggingface/accelerate/issues/4067)。全部公告 ID、别名、受影响范围、来源链接在机器报告内；GHSA 与 PYSEC 别名不能重复计作独立漏洞。

## 模型加载前检查

`training/loading.py` 在 AutoTokenizer / AutoModel 构造前读取受大小限制的固定 JSON。内部 attention/expert kernel 选择器、自定义代码映射、custom generation/pipeline 配置均拒绝；拒绝命名 chat-template 字典，只接受固定字符串或固定 `chat_template.jinja` 的匹配哈希。这样不依赖 `trust_remote_code=False` 单独承担已知配置注入的防护。

当前后端只接受已固定的 Qwen 仓库/revision，及带内容 pin、无 Python/custom_generate 文件的本地合成 tiny Qwen3。新仓库、其他架构和自定义代码需要单独实现与审查，不能通过填写一个 SHA 就获得执行许可。worker、产物重载与推理共用此入口；仍保留 safetensors、模板/依赖/源码哈希与关系范围校验。

实际检查固定 Qwen 的 config/tokenizer/template，通过；该固定 revision 的仓库文件列表无 Python 或 custom_generate 文件，列表摘要为 `1e3e6d3af740d0858e24e7bb316ccc8b99a08a1f6f27141729409850f01589b5`。只取得公开配置和元数据，没有下载正式权重或启动 CUDA 训练。

这些检查是当前受限后端的局部防护，不是模型输入沙箱，也没有抹去 OSV 中的剩余公告。正式发布前需升级/核验训练栈，并完成真实 CUDA、产物重载和质量验收。

## 可复现工具与许可库存

```sh
uv run python scripts/export_sbom.py
uv run python scripts/audit_dependencies.py --licenses --output /tmp/chattwin-dependency-audit.json
```

`audit_dependencies.py` 校验三份锁文件与 SBOM 一致，正确跟随 OSV 分页；网络失败、缺失结果、重复分页或陈旧库存都不能返回“无已知问题”。退出 0 表示查询完整且当时未命中；1 表示存在公告；2 表示检查不完整。使用 [OSV 官方 API](https://google.github.io/osv.dev/post-v1-querybatch/)，查询成功也不证明软件安全。

225 个组件均取得对应版本的 PyPI/npm 许可元数据。其中特别保留：12 个 NVIDIA 专有许可声明、MPL/CC-BY 组件，以及 9 个未提供简短许可表达式的记录；有些在 classifiers 或完整许可正文中另有说明。所有 `reviewed_for_redistribution` 仍为 false。这里没有将注册表标签、条件依赖库存或项目 Apache-2.0 许可证等同于再分发许可结论；外部 QQ/QCE 程序和模型权重也不在本次清单内。

## 验证与剩余工作

- 核心全量 191 passed / 1 skipped；独立训练 29 passed，包含真正的 tiny 参数更新、保存、新进程加载与认证推理。
- 新增 6 项审计工具回归，覆盖陈旧锁、分页归属、结果缺失、重复分页及失败输出；新增 12 项训练配置防护回归，其中 3 项通过真实 tiny 文件证明拒绝发生在模型/分词器构造前。
- Ruff 90 文件、mypy 63 源文件与生产构建通过。仅有已知 Starlette 测试客户端弃用警告。
- 私有工作台在新依赖下重新启动；旧登录会话失效，再认证后仍为本人模式、AI 停止，数据快照保留。数据集列表改为新版本在前，避免重新打开网页时默认回到首份旧快照。

剩余：训练栈公告修复和许可证逐项审查、Linux/CUDA 实测、实际个人模型质量、原 QQ 私聊收发、真实手机网络/休眠与至少 7 天试运行。没有创建 release 或上传真实数据。
