# 电脑可见历史后的 QCE 准备 — 2026-10-27

用户最新确认：导出 `.bak` 时，电脑 QQ 能看到所需旧记录，且保存记录的就是当前这台 Mac。后续走本机可读导出路径；先前“仅手机可见”不再作为该记录范围的当前前提。

后续进展：用户已明确同意启动变化，原 QQ 正常退出、数据库副本保存完成，QCE 专用 QQ 副本已启动并进入等待扫码状态。以下保留启动前的准备检查；实际运行结果见 [启动证据](qce-runtime-2026-10-27.md)。

## 已完成的真实本机准备

| 项目 | 实际结果 |
|---|---|
| 本机 QQ | 7.0.2 / build 53644，官方应用严格签名检查通过 |
| 本机前提 | Apple Silicon；`codesign` 存在，磁盘约 60.5 GiB 可用 |
| 下载来源 | 官方 QCE v6.3.2 release 的 macOS arm64 包 |
| 包大小 | 41,924,485 bytes |
| SHA-256 | `a241a2a694edb317fa494e9f9a0bda79284937be97afa7bfea269741b7f15a9a`，本地计算与发布元数据一致 |
| 归档检查 | 994 个条目，展开约 123 MB，只有普通文件和目录，无越界路径/链接/设备文件 |
| 实际内置版本 | QCE 6.3.2、NapCat 4.18.28；不等同另一个 Mac 安装器文档的 4.18.41 |
| 脚本静态检查 | `bash -n launcher-user.sh` 通过，启动脚本与固定源码一致 |
| 配置草案检查 | 基础 5 个 JSON 可解析，目录 0700 / 文件 0600；令牌独立、IP 白名单和仅 QCE 插件配置检查通过；后续追加第 6 个 `napcat.json` 日志配置，均尚未应用 |
| 运行状态 | 桌面 QQ 正在运行；40653/40654/6099/3001 当时无监听；没有启动 QCE、创建 QQ 副本或登录 |

包仅保存在用户私有 Application Support 下的 tools 目录，原始包与解压文件均未加入 Git。新配置草案权限为 0600，尚未部署；随机访问令牌只写本地文件，不进入文档、日志输出或命令参数。

准备的配置：NapCat WebUI 绑定 loopback、独立随机令牌；OneBot 服务保持关闭；仅启用 QCE 插件，停用无关 builtin 插件；QCE API 保留令牌及 loopback IP 白名单；导出根目录计划使用私有 Application Support；首轮只做指定会话 JSON，资源保留占位、不启用自动备份或通知。

本机记录范围确认后复查：QQ 仍为 7.0.2 / 53644，四个目标端口空闲，磁盘约 61.0 GiB 可用；没有 QCE 运行副本或 live 配置目录。发现包内默认 NapCat 文件日志为 debug、控制台为 info，追加草案关闭文件日志、把控制台限制为 warn；启动器和插件仍可能输出登录信息，实际运行时须整体重定向到仓库外 0600 日志，不在开发输出中打印。

## 实际启动仍需确认的变化

固定 Mac 启动器会复制并修改 QQ，重新签名生成专用 `QQNapCatRuntime.app`。副本会失去 App Sandbox 与 App Group 保护，并通过软链接与桌面 QQ **共享真实聊天数据库**；原 `/Applications/QQ.app` 保留。启动前应完全退出桌面 QQ，使用期间不同时开启两份客户端。这是实际上游行为，不是 ChatTwin 自己的虚构通道。

用户已确认记录就在当前 Mac，并明确同意退出 QQ、专用副本沙箱变化及共享数据库，已经据此启动。用户自行完成扫码登录及所选私聊的核对。开发会话继续遵守外部消息由本人发送的偏好；导出授权不包含发送私聊、开启自动回复或群发。

另一个已查明的边界：QCE Rust server v6.3.2 的 TCP 监听硬编码为 `0.0.0.0:40653`；`serverHost=127.0.0.1` 只影响地址配置，**不能把监听改为 loopback**。默认非 Docker 模式的受保护 API 校验令牌和 loopback IP 白名单；准备配置也保留该限制。不能把它描述成“端口只在本机监听”；若要求所有监听都仅 loopback，应先解决该上游限制再启动。运行时鉴权和实际监听尚未验证。

QCE 为 GPL-3.0，NapCat 是独立的自定义许可；NapCat README 推荐 QCE，且限制未授权基于其代码开发。本项目使用独立导入器和协议客户端，不复制 NapCat 实现或重新分发这些包；不能将本项目 Apache-2.0 宣称扩展到上游。静态许可说明不等于对所有用途作法律保证。

## 下一项验收

确认启动变化后：退出桌面 QQ → 启动准备好的导出工具 → 本人扫码 → 核对指定私聊和历史边界 → 单 JSON 小范围导出 → ChatTwin 本机预览 → 本人确认稳定 sender ID → 正式导入。届时记录实际 QCE/QQ/NapCat 版本、文件结构/计数/时间和未覆盖范围，不公开正文或账号。

本批没有真实导出、桥连接、QQ 消息发送或 GPU 训练结果。无需为历史导出租 GPU；GPU 仍是后续正式 Qwen 训练的独立前提。

本批仓库仅更新状态与准备文档，未修改应用运行代码；不重复运行上一批已通过的全量应用测试。提交前检查文档 diff 与 Git 索引隐私防护，私有工具包、配置及令牌不进入 Git。

## 固定来源

- [QCE v6.3.2 官方发布](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2)
- [Mac 启动说明](https://github.com/shuakami/qq-chat-exporter/blob/7d154b847a0cb3f9cffbdb126598c4d1434995ba/docs/macos-deploy.md)
- [Mac/Linux 启动脚本](https://github.com/shuakami/qq-chat-exporter/blob/7d154b847a0cb3f9cffbdb126598c4d1434995ba/scripts/napcat-launcher/launcher-user.sh)
- [QCE 监听实现](https://github.com/shuakami/qq-chat-exporter/blob/7d154b847a0cb3f9cffbdb126598c4d1434995ba/qq-chat-export-server/src/main.rs#L179)
- [QCE 安全配置与 IP 校验](https://github.com/shuakami/qq-chat-exporter/blob/7d154b847a0cb3f9cffbdb126598c4d1434995ba/qq-chat-export-server/src/security/manager.rs)
- [NapCat 使用说明与 QCE 推荐](https://github.com/NapNeko/NapCatQQ/blob/main/README.md)
