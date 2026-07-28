# 全局确认对话框

业务页面通过 `useConfirm().confirm()` 请求确认，由 `NcConfirmDialog` 在应用根节点统一渲染。确认类型固定为 `INFO`、`WARNING`、`DANGER`、`SECURITY`、`DESTRUCTIVE`；高风险动作必须使用动作化按钮文案，不能重新调用 `window.confirm` 或页面私有弹窗。

需要在确认后执行异步请求时使用 `onConfirm`，公共对话框会在请求期间锁定关闭操作并显示 loading；回调抛错时对话框保持打开，由业务调用方显示错误信息。`highlight`、`notice` 和 `width` 仅用于确认内容的强调、弱提示和受限宽度，不得绕过全局对话框另建页面级确认层。
