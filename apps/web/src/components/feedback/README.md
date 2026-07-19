# 全局确认对话框

业务页面通过 `useConfirm().confirm()` 请求确认，由 `NcConfirmDialog` 在应用根节点统一渲染。确认类型固定为 `INFO`、`WARNING`、`DANGER`、`SECURITY`、`DESTRUCTIVE`；高风险动作必须使用动作化按钮文案，不能重新调用 `window.confirm` 或页面私有弹窗。
