# NetConsole v1.5.16 Portable 启动专项调查

## 结论

`PORTABLE_ROOT_CAUSE=TEST_HARNESS_CONFIGURATION_ERROR`

没有确认 v1.5.16 Portable 产品启动缺陷。原始超时复现使用了 `Workspace\temp` 下的数据根，同时设置了 `NETCONSOLE_RUNTIME_MODE=test` 和 `NETCONSOLE_STORAGE_MODE=isolated_test`。Electron 的隔离存储校验只接受 `Workspace\test-data\NetConsole`，因此启动配置不能安全通过；GUI 配置错误对话框没有被 headless 脚本关闭，脚本随后把等待误报为启动超时。另一次复现没有使用 `NETCONSOLE_ISOLATED_SMOKE=1`，本机已有正式版 NetConsole 实例，单实例转交也使该测试不能作为产品启动证据。

## 正确隔离复现

- ZIP：`release/v1.5.16/build-0-6e72b67a/NetConsole-1.5.16-portable.zip`
- 测试根：`D:\study\NetConsole-Workspace\test-data\NetConsole\v1.5.16-runtime-audit-default-20261120`
- 运行标记：`NETCONSOLE_ISOLATED_SMOKE=1`；未连接 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`
- 默认数据根：`<portable>\data`
- 进程退出：code `0`，约 `8.16 s`
- Backend 首次 stdout：`1885 ms`
- Backend health ready：`2881.4 ms`
- Renderer DOM ready：约 `4928.2 ms`
- Renderer mounted：`5127.8 ms`
- Desktop interactive：`5211.7 ms`
- Renderer stable：约 `6798 ms`
- Shutdown complete：约 `1171 ms`，Backend exit code `0`
- Smoke 事件：`SHUTDOWN_STARTED`、`DOWNLOADS_STOPPED`、`BACKEND_STOPPED`、`EXIT_REQUESTED`、`EXIT_RETURNED`

## 数据根契约

- 默认根创建空 `default` / `默认局点`，`devices` 表为 `0` 条；未发现 Demo/example 数据库。
- `portable-data-root.json` 自定义根连续两次运行通过：约 `8.27 s` 和 `7.84 s`；日志均为 `source=portable_configuration`，Backend health 和 `desktop.interactive` 均完成。
- 将配置指向测试根内的普通文件时，程序保持 Fail Closed，未改写默认根、自定义根或目标文件；由于错误对话框等待用户关闭，自动脚本主动停止该进程，不能把它记录为正常退出 PASS。
- 原始测试根和本次证据均位于 Workspace `test-data`；真实 Production/Dev Authority 未访问。

## 原始超时证据解释

原始 `build-0-6e72b67a` 报告记录的 `PARTIAL_TIMEOUT` 保留为历史事实。该结果不能单独证明产品缺陷，因为当时测试根违反了 `isolated_test` 路径契约，且有一次测试受现有正式版单实例影响。修正测试根和单实例隔离后，实际 Portable 启动、Backend、Health、Renderer 和关闭链均通过。

## 状态

`PORTABLE_PRODUCT_DEFECT=NOT_CONFIRMED`
`PORTABLE_STARTUP=PASS_WITH_CORRECT_ISOLATION`
`PORTABLE_FAIL_CLOSED=PASS_WITH_DIALOG_LIMITATION`
