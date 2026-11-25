# Phase 7 Electron 实际桌面验收

2026-11-25，源码 Electron 43.1.1 / Chrome 150，使用已有正常 `scripts/dev.mjs --isolated-test-data` 入口。数据根为 Workspace 下 `phase7-readonly-lab-5597ce3b04`，局点为 `phase7-lab`。当前完成源码桌面交互验收，安装态验收单独记录。

## 窗口与截图

通过 Win32 SetWindowPos 调整实际 Electron 窗口 client area，逐次读取 Renderer 的 innerWidth/innerHeight，确认 1920×1080、2560×1440、1648×927、1280×720。截图来自该 Electron WebContents 的 CDP 连接。

截图目录为 `D:/study/NetConsole-Workspace/reports/diagnostic/netconsole-phase7-20261125/screenshots`。十三组状态各四张，共 52 张 PNG，文件名包含状态和窗口尺寸。

| 状态 | 文件名前缀 | 实际操作 |
| --- | --- | --- |
| 网络服务总览 | network-services | HTTPS 独立 Worker 运行，PID、CPU、内存与监听端口可见 |
| 服务配置 | service-config | FTP 用户、上传权限、被动端口与 TLS 配置 |
| 服务日志 | service-logs | HTTPS 配置与启动记录 |
| 双面板文件 | file-manager | 本地受管目录和 HTTP 服务根 |
| 文件传输 | file-transfer | 上传、复制、SHA-256 结果 |
| 任务中心 | task-center | 真实 AC/AC2/SW 任务与导出历史 |
| 任务详情 | task-details | 逐设备状态及真实查询结果 |
| 模板编辑 | template-editor | 自定义只读 Jinja2 模板和参数 |
| 模板预览 | template-preview | 滚动至渲染后的 display 查询命令 |
| 日志中心 | log-center | 真实隔离运行日志列表 |
| 服务日志中心 | service-log-center | 选择 HTTPS，查询实际服务日志 |
| 组织结构 | infrastructure | 三台实验设备与空工程关系概览 |
| 真实 SFTP | device-sftp | SW SFTP 根目录与下载至本地的 startup.cfg |

部分布局数据保存在同目录 `layout-metrics.json`。已查看窄屏文件传输、窄屏模板弹窗与宽屏网络服务截图。页面使用内部滚动，窄屏模板正文滚动后可访问预览，页脚操作保持可达。当前组织结构样本规模为三台设备，长组织树人工验收仍为 NOT VERIFIED。

## 已执行交互

- HTTPS 经正常受鉴权 API 初始化、配置回环端口 58443 并启动，真实 UI 显示运行状态与独立 PID 57584。
- Jinja2 预览生成 `display transceiver diagnosis interface GigabitEthernet1/0/1`，没有提交设备配置命令。
- 浏览真实历史任务，逐设备 AC、AC2、SW 为成功，查询结果可展开。
- 文件面板通过原生文件 input 上传 46 字节 fixture，复制到 HTTP 根，提交 SHA-256 校验。三个完成任务显示相同 SHA-256 `656812c8539041dbb92ebc40721ccc64daa7aea17247700eb90f9e2308150219`。
- 点击“另存为”，实际打开 Windows 原生对话框，通过 UI Automation 填写并保存。Electron 日志包含 SAVE_TARGET_SELECTED、DOWNLOAD_VERIFIED、LOCAL_FILE_COMMITTED，46 字节文件哈希一致。自动填路径时对话框保存到工作树 `.github`，已校验并将该本轮 fixture 移至 Workspace 报告目录 `electron-save-as.txt`。
- 选择 SW 192.168.56.3，经既有 SFTP 入口建立独立会话，读取根目录并下载 `startup.cfg`，本地受管下载目录显示 6879 字节，SHA-256 为 `8655c702e17beea70a2b2c12c4179596115ca592c66e09fc033726c54cafed11`。设备端执行文件读取，写入为零。
- 统一日志中心切换运行日志与网络服务日志，选择 HTTPS 查询启动日志，界面可刷新。

## 本轮发现与修复

1. 服务列表数据返回后，带 v-for 的条件显示仍留下 display:none，实际总览不可见。改为对渲染集合判断服务是否加载，实际 Electron 复验通过。
2. 新旧 canonical 路由与 Electron Workspace 白名单不一致，产生 route is not allowed 并损失工作区恢复。补齐精确路由与 snapshot 回归。
3. close-to-tray 关闭时，Renderer loading 隐藏窗口触发 visible-count=0，从而提前退出应用。可见数回调现在只更新托盘上下文，真实关窗仍走 window-all-closed 生命周期。实际重启、加载和设置为 false 后运行通过。
4. AppLayout 静态测试沿用旧 routeCacheKey 写法，已跟随 Phase 6 AppRouteView 的 route-name 前缀合同更新断言。

首次打开任务结果时 Vite 新依赖优化触发整页 reload，弹窗随之关闭。预热依赖后四种窗口尺寸重测任务详情均保持显示。开发模式两次出现 ResizeObserver loop completed with undelivered notifications，交互继续可用，正式构建观察待包级验收补充。

## 生命周期与待验收

第一轮隔离 Electron 关闭后，其 HTTPS Worker PID 43736 已退出。第二轮 HTTPS 连续运行 887 秒后主动断开 SFTP、关闭窗口，日志记录 shutdown_ack、shutdown_complete、Backend PID 51384 code=0 及 Electron 完整关闭，总耗时 1657ms。再次查询 Electron PID 49532 与 HTTPS PID 57584，均已退出。关闭前运行事实保存在截图目录 `electron-lifecycle.json`。

完整 Windows 原生安装、升级、卸载、跨机器验收、真实非零 MESH 链路与 FIT-AP 独立任务仍待验证。SOURCE_ELECTRON_INTERACTION=PASS，PACKAGED_GUI=NOT VERIFIED。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DEVICE_CONFIGURATION_WRITES=0
DATABASES_REMOVED=0
```
