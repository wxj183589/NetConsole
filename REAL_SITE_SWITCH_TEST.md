# Real Site Switch Test

日期：2026-08-26

## 范围

数据根：`D:\NetConsoleData-dev`。最终代码：`02fde6e9c9487b7d8edee2a0ff556f56c0f3d847`。

## 本轮桌面启动

使用 Electron Desktop + DEV 数据根启动一次：

| 阶段 | 耗时 |
| --- | ---: |
| backend first stdout | 1,849ms |
| backend health ready | 2,489ms |
| renderer load finished | 5,092ms |
| desktop interactive | 6,032ms |

当前日志块已确认 build identity 为最终 commit；未发现 backend restart、backend exit、migration 或 schema mismatch。进程停止后 5174 端口已释放。

## 局点交替

本轮没有再次用 GUI 完成“杭州 10 号线 ↔ 宁波 12 号线”的完整首次进入、返回和交替序列，因此不能把本轮启动结果等同于最终切换验收。

已合入 main 的 warm handoff 历史 DEV 证据为 2026-08-22 交替 6 次：metadata ready 362–453ms，P95 453ms；完整后台 Backend 接管仍为 13.6–15.1s，但 metadata 不再等待冷重启。该代码路径在最终 commit 未被本轮 Phase2 修改。

## 结论

**PARTIAL**：最终代码启动链路通过，未观察到本次启动的 restart/migration；8.5–14.4s 的完整局点切换是否在最终 commit 上仍保留，需要补做两局点 GUI 交替、再次进入、返回和异常恢复验收。
