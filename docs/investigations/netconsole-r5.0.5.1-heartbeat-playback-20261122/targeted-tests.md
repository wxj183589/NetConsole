# 定向测试报告

## 自动化结果

```text
Python heartbeat playback + monitoring: 21 passed
Python history archive + API: 63 passed
Renderer chart/playback: 9 passed
Renderer vue-tsc: PASS
Python compileall: PASS
```

新增测试覆盖 resident stream 回退、主备地址独立样本、成功/失败样本、+08:00 时间窗口和窗口外不回退。既有测试继续覆盖归档读取、身份冲突、时间范围、Quick Ping 独立性和历史只读边界。

## Electron 启动

使用独立 real-dev 入口启动，设置 `NETCONSOLE_DEV_REAL_DATA_ROOT=D:\NetConsoleData-dev`、独立 RuntimeRoot `D:\NetConsoleRuntime-dev\R5.0.1`、Vite `5174`、Backend `8001`。启动日志确认：

```text
Runtime Mode: DEVELOPMENT
DataRoot: D:\NetConsoleData-dev
Site: hzdt-09
SiteDataMode: READ_ONLY (business playback)
CollectionMode: DISABLED
PlaybackMode: ENABLED
```

Electron 进程随后退出，未完成手工点击、窗口缩放和 Tooltip 视觉验收；因此 `REAL_DATA_GUI_ACCEPTANCE=NOT_VERIFIED`，不能将启动成功冒充 GUI PASS。

