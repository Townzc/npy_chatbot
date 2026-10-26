# 本机常驻与手机访问

当前已有短期登录、同源/Host 校验、固定接管控件和 launchd 配置生成器。真实 Mac 休眠/唤醒、iPhone 蜂窝网、QQ 运行组合尚未验收，因此 T26 仍是 PARTIAL。

## 登录边界

网页使用本人凭证交换默认一小时会话，仅把短令牌放在 sessionStorage。服务端只保存令牌 hash，退出撤销，服务重启全部失效。五次失败登录触发一分钟限流；已登录会话的本人接管不受该登录限流影响。凭证不放 URL，也不写网页或访问日志。

核心默认保留本机 CLI 的直接 owner Bearer 访问。任何手机入口应设置 `CHATTWIN_REQUIRE_SESSION=1`，使 owner 凭证仅用于 `/api/v1/auth/session`，控制 API 强制检查短期会话。退出/会话过期不会冒称已接管；需要停止 AI 时，先点击本人接管并确认停止，再退出。

## 可选私网入口

服务仍只监听 loopback。用户已有 Tailscale 账号与设备网络时，可用 Serve 把 loopback 端点提供给自己的 tailnet，并使用 HTTPS。具体开关与证书要求以 [Tailscale Serve 官方说明](https://tailscale.com/docs/features/tailscale-serve) 及 [命令参考](https://tailscale.com/docs/reference/tailscale-cli/serve) 为准，核查于 2026-10-26。本项目没有创建账号、改网络策略、安装 VPN 或开放入口。

使用实际机器的完整 DNS 名称替换占位符，只允许明确 hostname：

```sh
export CHATTWIN_REQUIRE_SESSION=1
export CHATTWIN_ALLOWED_HOSTS='YOUR-MACHINE.YOUR-TAILNET.ts.net'
uv run chattwin serve --port 8765
```

在另一个用户自己的终端配置私网反向代理：

```sh
tailscale serve --bg http://127.0.0.1:8765
tailscale serve status
```

仅授予本人设备访问，不使用公开 Funnel。手机打开该 HTTPS 地址，使用本人凭证登录；不把这个凭证发送到本开发对话。代理必须保留 Host，并提供正确 HTTPS scheme，否则同源检查会拒绝请求。若出现 403，应检查实际来源与代理配置，不要移除 Origin/Host 保护。

## macOS 登录服务配置

生成器只写配置，不安装或启动服务；QQ 仍需单独、明确选定账号和会话启动。示例路径按本机已安装的可执行文件替换：

```sh
uv run chattwin host launch-agent "$HOME/Library/LaunchAgents/local.chattwin.owner.plist" \
  --executable /ABSOLUTE/PATH/TO/chattwin \
  --data-dir "$HOME/Library/Application Support/ChatTwin"
plutil -lint "$HOME/Library/LaunchAgents/local.chattwin.owner.plist"
```

该定义包含独立数据目录、严格短会话模式、私有日志路径、失败重启与 15 秒重试节流；不含任何 key 或 QQ 配置。可用 `--allowed-host` 加入明确 tailnet DNS 名称。目标已存在时拒绝覆盖。

用户自行启动/停止该登录服务：

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.chattwin.owner.plist"
launchctl bootout "gui/$(id -u)/local.chattwin.owner"
```

本次实际生成的 plist 经 `plutil -lint` 通过；没有在用户登录项中安装它。服务定义不防止机器睡眠，不能把屏幕熄灭当作后台持续可用证据。

## 仍需真实设备验收

先用虚构数据验证：蜂窝网登录与接管、会话到期/退出、另一浏览器旧版本接管、断网时明确失败、Mac 睡眠/唤醒、服务重启后不恢复托管。然后按 QQ 实测文档由用户验证指定原私聊。记录设备/系统/QQ/桥版本和实际时间，不以浏览器窄屏截图替代真手机试验。
