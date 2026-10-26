# 虚构示例

这里所有人物、账号与内容均为合成数据。它们只用于启动解析与隔离测试，不能证明某个实际导出工具版本已兼容，也不能用于宣称微调效果。

- chatlab_wechat.synthetic.jsonl：ChatLab v0.0.2 流式结构，微信标签。
- chatlab_qq.synthetic.json：同一交换格式的 QQ 标签；这不是 QCE 专用 JSON。
- generic_chat.synthetic.csv：字段映射示例，UTC 时间，包含本人和对方。
- canonical_messages.synthetic.jsonl / canonical_manifest.synthetic.json：本项目规范消息形状与身份用途映射示意。
- mode_cases.json：模式通知和竞态的实现验收案例，尚无运行测试代码。

QCE 专用 fixture 必须在 T09 取得明确版本的真实脱敏导出或可验证上游格式之后补齐，不编造一份 JSON 假装已支持 QCE。
规范模型实现后应由 Pydantic 生成 schema，再验证/必要时更新这些示例并记录契约变更。
