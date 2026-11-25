# 杭州地铁 9 号线与 10 号线真实数据对比

状态：**PARTIAL**

## 数据规模

| 数据集 | 文件数 | 解压大小 | 主要站点目录 |
| --- | ---: | ---: | --- |
| HZL9 | 521 | 0.57 GiB | `sites/hzdt-09` |
| HZL10 | 24,249 | 22.92 GiB | `sites/hzl10` |

## Schema 与数据量差异

- 两套数据均包含 `devices.db`、`tasks.db`、Ground `index.sqlite` 和 `vehicle_mr_online.sqlite`。
- HZL9 的 Ground 数据包含 2 个 Quick Ping run、15,485 条 ping summary、6,818 条 MESH 事件和 2,304 条 AC 快照。
- HZL10 的 Ground 数据包含 6 个 run、562,861 条 ping summary、297,397 条 MESH 事件和 358,870 条 AC 快照。
- HZL10 的设备库包含 948 个 AP 资源、1,896 条射频记录、105,958 条接口历史和 104,858 条光模块历史，规模显著高于 HZL9。
- HZL10 的车辆 MR 链路表有 1,999,008 行，HZL9 有 2,315 行。
- HZL10 的 `devices.db`、Ground 和车辆 MR SQLite 均明显更大，适合后续大数据分页和索引专项。

## 功能与性能状态

| 项目 | HZL9 | HZL10 |
| --- | --- | --- |
| 结构审计 | PASS | PASS |
| 只读 SQLite 查询 | PASS | PASS |
| Ground/MESH 历史可用 | PASS_WITH_EVIDENCE_CAVEATS | PASS_WITH_EVIDENCE_CAVEATS |
| Quick Ping 历史 | PASS_WITH_EVIDENCE_CAVEATS | NOT AVAILABLE（当前 Ground 表无 Quick Ping 记录） |
| Electron/Backend 真实回放 | NOT VERIFIED | NOT VERIFIED |
| Windows 安装态与 Worker | NOT VERIFIED | NOT VERIFIED |
| 冷启动、页面首开、内存/CPU | NOT VERIFIED | NOT VERIFIED |

## 数据安全

- 原始压缩包保留在 `D:\下载\20261125`，未修改或删除。
- 两套数据在 Workspace 内独立解压，未互相覆盖。
- 未修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未提交真实数据。

## 后续验证边界

需要在隔离 DataRoot 上启动真实 Backend/Electron，执行页面回放、分页、图表、任务历史和内存/CPU采样。由于本轮没有启动安装态产品，以上项目保持 NOT VERIFIED。
