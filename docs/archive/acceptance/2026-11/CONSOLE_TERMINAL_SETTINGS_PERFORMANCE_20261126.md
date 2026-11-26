# Console 终端设置性能报告

## 验收范围

在 Windows 实际 Electron 43.1.1 进程和隔离测试数据根中，使用 1920×1080 窗口打开 Console，保持两个隔离 SSH 标签及左右分屏，反复打开和关闭终端设置弹窗 30 次。设置读取使用 Console 已缓存数据，未访问生产数据或真实开发数据。

## 实测结果

| 指标 | 结果 | 状态 |
| --- | --- | --- |
| 弹窗重开次数 | 30 | PASS |
| 由点击到弹窗可见 | 中位数 28 ms，最小 24 ms，最大 32 ms | PASS |
| 设置数据读取 | 缓存命中，记录为 0 ms | PASS |
| 表单渲染 | 范围 6–43 ms，31 次测量中常见值为 6 ms | PASS |
| 弹窗外壳埋点 | 范围 6–44 ms | PASS |
| Renderer long-task 总时长 | 0 ms | PASS |
| SSH 标签和分屏保留 | 30 次操作期间未关闭或重新连接 | PASS |

点击到可见时间来自 Playwright 外部计时，浏览器 `performance.measure` 记录外壳、读取和表单渲染时间。long-task 总时长来自 Renderer Performance API。缓存读取 0 ms 表示本次读缓存副本所测耗时小于整数毫秒精度，不代表冷启动读取耗时为零。

## 证据

Workspace `reports/tests/console-1.5.19-resume-20261126/console-serial-electron-20261126/serial-electron-evidence.json` 保存 30 个点击到可见样本和 Renderer 埋点。`console-electron-1920x1080-settings.png`、`console-electron-1920x1080-serial.png` 记录混合 SSH 标签、分屏、设置窗和串口窗。自动化运行日志位于同目录上一级的 `console-serial-electron-20261126.log`。

此结果覆盖已连接 SSH 时的缓存设置读取及反复开关。冷启动首次读取、已连接 Telnet 时打开、持续大量终端输出并发、设置保存失败注入和 30 次循环后的进程级内存曲线未在本轮测量，保持 NOT VERIFIED。

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=0`。
