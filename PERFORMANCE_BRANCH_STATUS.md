# Performance Branch Status

日期：2026-08-26

## 474c8fe6

- commit：`474c8fe6f99d1acf892f53d3c431569a99707628`
- 作用：Phase1 数据加载性能基础与 profiling；收窄 FIT-AP 当前页详情读取、设备当前页 facts/tasks、轨旁 snapshot cache/revision 复用，并补 API/SQL/Repository/Renderer 计时。
- 修改模块：`apps/desktop_renderer` API/table/site-switch、Backend profiling、AC Query Service、Device/Trackside query、测试和 `PERFORMANCE_REPORT.md`。
- 依赖：基于 `f21b67dfdce8b068e9b12b2992d58545799ba29d`；属于 4a13213e 的性能基础。
- 是否可进入 main：已进入 main，保留为 merge parent `31aab267` 的祖先链。
- 风险：L4，共享 profiling、SQLite 连接、Renderer API、NcDataTable 和 Export/Artifact 消费者；合并后必须重跑消费者套件。

## 4a13213e

- commit：`4a13213e761344f1b25bd422d10630884e95013d`
- 作用：Phase1/Phase2 warm handoff；局点切换先显示 metadata，再以独立候选 Backend 后台接管，减少原有 backend restart 阻塞。
- 修改模块：Electron backend handoff/manager/runtime/lock、Renderer site-switch/current-site UI、桌面架构文档和测试。
- 依赖：父提交为 `474c8fe6`；复用其 profiling/Renderer site-switch 基础，不是独立的第二套 warm handoff。
- 是否可进入 main：已进入 main，保留为 merge parent `e6a05df8` 的祖先链。
- 风险：L4，跨进程 lock、动态端口、token/cookie/bootstrap、DataRoot 与窗口恢复；失败必须保持旧 Backend 和原局点。

## 重复性结论

- Phase1 性能优化与 warm handoff 没有重复实现同一 backend lifecycle。
- `474c8fe6` 负责 profiling、列表/snapshot 数据加载基础；`4a13213e` 负责 Electron Backend lifecycle 与局点接管。
- 当前 bounded LLDP/optical 变更只增加 Current/History authority 与 Trackside 只读消费，不重复实现 warm handoff，也不修改 backend lifecycle。

## 当前 main

当前主线 HEAD 为 `e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`；本轮工作区另有尚未提交的 LLDP/optical bounded current/history 与 DEV 验收报告。Python 400 项相关回归、Renderer 1209、Electron 282、两端 build/typecheck 通过；真实 Trackside export 仍为 PARTIAL。
