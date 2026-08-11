# 系统设置表单组件

`NcExecutablePathField.vue` 统一展示可执行文件路径、选择、清空、可选试启动和字段级校验反馈。按钮使用独立 `inline-flex` 容器和固定间距，不放入 `el-input` suffix/append；窄于 900px 时按钮组换到下一行。

终端 executable basename 定义来自 `apps/desktop_electron/src/shared/bridge.ts`。Renderer 只向 Electron Main 发送语义化 `toolId`，不能传入扩展名或任意 allowlist。
