# 模型版本与用量

网页“训练与模型”可登记训练产物、建立模型端点版本、发起连接测试、启用或回滚。产物必须位于 Git 外，并通过训练成功、新进程重载、manifest/hash、本人/关系和本地冻结数据集校验。删除来源或重映射身份会撤销依赖产物与部署；已有权重文件不会因此自动遗忘。

端点版本不可原地改地址、模型或关系。HTTPS 可用于远程端点；HTTP 仅允许 loopback。凭证只引用服务环境中的 `CHATTWIN_MODEL_KEY` 或其带后缀变体，不能借此读取 QQ 或 owner 密钥。不要把 token 填进 endpoint URL。

adapter 端点测试除实际生成外，还核对 `/health` 返回的已加载产物 hash、Persona、关系与模型名称。切换版本会停止当前托管、增加控制 epoch、使旧候选无效；有待确认/unknown 模式通知时拒绝切换。回滚也需要明确重新开启，不会悄悄恢复 AI。

## 基础模型与 adapter 服务

`chattwin model serve` 的认证推理端点接受 `chattwin-adapter` 和 `chattwin-base`。后者在同一生成锁内禁用 LoRA，实际使用相同底座生成；请求结束恢复 adapter。两者都检查 Persona/关系、上下文 token 上限和独立模型凭证。health 提供固定底座、tokenizer revision、模板与 adapter manifest 哈希。

网页 B0/B1/B2 使用已配置基础 provider，B3 使用已选 adapter；若基础 provider 仍为 Mock，网页会标虚构。网页快速试聊不证明 B0–B3 使用同一底座。正式公平对照须使用 [独立评测工具](evaluation.md)，它验证版本、时间截断与一致的 B2/B3 输入，默认 temperature=0。tiny 模型只提供执行证据。

## 持久月度预算

“运行维护”按 Persona 设置 UTC 月份请求数、输入/输出 token 上限和可选 USD 估算。默认每月 1000 次、100 万输入/25 万输出 token。金额上限需要同时提供供应商输入与输出单价（每百万 token）；GPU、推理主机、存储等费用不计入这张模型调用账目。

每次 HTTP 生成/端点测试先在 SQLite 事务中预留一次请求及保守 token 额度，竞争请求不能同时越过限额。成功且供应商返回 usage 时按报告结算；超时、取消、失败或缺少 usage 时保留预留，防止重试和重启使未知费用归零。80% 提醒，额度不足拒绝发起新请求并暂停 AI。Mock 对话不消耗 HTTP 预算。

输入预留按 UTF-8 字节数加协议余量计算，输出预留按 max_tokens；服务器额外隐藏上下文或其他收费项不能由客户端保证。金额按当前配置单价估算，并非供应商账单。原有每进程 HTTP 调用上限仍独立生效；预算不授权消费或自动租用服务器。
