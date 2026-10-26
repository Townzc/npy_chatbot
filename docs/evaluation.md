# 独立 HTTP 评测与人工盲评

当前交付是可执行的评测工具，**不是 T24/T28 质量验收通过**。仓库仅提供 12 个明确虚构场景（六类各两个），没有制造 100 个“真实样本”或人工质量分数。正式 Qwen CUDA 训练、独立 100 场景人工评审、真实七天试运行仍未完成。

## 比较边界

`python -m chattwin.evaluation` 直接调用已注册、已验证、相同 Persona/Relationship 的 HTTP 模型，完全不调用聊天渠道、outbox 或 QQ。默认 mock 模型不能用于评测。每次请求的 `max_tokens` 相同，`temperature=0`；服务端仍须如实实现协议。端点身份来自健康检查的声明，不等于可信执行环境证明。

| 变体 | 模型与输入 |
| --- | --- |
| B0 | 基础模型，最小 AI 身份与事实不确定性规则，同一场景上下文 |
| B1 | B0 加来源合规、本人已批准且在截止点之前的风格规则/示例 |
| B2 | B1 加同关系已确认且在截止点之前的记忆 |
| B3 | 已注册、校验有效的 LoRA，**逐字相同的 B2 消息数组** |

B3 必须有有效、未撤销的注册产物和已验证部署；runner 再核验权重文件与 manifest hash、来源状态、scope、底座/revision/tokenizer/template pin。正式模式拒绝 tiny CPU 产物。B0–B2 部署不能绑定 adapter。内置训练推理服务同时提供 `chattwin-base`（同一模型在锁内真正禁用 PEFT adapter）和 `chattwin-adapter`；可注册两个指向同一端点的部署做公平对照。B3 的 health.model 必须等于请求 model，不能将 base 冒充 adapter。

正式基础端点的 `/health` 必须返回与评测 spec 完全匹配的 `base_model_id`、`base_model_revision`、`tokenizer_revision`、`chat_template_hash`。内置共享推理服务还返回 `models`，基础部署必须选 `chattwin-base`。LoRA health 必须返回对应 `artifact_manifest_hash`、`persona_id`、`relationship_id`、`model`。缺少或不匹配即拒绝，不把用户填写的版本号当作已验证模型身份。

## 输入冻结与防泄漏

可以使用手工审核的 JSONL 场景，或 `--dataset-id` 从冻结数据集的 `test.jsonl` 推导场景。不能同时指定两种来源。

手工场景字段：`id`、`category`（style/multi_turn/facts/privacy/commitment/unsupported）、`messages`（仅 user/assistant，末条为 user）、带时区的 `source_cutoff`、人工 `reference`、`rubric`、`synthetic`、`provenance: manual_reviewed`。人工编写的场景、答案与评语必须独立审核，避免复制训练答案或在上下文里暗含答案；工具无法自动证明手工语义独立性。所有真实场景文件应放在 Git 外。

冻结测试样本验证登记 scope、manifest 哈希、三份 split 文件哈希、test 片段与 source/target lineage；目标 assistant 回复只作为人工参考保存，永不传给模型。截止点设为整个测试片段开始时间。对 B3，冻结 test 必须来自该 adapter 对应数据集版本与哈希，不能用另一个可能已进入训练的数据集冒充独立测试。预载样本在运行前再次验证；来源先删除时不会重新写回正文副本。

风格、记忆都经过 DataService 范围和 split 过滤，再独立核查来源在截止点之前、未被任何冻结数据集列为非 train。记忆自身的创建和更新时间也不得来自未来。没有合规批准风格时 B1 可能等于 B0；没有可用记忆时 B2 可能等于 B1，`prompts.json` 记录实际使用项，不填造资料。场景里的真实历史上下文属于给定输入，检索不会偷偷加入测试片段其他内容。

一次运行先冻结案例、提示词和模型记录；之后每次传输前重检版本与来源。若发生变化，该条失败，不用新资料静默替换。每次调用及其结果落盘持有 `data-management.lock`，防止撤销与传输竞态；健康检查最多 10 秒、生成最多 35 秒。源管理可能提示忙，请重试；该锁不控制本人接管。删除来源会将相关本地评测目录纳入影响预览及隔离删除，身份重映射也撤销受影响范围评测；外部复制的评分 CSV 无法自动召回，须人工删除。

## 运行

先在本地 UI 注册并验证基础和 LoRA 部署。密钥仅放进部署指定的环境变量，不放在 spec、案例或 Git。将下例保存在私有目录，替换实际 scope 和 deployment UUID：

```json
{
  "persona_id": "PERSONA_UUID",
  "relationship_id": "RELATIONSHIP_UUID",
  "base_deployment_id": "BASE_DEPLOYMENT_UUID",
  "adapter_deployment_id": "ADAPTER_DEPLOYMENT_UUID",
  "base_pin": {
    "base_model_id": "Qwen/Qwen3-4B-Instruct-2507",
    "base_model_revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
    "tokenizer_revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
    "chat_template_hash": "64f85b198065d0fba2a81f37e10ed68161ce2c19a754c7100e67e0ca2ee9c326"
  },
  "mode": "formal",
  "variants": ["B0", "B1", "B2", "B3"],
  "temperature": 0,
  "max_tokens": 256,
  "max_cases": 100
}
```

