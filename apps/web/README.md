# ChatTwin Web

React + TypeScript + Vite 本地工作台。所有页面调用 FastAPI，页面中不内置聊天回答或训练结果。

```sh
pnpm install --frozen-lockfile
pnpm generate:api
pnpm build
```

API 类型来自根目录 `schemas/openapi.json`，生成到 `src/generated-api.ts`。`src/api.ts` 只对后端未细分的字典元数据做显示类型收窄，Binding、ModeStatus、ModeCommand、SandboxInput、MemoryInput 直接复用生成类型。

生产页面由后端提供，构建资产复制到 `src/chattwin/web_dist`。开发模式 `pnpm dev` 将 `/api` 代理到 `127.0.0.1:8765`；真实运行与浏览器验收优先使用后端同源入口。

已实现：本人凭证登录、加载虚构数据、创建档案和独立关系、选择绑定、B0/B1/B2 试聊、通知与接管、导入预览/稳定 ID 选择/CSV 映射、从当前关系消息选择出处、关系记忆保存删除、冻结数据集报告、训练条件与当前运行状态。

接管按钮不受生成、导入、构建数据集或正在开启的请求阻断。相同失败命令重试复用 command_id；旧控制 epoch 响应不能覆盖新状态。切换绑定后，导入表单、记忆和训练报告重置，未完成的试聊请求取消。

访问凭证仅放在当前浏览器会话的 sessionStorage，不放在 URL。没有遥测、远程字体、外部图像、HTML 聊天渲染或第三方脚本。

剩余范围：完整画像编辑、训练作业控制、模型切换、备份恢复面板尚未实现；服务端现有 API/CLI 不因此被声明为网页已覆盖。QQ 原会话、手机离网接管和真实 GPU 训练需独立实机验证。

新建档案/关系使用真实 API 顺序创建 Persona、Relationship 和默认 HUMAN 的网页 Binding，完成后刷新状态并选中该关系。已确认完成的步骤在失败重试时复用。记忆来源只从当前关系的 `/messages` 读取和选择，不要求用户猜消息 ID；目前该 API 最多返回 200 条，界面明确标注这一限制。
