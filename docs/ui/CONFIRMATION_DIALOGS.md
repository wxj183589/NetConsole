# 全局确认对话框

NetConsole 的业务确认统一由 `apps/desktop_renderer/src/components/feedback/useConfirm.ts` 提交、由应用根节点的 `NcConfirmDialog` 渲染。页面不得使用 `window.confirm()`、私有确认弹窗或直接调用 `ElMessageBox.confirm()`。

## 确认类型

| 类型 | 用途 | 按钮示例 |
| --- | --- | --- |
| `INFO` | 无副作用提示 | `知道了` |
| `WARNING` | 可撤销或需提醒的操作 | `确认保存配置` |
| `DANGER` | 真实设备或配置写操作 | `确认执行` |
| `SECURITY` | 凭据、主机密钥或外部进程风险 | `确认启用` |
| `DESTRUCTIVE` | 删除、覆盖、强制停止 | `确认删除` |

调用方应使用动作化标题和按钮文案，并把设备、影响范围、命令计划或风险说明放入 `message`/`detail`。安全操作可通过 `requireAcknowledgement` 要求用户勾选风险确认。需要名称级强确认的删除可传入 `confirmationText`；`NcConfirmDialog` 仅在输入值与其逐字符完全一致时启用确认按钮，Element Plus fallback 也必须使用相同的精确校验。可通过 `confirmationLabel` 和 `confirmationPlaceholder` 调整输入提示，但不得在调用方另建私有弹窗。

## 生命周期与安全边界

- 弹窗居中、限制宽度、追加到 body，并禁止点击遮罩误关闭。
- 未确认或取消不得提交 Application Service；取消、ESC 和关闭按钮都返回取消结果。
- 高风险操作不把密码、Token、主机密钥私钥或服务器绝对路径放入确认参数。
- `useConfirm` 的 Element Plus fallback 只在应用根确认组件尚未挂载的开发/测试阶段使用；生产页面统一由 `NcConfirmDialog` 提供。
- 长操作的进度、取消和失败保留由 Task Center 负责，确认弹窗只负责授权，不创建第二套任务状态源。

## 迁移清单

设备删除、批量删除、配置保存、SFTP 启用、主机密钥信任、外部终端密码传递、文件覆盖、局点切换/迁移和任务强停均须登记确认类型，并由对应 Application Service 做最终权限和状态校验。