```sh
uv run python -m chattwin.evaluation run \
  --data-dir "$CHATTWIN_DATA_DIR" --spec /private/location/evaluation-spec.json \
  --dataset-id DATASET_UUID

# 或使用经过独立审核的手工案例：
uv run python -m chattwin.evaluation run \
  --data-dir "$CHATTWIN_DATA_DIR" --spec /private/location/evaluation-spec.json \
  --cases /private/location/reviewed-cases.jsonl
```

工具测试必须显式设 `mode: synthetic-protocol`，只接收 `synthetic:true` 的案例，允许仅 B0–B2；若含 B3 仍必须注册真实有效 adapter，只是允许 tiny 产物。可使用 `examples/evaluation.synthetic.jsonl`。所有结果、盲评表、汇总均显著标记 `synthetic_protocol_only`，不能作为正式质量证据。正式模式必须含完整 B0–B3，拒绝合成案例。

默认最多 100 场景/400 次请求；`max_cases` 可显式调整，最大 1000。串行执行，不重试失败请求，不自动恢复进程中断，不自动下载模型，不自动部署或晋升。正式调用可能使用配置的远程模型并产生费用；此次协议验证只访问本地测试服务器。

## 持久结果与人工评分

输出到 `$CHATTWIN_DATA_DIR/evaluations/{UUID}`，目录 0700、文件 0600，拒绝 Git 内输出。内容含私密聊天、模型回复和参考答案，**不应上传或加入 Git**。该目录当前不包含在备份工具的受支持内容中；需要保留时单独保存到私有位置。

- `manifest.json`：scope、来源 IDs、案例/提示词/结果 hash、模型版本 hash、实际类别数、请求数、失败数、证据等级；不会保存 API key。
- `cases.json`：完整独立案例及人工参考。`prompts.json`：实际 B0–B3 输入和 cutoff/source 证据。
- `results.json`：逐条回复、变体、scope、版本/prompt hash、耗时、服务端报告的 token 用量、`token_usage_reported`、结构化失败码；不记录上游错误正文。缺少 usage 不伪造消费量。
- 运行中断可能保留 `running` 状态（硬杀进程来不及清理），仅表示不完整证据，不能出盲评表；可正常捕获的中断写为 `interrupted`。

```sh
uv run python -m chattwin.evaluation blind --run-dir /private/location/evaluations/RUN_UUID
# 由独立人工审阅 blind-review.csv，保持原字段内容与 row_id 不变，只填写评分/notes。
uv run python -m chattwin.evaluation score \
  --run-dir /private/location/evaluations/RUN_UUID \
  --ratings /private/location/reviewed.csv --reviewer '本人或独立评审标识'
```

每场景候选用安全随机顺序排列，CSV 不含变体和模型标识。`blind-key.json` 和原始 `results.json` 留给组织者，评分完成之前不交给评审；措辞仍可能使评审猜到模型，所以这不是完美双盲。CSV 内容以公式字符开头时加文本前缀，防止模型输出被表格软件当作公式执行。

评分字段：`style_score`、`grounded_score` 为整数 1–5；`sendable`、`privacy_violation`、`unauthorized_commitment` 为 0/1。单条可完全留空，已评条必须五项完整；重复、未知 ID 或原始可见内容被修改时拒绝。没有实际填写的评分则不生成质量数字。人工评分和汇总保存在 `human-ratings.json`/`score-summary.json`，明确显示覆盖率、未评项与失败数；不会把部分完成或零观察缺陷说成完全通过。汇总始终 `quality_accepted:false`、`auto_promoted:false`，最终验收由人决定。

推荐独立正式集至少 100 完整场景：35 风格、20 多轮、20 已知/未知事实、10 跨关系隐私、10 本人承诺、5 未支持输入与注入。该建议分布尚未交付或人工验证。不能拿本仓库的 12 个虚构场景或测试中填写的虚构评分代替它。

## 验证证据

`uv run pytest -q tests/test_evaluation.py`：本机真实 loopback HTTP 协议测试，包含匿名本地连接（避免 MockTransport 掩盖空 Bearer header 错误）、各变体内容/温度、future/heldout/跨关系/gold 隔离、冻结文件篡改拒绝、失败持久记录与错误正文脱敏、盲评表/手工评分解析/篡改拒绝。可选 isolated training runtime 存在时，测试真实 tiny LoRA 训练并注册产物，再以明确合成 HTTP 服务器验证 B3 比较契约；**这里的服务器固定回复不是模型推理质量证据**。tiny 的真实参数更新、新进程加载和实际推理由训练运行时测试单独验证。

真实 Qwen B0–B3 分数、100 场景本人评价、跨关系模型权重泄漏强保证、≥7 天外部试运行：仍未验证。
