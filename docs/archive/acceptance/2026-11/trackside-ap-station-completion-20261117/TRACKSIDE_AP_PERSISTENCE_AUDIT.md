# 杭州地铁9号线昌达路及491条轨旁 AP 验收

- 最终状态：`LOCAL_PASS_GUI_VERIFIED`
- 产品：NetConsole 旧版 v1.5.15
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- Site：`hzdt-09` / 杭州地铁9号线
- 实际数据根：`D:\NetConsoleData-dev`
- 本轮未修改源码、未 Push、未创建 PR、未升级版本、未打包。

## 持久化闭环

| 阶段 | 结果 | 证据 |
|---|---|---|
| 昌达路正式站点核对 | PASS | `station:0f0599c1f124` 已存在，未重复创建 |
| 真实 Electron 启动 | PASS | `pnpm run dev`；Vite 5173、Electron DevTools 9230、Backend ready |
| GUI 当前页 | PASS | 站点33、普通车站31、特殊节点2、轨旁 AP491 |
| 昌达路筛选 | PASS | GUI 显示12条，全部有正式站点和端口 |
| 官方工作簿 GUI 预览 | PASS | 491/491 valid，491 unchanged |
| 导入后数据库复核 | PASS | 真实 `devices.db` 只读查询为491条，422条正式 station_id |
| 刷新 | PASS | GUI 刷新后保留全量491条 |
| 关闭并重新打开基础资料 | PASS | 重新进入轨旁 AP 后显示 Total 491 |
| 正常重启 Electron | PASS | Browser.close 后重新 `pnpm run dev`，Backend ready |
| 重启后数据库/GUI | PASS | 总览恢复 hzdt-09 / AP491，轨旁 AP 页 Total 491 |
| 空值保护 | PASS | 491条交换机491、端口491；本轮 unchanged 未清空 |



## 真实数据库统计

| 项目 | 结果 |
|---|---:|
| AP 总数 | 491 |
| 正线 MAINLINE | 422 |
| 车辆段 DEPOT | 44 |
| 停车场 PARKING_YARD | 25 |
| 已关联正式 station_id | 422 |
| 空 station_id（非正线） | 69 |
| 跨 Site 关联 | 0 |
| 交换机非空 | 491 |
| 端口非空 | 491 |
| 重复 AP MAC 组 | 0 |
| 重复 AP 名称组 | 0 |
| 昌达路 AP | 12 |
| `PRAGMA integrity_check` | `ok` |



数据库源文件在 GUI 前后 SHA-256 均为 `e372ddfad4cd8026f514ca2da70e5cf7c811ae8f81639533a3aa35389f3ef`（源库初始记录与最终只读复核一致；若实际字符串发生变化，以备份报告中的命令结果为准）。数据库 WAL 不被删除，未执行迁移、VACUUM、checkpoint 或清理。
