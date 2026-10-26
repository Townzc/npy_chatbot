# sources.md

本文件是完整计划的按主题阅读副本。规范以 [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 为准；来源见 [sources.md](sources.md)。修改计划时使用随包脚本重新生成这些副本。

## 19. 参考资料与证据边界

上游事实以 2026-10-26 的官方仓库/文档为依据。架构、顺序、工期和验收阈值是本计划的设计建议。

- **[S1]** 用户提供的 *The AI-Native SDLC Playbook*，Louis Claxton，54 页；重点 p7–9 工件依赖、p11–17 intent/spec、p19–29 实施、p31–35 测试/eval、p37–46 发布、p48–51 维护。依据前一轮全文审阅。
- **[S2]** [QCE 仓库](https://github.com/shuakami/qq-chat-exporter)；[导出说明](https://shuakami.github.io/qq-chat-exporter/docs/guide.html)。
- **[S3]** [ChatLab v0.0.2 交换格式](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/standard/chatlab-format.md)。
- **[S4]** [ChatLab LICENSE](https://github.com/ChatLab/ChatLab/blob/main/LICENSE)；[导出使用边界](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/usage/how-to-export.md)。
- **[S5]** [WeFlow](https://github.com/hicccc77/WeFlow)；[第三方组件说明](https://github.com/hicccc77/WeFlow/blob/main/docs/third-party-components.md)；[LICENSE](https://github.com/hicccc77/WeFlow/blob/main/LICENSE)。
- **[S6]** [WeClone](https://github.com/xming521/WeClone)；[训练入口](https://github.com/xming521/WeClone/blob/master/weclone/train/train_sft.py)。
- **[S7]** [NapCatQQ](https://github.com/NapNeko/NapCatQQ)；[当前 LICENSE](https://github.com/NapNeko/NapCatQQ/blob/main/LICENSE)。
- **[S8]** [NapCat Mac Installer](https://github.com/NapNeko/NapCat-Mac-Installer)。
- **[S9]** [Tencent/openclaw-weixin](https://github.com/Tencent/openclaw-weixin)；[协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)；[腾讯云微信 ClawBot 对话流程](https://cloud.tencent.com/document/product/1291/129132)。
- **[S10]** [AstrBot](https://github.com/AstrBotDevs/AstrBot)；[MaiBot](https://github.com/Mai-with-u/MaiBot)。
- **[S11]** [chatlog 项目移除通知](https://github.com/sjzar/chatlog)。
- **[S12]** [WeChatMsg 当前说明](https://github.com/LC044/WeChatMsg)。
- **[S13]** [Qwen3-4B-Instruct-2507 官方模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)。
- **[S14]** [Apache License 2.0 正文](https://www.apache.org/licenses/LICENSE-2.0)。
- **[S15]** [Hugging Face PEFT](https://huggingface.co/docs/peft/main/en/index)；实现时切换到已锁定的稳定版本文档。
- **[S16]** [NapCat 事件兼容表](https://napneko.github.io/develop/event)。

本计划引用资料用于核实能力、接口和限制；没有复制上游实现代码。历史示例与计划中的类型名称不构成任何第三方程序的再许可。
