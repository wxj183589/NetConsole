# Web 视觉测试

本目录提供共享表格与局点管理视觉夹具页面。截图和 DOM 断言由 Playwright 配置驱动，局点夹具只使用拦截的假 API 和假 Electron Bridge，不写入业务运行数据；修改相关展示契约时同步更新视觉测试和说明。

`ground.html` 挂载真实地面无人值守 Vue 页面，`ground-unattended.visual.spec.ts` 仅以 HTTP Mock 提供合成局点、列车、MR、心跳及日志数据。覆盖十页导航、MR 主备 IP 详情与快速 Ping 入口/启停、Syslog/时间轴服务端筛选分页、剩余高度和外层横向溢出。它不连接真实数据目录、后端或设备。

从 `apps/desktop_renderer` 运行：

```powershell
pnpm exec playwright test ground-unattended.visual.spec.ts --project='1920x1080@100%' --project='1920x1080@125%' --project='2560x1440@100%' --workers=1
```

125% 项目同时使用 1.25 像素密度和缩小的 CSS viewport，仿真相同物理屏幕在缩放后可用空间；这不等同 Windows 原生 125% 缩放或 Electron 实机验收。截图写入仓库既定 `.local/tests/renderer-visual`，后续 Playwright 运行会刷新该临时证据目录。
