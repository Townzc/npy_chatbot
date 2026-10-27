# QQ 桥与聊天导出：可执行路径和未验证项

核查日期 2026-10-26。用户尚无 OneBot 桥；已确认现有 8 个无扩展名文件来自 QQ“聊天记录管理 → 备份聊天记录到电脑”。来源是用户确认的事实，容器内部尚未解析。下面依据上游说明准备接入，不表示本机已安装、已登录或真实 QQ 测试通过。

2026-10-27 最新补充：用户进一步确认，生成所提供 `.bak` 时，**电脑 QQ 能看到所需旧记录**。因此针对这部分历史改走下面的第 1 分支；还需确认保存记录的是当前 Mac 还是另一台电脑。先前“仅手机可见”的答复不再作为这部分历史的当前前提，实际导出范围仍需核验。

## 现有 QQ 备份怎么处理

先保留现有备份原样。初次检查未识别为 JSON/CSV/标准 SQLite/ZIP/gzip，2026-10-27 进一步检查确认原 8 个文件中有 4 个带 `SQLite header 3\0` / `MSG0` 自定义头，其余 4 个仍未识别。注意 `SQLite header 3` 与标准 `SQLite format 3` 不同；改名为 `.json` 不会产生结构化导出。当前 QCE 指南描述的是读取当前电脑客户端已经同步到本机的记录，没有给出直接打开这些官方备份容器的方法。[固定 QCE 指南](https://github.com/shuakami/qq-chat-exporter/blob/7d154b847a0cb3f9cffbdb126598c4d1434995ba/docs/guide.md)

用户随后提供一份**电脑 QQ → 导出聊天记录**产生的 `.bak`。实际文件为 17,388,206 bytes 的 ZIP，4 个内部文件均为 MSG0，外层没有 ZIP 加密；逐成员完整读取的 CRC 通过，原文件前后 SHA-256 相同。数据库层尚未解密，不能得出双方身份、日期、消息数或完整度。用户确认电脑可见所需旧记录，但导出电脑与 QQ 版本仍待确认，不能根据文件类型反推用户使用了某个旧版本。

MSG0 与 `QQ_NT DB` 是不同标记，不能把“裁掉 1024 字节，再用 NTQQ 的 UID/盐值推导”当成可用转换。上游 PCQQ 文档已经标为不再维护，建议先将旧数据库导入 QQNT；旧脚本依赖 Windows 客户端及运行时 key，不是独立读取任意 `.bak` 的工具。本项目没有运行注入、重设数据库密钥或恢复覆盖操作。[PCQQ 提取边界](https://github.com/QQBackup/QQDecrypt/blob/0dba968ebcb9ba23a68571780eb6b53687f77493/docs/decrypt/extract/PCQQ%20%28Windows%29.md) · [上游旧版导出脚本](https://github.com/QQBackup/qq-win-db-key/blob/5c643c39bdc65a7ce3ecc414052fdfd93d5f9107/scripts/windows/pcqq/pcqq_dump.py)

当前下一步是在**实际保存所需历史的电脑**运行 QCE，取得单文件 JSON，再核验具体首末时间和缺口。若保存记录的是另一台电脑，不能仅在当前 Mac 登录就假设历史会迁移过来，也不能假设 `.bak` 是手机全部历史的副本。只读诊断可运行 `chattwin import probe /absolute/path/to/export.bak`；[检查报告](evidence/qq-bak-inspection-2026-10-27.md) 区分真实文件头验证与合成导入错误回归。

接下来按实际可见记录分支：

1. **电脑 QQ 能看到所需旧记录**：在保存记录的电脑上使用匹配平台的 QCE v6.3.2，导出一个私聊的小范围单文件 JSON，先核对时间、双方稳定 ID、消息数和抽样内容，再扩大范围。下方 Mac 准备只适用于记录就在这台 Mac 的情况；另一台 Windows/Mac 需在原电脑完成导出。实际格式门槛通过后进入 ChatTwin；先关闭嵌入头像并控制网页文件在 20MiB 内。
2. **只有手机能看到旧记录**：记录“手机可见、电脑不可见”的时间边界，先导出电脑确实可取得的部分。官方备份或恢复操作完成，不能单独作为“电脑已有全部历史”的证据。计划记录该账号漫游只有 7 天，因此不能保证重新登录、恢复备份或 QCE 漫游导出能补齐更早内容；不以购买会员代替可用性核验。
3. **只剩备份、手机也看不到**：先由本人在 QQ 自带备份/恢复界面核对该备份是否可恢复、恢复目标是什么设备；本项目没有验证当前版本的恢复流程，不自动恢复、覆盖现有记录或更改备份。恢复后仍须重新核对电脑可见范围，才能进入上一步导出路径。

这些分支是在核查数据在哪里，不要求用户在对话发送私聊正文。完整度报告保留请求范围、实际首末时间/条数和未知缺口；解析成功不声明全量。

也检查了 QQBackup 的 iOS 提取说明：旧 iOS 教程已标为不再维护，NTQQ iOS 教程明确标为近期版本未确认；其离线推导段需要原始 `nt_msg.db` 和相关账号元数据，不能据此断言能读取这些 MSG0 或未识别文件。未运行提取工具、修改手机或取得密钥。[旧 iOS 状态](https://github.com/QQBackup/QQDecrypt/blob/main/docs/decrypt/extract/IOSQQ.md) · [NTQQ iOS 状态及输入要求](https://github.com/QQBackup/QQDecrypt/blob/main/docs/decrypt/extract/NTQQ%20%28iOS%29.md)

下一项候选是 **Finder/iTunes 的 iPhone 整机本地备份**，与 QQ 内的电脑备份分开。Apple 说明电脑备份包含设备大部分数据和设置；这不能证明当前 QQ 的数据库一定包含其中。第三方 `iphone_backup_decrypt` 公开了只按备份目录索引筛选文件的接口，但解开 iOS 备份层也不等于解开 QQ 数据库层。先确认 iOS/QQ 版本及是否有这类备份，再只检查 QQ 对应的目录项和数据库是否存在；在得到可验证的数据库前，不承诺能导出全部旧聊天。[Apple 备份说明](https://support.apple.com/zh-cn/108771) · [备份工具的输入与筛选接口](https://github.com/jsharkey13/iphone_backup_decrypt)

本机只检查了默认 `~/Library/Application Support/MobileSync/Backup` 是否存在，结果不存在；未扫描其他磁盘、未读取手机备份正文。尚未安装或运行上述工具，也没有要求取消备份加密、越狱或覆盖手机数据。若后续需要备份密码，由本人在本机输入，不贴到对话或写入 Git。

## QQ 历史记录：QCE 固定版本

本次 releases API 返回 QCE **v6.3.2**（2026-10-03），Apple Silicon 包为 `NapCat-QCE-macOS-arm64-v6.3.2.tar.gz`，41,924,485 bytes。2026-10-27 已下载至仓库外私有工具目录，本地 SHA-256 与发布值 `a241a2a694edb317fa494e9f9a0bda79284937be97afa7bfea269741b7f15a9a` 一致；994 个归档条目路径与类型检查通过，启动脚本与固定源码一致且语法检查通过。实际包内是 QCE 6.3.2 / NapCat 4.18.28。尚未启动、登录或真实导出；[准备证据](evidence/qce-preparation-2026-10-27.md) 与运行验收分开。[固定发布页](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2)

按[固定 macOS 指南](https://github.com/shuakami/qq-chat-exporter/blob/7d154b847a0cb3f9cffbdb126598c4d1434995ba/docs/macos-deploy.md)：

1. Apple Silicon、已安装官方 QQ、可用 `codesign`，至少 1.5 GB 空间；此平台仍标为预览支持。
2. 用户用 Command-Q 完全退出桌面 QQ，再在仓库外解压官方包并运行 `./launcher-user.sh`。
3. 启动器会建立并重签名专用 QQ 副本。这份副本失去原 App Sandbox 保护，并通过链接使用桌面 QQ 数据；原 `/Applications/QQ.app` 保留。运行期间不要再打开桌面 QQ。
4. 用户自行扫码。访问本机 `http://localhost:40653/qce`，令牌仅保留在本机；不用把带 token 的一键登录链接发给助手或写进 Git。
5. 选择一个明确的私聊和时间范围，导出 JSON；保存 QCE/QQ 版本、选择范围、导出统计和文件摘要。先不导出全部联系人。
6. 导出结束停止 QCE，再重新打开原桌面 QQ。`start-standalone.sh` 只能查看已有导出，不能替代登录导出。

启动前还要核对实际网络配置。该版本 QCE Rust HTTP 服务硬编码监听 `0.0.0.0:40653`，`security.json` 的 `serverHost` 不能改变监听地址。已准备随机令牌和 loopback API 白名单、NapCat WebUI 绑定 `127.0.0.1` 的配置草案，但尚未应用，运行时鉴权未验证；不能称为所有端口都只在本机监听。OneBot 服务保持关闭，先完成导出后再单独配置桥。原 QQ 与专用副本共享真实数据库的安全边界变化需要用户确认后再执行。不要公开管理端口或带令牌链接。

历史完整度以实际可取得记录为准：普通导出读取本地已有/已同步消息，实验性漫游导出也有日期和平台限制，不能保证取回手机上全部旧记录。[QCE 使用手册](https://github.com/shuakami/qq-chat-exporter/blob/master/docs/guide.md)

ChatTwin 的 ChatLab/CSV/规范 JSONL 和 QCE 单 JSON 解析器已实现；QCE 使用固定源码契约的人工虚构样例验证，尚未通过真实导出验收。拿到导出后在本机核对结构、发送者稳定 ID 与历史边界；结果见 [兼容范围](qce-compatibility.md)。导出与后续训练数据保存在私有目录，不上传 GitHub。

## QQ 原私聊：NapCat 的 OneBot v11 正向 WS

桥接与历史导出分开验收。NapCat 有 Mac 安装器和 Linux/Docker 路径；Mac 安装器会改变 QQ 启动入口，与 QCE 专用副本不是同一种安装方式。先选定一种运行部署和一个账号的唯一桥进程。核心仍独立实现 OneBot 客户端，不捆绑桥程序。[NapCat 部署](https://napneko.github.io/guide/boot/Shell) · [Mac 安装器](https://github.com/NapNeko/NapCat-Mac-Installer)

NapCat 本体的自定义许可与安装器 MIT 不同；其 README 推荐 QCE，并限制未经授权基于 NapCat 代码开发。当前只准备官方发布包在用户电脑独立运行，ChatTwin 不复制其实现或重新分发；不把本项目 Apache-2.0 扩展到上游，也不将静态说明当成所有用途的许可结论。[NapCat LICENSE](https://github.com/NapNeko/NapCatQQ/blob/main/LICENSE) · [上游 README](https://github.com/NapNeko/NapCatQQ/blob/main/README.md)

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

## 与 GPU 任务的关系

首次 AutoDL 训练只使用随包虚构数据，QQ 登录、历史导出和原私聊桥留在本机处理。QQ 原会话的连接探针也不依赖历史导出成功，可以在桥可用时先验收。现有备份不上传 AutoDL 或 GitHub；本次没有访问真实消息数据库、改写 QQ 安装或登录任何账号。
