# QQ 桥与聊天导出：可执行路径和未验证项

核查日期 2026-10-26。用户尚无 OneBot 桥；现有 8 个无扩展名文件的来源/导出方式未明。下面依据上游说明准备接入，不表示本机已安装、已登录或真实 QQ 测试通过。

## QQ 历史记录：QCE 固定版本

本次 releases API 返回 QCE **v6.3.2**（2026-10-03），Apple Silicon 包为 `NapCat-QCE-macOS-arm64-v6.3.2.tar.gz`，41,924,485 bytes，发布页给出的 SHA-256 为 `a241a2a694edb317fa494e9f9a0bda79284937be97afa7bfea269741b7f15a9a`。这是上游公布值；未下载或独立验包。不要选择来源不明的二次打包。[固定发布页](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2)

按[上游 macOS 指南](https://github.com/shuakami/qq-chat-exporter/blob/master/docs/macos-deploy.md)：

1. Apple Silicon、已安装官方 QQ、可用 `codesign`，至少 1.5 GB 空间；此平台仍标为预览支持。
2. 用户用 Command-Q 完全退出桌面 QQ，再在仓库外解压官方包并运行 `./launcher-user.sh`。
3. 启动器会建立并重签名专用 QQ 副本。这份副本失去原 App Sandbox 保护，并通过链接使用桌面 QQ 数据；原 `/Applications/QQ.app` 保留。运行期间不要再打开桌面 QQ。
4. 用户自行扫码。访问本机 `http://localhost:40653/qce`，令牌仅保留在本机；不用把带 token 的一键登录链接发给助手或写进 Git。
5. 选择一个明确的私聊和时间范围，导出 JSON；保存 QCE/QQ 版本、选择范围、导出统计和文件摘要。先不导出全部联系人。
6. 导出结束停止 QCE，再重新打开原桌面 QQ。`start-standalone.sh` 只能查看已有导出，不能替代登录导出。

历史完整度以实际可取得记录为准：普通导出读取本地已有/已同步消息，实验性漫游导出也有日期和平台限制，不能保证取回手机上全部旧记录。[QCE 使用手册](https://github.com/shuakami/qq-chat-exporter/blob/master/docs/guide.md)

ChatTwin 当前的 ChatLab/CSV/规范 JSONL 已实现，QCE 原生 JSON 尚未通过固定版本真实样本验收。拿到导出后先在本机识别结构、保留发送者稳定 ID，再验证解析器；不将备份容器改扩展名后冒充 JSON。无需在对话粘贴正文，也不把导出上传 GitHub。

## QQ 原私聊：NapCat 的 OneBot v11 正向 WS

桥接与历史导出分开验收。NapCat 有 Mac 安装器和 Linux/Docker 路径；Mac 安装器会改变 QQ 启动入口，与 QCE 专用副本不是同一种安装方式。先选定一种运行部署和一个账号的唯一桥进程。核心仍独立实现 OneBot 客户端，不捆绑桥程序。[NapCat 部署](https://napneko.github.io/guide/boot/Shell) · [Mac 安装器](https://github.com/NapNeko/NapCat-Mac-Installer)

已具备适用许可的桥由用户配置；NapCat 本体的自定义许可与安装器 MIT 不同，不能从“个人使用”自行推导已获全部授权。[NapCat LICENSE](https://github.com/NapNeko/NapCatQQ/blob/main/LICENSE)

NapCat WebUI 中建立网络配置：

| 设置 | ChatTwin 对接值 |
|---|---|
| 类型 | **WebSocket 服务器 / 正向 WS**，不是反向 WS 客户端 |
| 监听 | `127.0.0.1`，例如端口 `3001` |
| OneBot 访问令牌 | 独立随机值，通过 `CHATTWIN_ONEBOT_TOKEN` 提供给 ChatTwin |
| 消息格式 | `array` 消息段 |
| 自身消息上报 | `reportSelfMessage=true`；用于验证本人发言与发送回声 |
| 其他 | 开启该服务，关闭无关调试日志；记录实际 NapCat/QQ 版本 |

WebUI 通常为 6099，冲突时可能顺延；它是管理入口，不是这里的 OneBot 端口。QCE 的 40653 也是另一服务，不应填作 WS 地址。[NapCat 基本配置](https://napneko.github.io/config/basic) · [网络配置](https://napneko.github.io/onebot/network)

设置私有环境变量后先执行只读探针：

```sh
uv run chattwin qq probe --url ws://127.0.0.1:3001 --account EXPECTED_ACCOUNT_ID
```

只有版本、身份、在线状态均符合预期，才进入 [qq-validation.md](qq-validation.md) 的指定会话验收。若桥在 Linux，优先使用 SSH 本地转发，桥继续只监听 loopback；不要为方便接入直接暴露管理端口或 OneBot 到公网。

`reportSelfMessage=true` 不证明手机人工发言一定上报，也不能消除所有自身回声竞态。默认只读探针不发消息；当前开发会话继续遵守“外部消息由用户本人发送”。两条固定通知、真实 AI 回复、手机接管及断线恢复须由用户按受控步骤实测，不能拿协议测试充数。

## 如果 8 个文件来自微信

需先确认来源系统、微信版本和“备份/迁移/导出”的具体功能。官方备份容器不等于可读聊天导出；现有项目不提供任意备份解密。WeFlow 上游列出 ChatLab/CSV 导出和本地 API，但当前 README 同时说明需要另行具备第三方原生解密组件，因此不能声称下载即能读这些文件。[WeFlow 说明](https://github.com/hicccc77/WeFlow)

可解析的本地 ChatLab/CSV 到手后再走已有导入、身份确认和关系隔离流程；微信历史导入不等于微信原个人号自动回复。本次没有访问真实数据库、改写 QQ 安装或登录任何账号。
