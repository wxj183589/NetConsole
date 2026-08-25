# Real Data Environment Report

日期：2026-08-26

## 环境

- code commit：`02fde6e9c9487b7d8edee2a0ff556f56c0f3d847`
- branch：`main`
- data_root：`D:\NetConsoleData-dev`
- 生产根 `D:\NetConsoleData`：本轮未访问、未写入、未复制、未迁移。
- 数据库访问：业务验证使用 DEV 根内 SQLite；只读 profiling 使用 `mode=ro`/`query_only`。桌面启动产生的 runtime 日志、Task 和 Artifact 也全部位于 DEV 根。

## 局点

DEV site registry 共 9 个局点条目：demo、杭州 10 号线、宁波 10 号线、宁波 12 号线、宁波 1 号线、宁波 6 号线、两条杭州 4 号线信号条目、sxl1。

## 数据库规模

| 局点 | devices.db | tasks.db | 代表性规模 |
| --- | ---: | ---: | --- |
| 杭州 10 号线 | 424,132,608 bytes（约 404.48MiB） | 约 90.88MiB | devices 34，interfaces 1,561，FIT resources 491，AP history 35,496 |
| 宁波 12 号线 | 92,807,168 bytes（约 88.51MiB） | 约 265.10MiB | devices 100，interfaces 3,538，FIT resources 992，snapshot rows 157,423 |
| 宁波 10 号线 | 约 163.55MiB | 约 33.44MiB | devices 116，interfaces 2,138，FIT resources 591 |
| 宁波 6 号线 | 约 17.37MiB | 约 8.09MiB | devices 68，FIT resources 约 3 个站点目录规模 |

其它 SQLite 内容包括各站点的 history/state、Task Center 表、MESH 分析索引和导出任务记录；没有对任何生产数据库执行迁移或清理。

## 完整性结论

局点 registry、数据库文件、主要设备事实、FIT-AP 资源和 MESH 分析数据均可读；宁波 12 号线存在大规模历史数据，是本轮 Trackside snapshot 的真实压力场景。个别局点详情数据缺少 radio detail，按业务数据缺口记录，不在验收现场补数据。
